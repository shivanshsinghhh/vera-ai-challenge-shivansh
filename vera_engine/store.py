from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

VALID_SCOPES = {"category", "merchant", "customer", "trigger"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class ContextRecord:
    version: int
    payload: dict[str, Any]
    delivered_at: str


@dataclass
class ConversationState:
    conversation_id: str
    merchant_id: Optional[str]
    customer_id: Optional[str]
    trigger_id: Optional[str]
    trigger_kind: Optional[str]
    last_body: str = ""
    turns: list[dict[str, Any]] = field(default_factory=list)
    auto_reply_count: int = 0
    last_inbound_normalized: str = ""
    accepted: bool = False
    closed: bool = False


class ContextStore:
    """Thread-safe in-memory state for one judging run."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.contexts: dict[tuple[str, str], ContextRecord] = {}
        self.suppression_keys: set[str] = set()
        self.conversations: dict[str, ConversationState] = {}
        self.recent_bodies: set[str] = set()

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def put(self, scope: str, context_id: str, version: int, payload: dict[str, Any], delivered_at: str) -> tuple[str, Optional[int]]:
        """Return (status, current_version). status in accepted|duplicate|stale|invalid."""
        if scope not in VALID_SCOPES or not context_id or not isinstance(payload, dict) or not isinstance(version, int):
            return "invalid", None
        key = (scope, context_id)
        with self._lock:
            current = self.contexts.get(key)
            if current is not None:
                if version < current.version:
                    return "stale", current.version
                if version == current.version:
                    return "duplicate", current.version
            self.contexts[key] = ContextRecord(version=version, payload=payload, delivered_at=delivered_at)
            return "accepted", version

    def get_record(self, scope: str, context_id: Optional[str]) -> Optional[ContextRecord]:
        if not context_id:
            return None
        with self._lock:
            return self.contexts.get((scope, context_id))

    def get(self, scope: str, context_id: Optional[str]) -> Optional[dict[str, Any]]:
        rec = self.get_record(scope, context_id)
        return rec.payload if rec else None

    def counts(self) -> dict[str, int]:
        counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
        with self._lock:
            for scope, _ in self.contexts:
                counts[scope] = counts.get(scope, 0) + 1
        return counts

    def mark_suppressed(self, key: str) -> bool:
        """Atomically reserve a suppression key. Returns False if it already fired."""
        if not key:
            return True
        with self._lock:
            if key in self.suppression_keys:
                return False
            self.suppression_keys.add(key)
            return True

    def is_suppressed(self, key: str) -> bool:
        if not key:
            return False
        with self._lock:
            return key in self.suppression_keys

    def save_conversation(self, state: ConversationState) -> None:
        with self._lock:
            self.conversations[state.conversation_id] = state

    def get_conversation(self, conversation_id: str) -> Optional[ConversationState]:
        with self._lock:
            return self.conversations.get(conversation_id)

    def add_recent_body(self, body: str) -> bool:
        """Returns False if body has been seen globally this run."""
        normalized = " ".join(body.lower().split())
        with self._lock:
            if normalized in self.recent_bodies:
                return False
            self.recent_bodies.add(normalized)
            # Bounded enough for the challenge, but avoid unbounded process growth.
            if len(self.recent_bodies) > 5000:
                self.recent_bodies.clear()
                self.recent_bodies.add(normalized)
            return True

    def teardown(self) -> None:
        with self._lock:
            self.contexts.clear()
            self.suppression_keys.clear()
            self.conversations.clear()
            self.recent_bodies.clear()
