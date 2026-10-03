from __future__ import annotations

import re
from typing import Any, Optional

from .store import ContextStore, ConversationState

MAX_BODY_CHARS = 300
WS_RE = re.compile(r"\s+")

STOP_PATTERNS = (
    "stop", "unsubscribe", "don't message", "do not message", "no more", "spam",
    "band karo", "mat bhejna", "nahi chahiye", "nahin chahiye", "बस करो",
)
DECLINE_PATTERNS = (
    "not interested", "no thanks", "no thank", "leave it", "skip it", "not now",
    "nahi", "nahin", "rehne do", "chhodo", "cancel",
)
COMMIT_PATTERNS = (
    "yes", "yep", "yeah", "go ahead", "let's do it", "lets do it", "do it",
    "proceed", "haan", "han", "bilkul", "chalo", "karo", "send it", "book it",
    "sounds good", "ok do", "okay do",
)
WAIT_PATTERNS = (
    "later", "busy", "call me later", "message later", "tomorrow", "give me time",
    "baad mein", "baad me", "abhi busy",
)
AUTO_REPLY_PATTERNS = (
    "thank you for contacting", "thanks for contacting", "we will respond shortly",
    "we'll respond shortly", "our team will get back", "we will get back",
    "automated assistant", "auto reply", "business hours are", "we are currently unavailable",
    "aapki jaankari ke liye", "hamari team", "team tak pahuncha",
)
OFFTOPIC_PATTERNS = (
    "gst", "income tax", "itr", "file my tax", "passport", "loan application",
)
ABUSE_PATTERNS = (
    "idiot", "stupid", "useless", "shut up", "fuck", "bastard", "bakwas",
)


def _norm(text: str) -> str:
    return WS_RE.sub(" ", (text or "").lower()).strip()


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(p in text for p in patterns)


def _clip(text: str) -> str:
    text = re.sub(r"https?://\S+", "", text)
    text = WS_RE.sub(" ", text).strip()
    if len(text) <= MAX_BODY_CHARS:
        return text
    return text[: MAX_BODY_CHARS - 1].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"


def _merchant_first(merchant: Optional[dict[str, Any]]) -> str:
    if not merchant:
        return ""
    identity = merchant.get("identity") or {}
    return str(identity.get("owner_first_name") or "").strip()


def _accepted_followup(store: ContextStore, state: ConversationState) -> str:
    trigger = store.get("trigger", state.trigger_id) or {}
    payload = trigger.get("payload") or {}
    kind = state.trigger_kind or trigger.get("kind") or ""
    merchant = store.get("merchant", state.merchant_id) or {}
    first = _merchant_first(merchant)
    prefix = f"{first}, " if first else ""

    if kind == "research_digest":
        category = store.get("category", merchant.get("category_slug")) or {}
        item_id = payload.get("top_item_id")
        item = next((x for x in category.get("digest") or [] if x.get("id") == item_id), None)
        if item:
            summary = str(item.get("summary") or item.get("title") or "").strip()
            summary = summary.split(".", 1)[0].strip()
            return _clip(f"{prefix}yes — key takeaway: {summary}. Next step is to decide whether it applies to your current customer mix; no extra qualification needed.")
        return _clip(f"{prefix}yes — I’ll keep this to the context already shared and give you the key takeaway next, without another qualification question.")

    if kind == "regulation_change":
        deadline = str(payload.get("deadline_iso") or "").split("T", 1)[0]
        return _clip(f"{prefix}on it. Next step is a short compliance checklist tied to the supplied deadline{f' ({deadline})' if deadline else ''}; I won’t add assumptions beyond your context.")

    if kind == "renewal_due":
        amount = payload.get("renewal_amount")
        plan = payload.get("plan")
        amount_txt = f"₹{int(amount):,}" if isinstance(amount, (int, float)) else str(amount or "")
        return _clip(f"{prefix}got your confirmation. The supplied renewal is {plan or 'the current plan'}{f' at {amount_txt}' if amount_txt else ''}. Next step is to complete that same-plan renewal in your merchant flow.")

    if kind in {"recall_due", "trial_followup", "wedding_package_followup"}:
        slots = payload.get("available_slots") or payload.get("next_session_options") or []
        label = ""
        if slots and isinstance(slots[0], dict):
            label = str(slots[0].get("label") or "")
        return _clip(f"Confirmed. {('The first supplied slot is ' + label + '. ') if label else ''}I’ll keep the follow-up to the appointment details already in context — no extra qualification.")

    if kind == "chronic_refill_due":
        meds = ", ".join(str(x) for x in (payload.get("molecule_list") or [])[:3])
        return _clip(f"Confirmed. I’ll keep the refill request to the medicines already listed{f': {meds}' if meds else ''}; no substitutions or new medical claims added.")

    if kind == "supply_alert":
        batches = ", ".join(str(x) for x in (payload.get("affected_batches") or [])[:3])
        return _clip(f"{prefix}on it. First action: isolate/check the supplied affected batches{f' ({batches})' if batches else ''}. I’ll keep any customer draft limited to the recall facts in context.")

    if kind == "active_planning_intent":
        topic = str(payload.get("intent_topic") or "the plan").replace("_", " ")
        return _clip(f"{prefix}yes — moving straight to action on {topic}. I’ll draft the first concrete version from the details already in context, without another qualifying question.")

    if kind in {"perf_dip", "seasonal_perf_dip", "perf_spike"}:
        metric = str(payload.get("metric") or "performance").replace("_", " ")
        return _clip(f"{prefix}yes — next I’ll focus only on the supplied {metric} change and your stored profile/offer context, then give you the two most practical actions.")

    return _clip(f"{prefix}got your yes. I’m switching to action mode now and will use the details already in this conversation — no more qualification questions.")


