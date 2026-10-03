"""Offline composition entry-point for challenge variants that import bot.compose()."""
from __future__ import annotations

from typing import Any, Optional

from vera_engine.composer import compose_message


def compose(
    category: dict[str, Any],
    merchant: dict[str, Any],
    trigger: dict[str, Any],
    customer: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    result = compose_message(category, merchant, trigger, customer)
    if result is None:
        return {
            "body": "",
            "cta": "none",
            "send_as": "merchant_on_behalf" if trigger.get("scope") == "customer" else "vera",
            "suppression_key": str(trigger.get("suppression_key") or ""),
            "rationale": "No message sent: required customer consent/context was unavailable or incompatible.",
        }
    return {
        "body": result["body"],
        "cta": result["cta"],
        "send_as": result["send_as"],
        "suppression_key": result["suppression_key"],
        "rationale": result["rationale"],
    }