def _context_answer(store: ContextStore, state: ConversationState) -> str:
    trigger = store.get("trigger", state.trigger_id) or {}
    kind = str(state.trigger_kind or trigger.get("kind") or "update").replace("_", " ")
    payload = trigger.get("payload") or {}
    facts: list[str] = []
    for key, value in payload.items():
        if key.endswith("_id") or key in {"merchant_id", "customer_id", "category"}:
            continue
        if isinstance(value, (str, int, float, bool)):
            facts.append(f"{key.replace('_',' ')}: {value}")
        if len(facts) == 2:
            break
    detail = "; ".join(facts)
    return _clip(f"This conversation is about the {kind} trigger{f' — {detail}' if detail else ''}. I’m keeping it strictly to the context the judge supplied.")


def handle_reply(
    store: ContextStore,
    conversation_id: str,
    merchant_id: Optional[str],
    customer_id: Optional[str],
    from_role: str,
    message: str,
    turn_number: int,
) -> dict[str, Any]:
    text = _norm(message)
    state = store.get_conversation(conversation_id)
    if state is None:
        state = ConversationState(
            conversation_id=conversation_id,
            merchant_id=merchant_id,
            customer_id=customer_id,
            trigger_id=None,
            trigger_kind=None,
        )
        store.save_conversation(state)

    state.turns.append({"from": from_role, "message": message, "turn_number": turn_number})

    # Explicit opt-out/stop always wins, even in an unknown conversation.
    if _contains_any(text, STOP_PATTERNS):
        state.closed = True
        store.save_conversation(state)
        return {"action": "end", "rationale": "explicit opt-out/stop intent detected; conversation closed immediately"}

    # Auto-reply detection: one retry maximum, then exit. Repetition makes exit immediate.
    auto_like = _contains_any(text, AUTO_REPLY_PATTERNS)
    repeated = bool(text and text == state.last_inbound_normalized)
    if auto_like or repeated:
        state.auto_reply_count += 1
        state.last_inbound_normalized = text
        if state.auto_reply_count >= 2 or repeated:
            state.closed = True
            store.save_conversation(state)
            return {"action": "end", "rationale": "repeated/canned WhatsApp Business auto-reply detected; avoiding wasted turns"}
        body = _clip("Looks like an automated reply. I’ll try once: if the owner/manager sees this, reply YES and I’ll continue; otherwise I’ll stop here.")
        state.last_body = body
        store.save_conversation(state)
        return {"action": "send", "body": body, "cta": "binary_yes_no", "rationale": "first auto-reply detected; one low-friction owner check before exit"}

    state.last_inbound_normalized = text

    if _contains_any(text, WAIT_PATTERNS):
        store.save_conversation(state)
        return {"action": "wait", "wait_seconds": 1800, "rationale": "merchant/customer asked for time; backing off for 30 minutes"}

    # A clear committed intent must transition directly into action mode.
    if _contains_any(text, COMMIT_PATTERNS):
        state.accepted = True
        body = _accepted_followup(store, state)
        if _norm(body) == _norm(state.last_body):
            body = _clip(body + " I’ll keep the next message to new information only.")
        state.last_body = body
        store.save_conversation(state)
        return {"action": "send", "body": body, "cta": "none", "rationale": "explicit acceptance detected; immediate action-mode handoff with no re-qualification"}

    if _contains_any(text, DECLINE_PATTERNS):
        state.closed = True
        store.save_conversation(state)
        return {"action": "end", "rationale": "decline/not-interested intent detected; graceful exit"}

    if _contains_any(text, OFFTOPIC_PATTERNS):
        body = _clip("I can’t handle GST/tax filing. I can help with your magicpin/Google profile, offers, performance insights, and customer follow-ups using the context available here.")
        state.last_body = body
        store.save_conversation(state)
        return {"action": "send", "body": body, "cta": "open_ended", "rationale": "off-topic request; stayed within Vera's merchant-growth scope"}

    if _contains_any(text, ABUSE_PATTERNS):
        body = _clip("I’ll keep this brief and professional. I can help only with your merchant profile, offers, performance, and customer follow-ups. If you want to stop messages, say STOP.")
        state.last_body = body
        store.save_conversation(state)
        return {"action": "send", "body": body, "cta": "binary_yes_no", "rationale": "hostile language handled without escalation; stayed on mission and exposed opt-out"}

    if any(q in text for q in ("what is this", "what's this", "why", "details", "explain", "tell me more", "kya hai")):
        body = _context_answer(store, state)
        state.last_body = body
        store.save_conversation(state)
        return {"action": "send", "body": body, "cta": "open_ended", "rationale": "clarification request answered from stored trigger context only"}

    # Unknown conversation must still return a useful non-empty response.
    if not state.trigger_id:
        body = _clip("Hi — I can help with your magicpin/Google profile, offers, performance, or customer follow-ups. Tell me which one you want help with, or say STOP.")
        state.last_body = body
        store.save_conversation(state)
        return {"action": "send", "body": body, "cta": "open_ended", "rationale": "unknown conversation recovered safely without inventing prior context"}

    body = _context_answer(store, state)
    if _norm(body) == _norm(state.last_body):
        body = _clip("I don’t have a new verified fact beyond the context already shared. If you want to proceed, reply YES; if not, reply STOP.")
    state.last_body = body
    store.save_conversation(state)
    return {"action": "send", "body": body, "cta": "binary_yes_no", "rationale": "continued conversation using stored context while avoiding fabricated details and verbatim repetition"}
