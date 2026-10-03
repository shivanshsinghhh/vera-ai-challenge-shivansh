from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

MAX_BODY_CHARS = 300
URL_RE = re.compile(r"https?://\S+", re.I)
WS_RE = re.compile(r"\s+")


@dataclass
class ComposeResult:
    body: str
    cta: str
    send_as: str
    suppression_key: str
    rationale: str
    template_name: str
    template_params: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "body": self.body,
            "cta": self.cta,
            "send_as": self.send_as,
            "suppression_key": self.suppression_key,
            "rationale": self.rationale,
            "template_name": self.template_name,
            "template_params": self.template_params,
        }


def _s(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value).strip()


def _clean_text(value: Any, limit: int = 100) -> str:
    text = URL_RE.sub("", _s(value))
    text = WS_RE.sub(" ", text).strip(" ,.;")
    return text[:limit]


def _first_name(merchant: dict[str, Any]) -> str:
    identity = merchant.get("identity") or {}
    owner = _clean_text(identity.get("owner_first_name"), 30)
    if owner:
        return owner
    name = _clean_text(identity.get("name"), 60)
    if name.lower().startswith("dr. "):
        parts = name.split()
        return parts[1].strip("'s") if len(parts) > 1 else name
    return name.split()[0] if name else "there"


def _merchant_name(merchant: dict[str, Any]) -> str:
    return _clean_text((merchant.get("identity") or {}).get("name"), 80) or "your business"


def _locality(merchant: dict[str, Any]) -> str:
    identity = merchant.get("identity") or {}
    return _clean_text(identity.get("locality") or identity.get("city"), 50)


def _customer_name(customer: Optional[dict[str, Any]]) -> str:
    if not customer:
        return ""
    name = _clean_text((customer.get("identity") or {}).get("name"), 60)
    return name or "there"


def _customer_addressee(customer: Optional[dict[str, Any]]) -> tuple[str, str]:
    """Return (person_to_address, subject_name). Handles child profiles routed via a parent."""
    name = _customer_name(customer)
    if not customer:
        return name, name
    channel = _clean_text((customer.get("preferences") or {}).get("channel"), 50).lower()
    m = re.match(r"^(.*?)\s*\(parent:\s*([^\)]+)\)\s*$", name, flags=re.I)
    if m and "parent" in channel:
        child = m.group(1).strip()
        parent = m.group(2).strip()
        return parent, child
    return name, name


def _service_label(value: Any) -> str:
    raw = _s(value)
    m = re.match(r"^(\d+)_month_(.+)$", raw)
    if m:
        return f"{m.group(1)}-month {m.group(2).replace('_', ' ')}"
    return _slug_words(raw)


def _program_label(value: Any) -> str:
    raw = _s(value)
    m = re.match(r"^(.*)_([0-9]+)day$", raw)
    if m:
        return f"{m.group(2)}-day {m.group(1).replace('_', ' ')}"
    return _slug_words(raw)


def _trend_label(value: Any) -> str:
    raw = _s(value)
    m = re.match(r"^(.*)_([+-]?[0-9]+(?:\.[0-9]+)?)$", raw)
    if m:
        return f"{m.group(1).replace('_', ' ')} {m.group(2)}%"
    return _slug_words(raw)


def _language_pref(customer: Optional[dict[str, Any]], merchant: dict[str, Any]) -> str:
    if customer:
        pref = _clean_text((customer.get("identity") or {}).get("language_pref"), 40).lower()
        if pref:
            return pref
    langs = [str(x).lower() for x in (merchant.get("identity") or {}).get("languages", [])]
    return "hi-en mix" if "hi" in langs else "english"


def _pct(value: Any, absolute: bool = True) -> str:
    try:
        x = float(value)
    except Exception:
        return ""
    if abs(x) <= 1.5:
        x *= 100
    if absolute:
        x = abs(x)
    rounded = int(round(x)) if abs(x - round(x)) < 0.05 else round(x, 1)
    return f"{rounded}%"


def _money(value: Any) -> str:
    try:
        n = int(float(value))
        return f"₹{n:,}"
    except Exception:
        return _clean_text(value, 30)


def _date_short(value: Any) -> str:
    raw = _s(value)
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y").lstrip("0")
    except Exception:
        return _clean_text(raw, 30)


def _slug_words(value: Any) -> str:
    text = _clean_text(value, 80).replace("_", " ").replace("-", " ")
    return WS_RE.sub(" ", text).strip()


def _active_offer(merchant: dict[str, Any]) -> Optional[str]:
    for offer in merchant.get("offers") or []:
        if str(offer.get("status", "")).lower() == "active" and offer.get("title"):
            return _clean_text(offer["title"], 80)
    return None


def _catalog_offer(category: dict[str, Any], prefer: tuple[str, ...] = ()) -> Optional[str]:
    offers = category.get("offer_catalog") or []
    if prefer:
        for o in offers:
            title = _clean_text(o.get("title"), 80)
            if any(p.lower() in title.lower() for p in prefer):
                return title
    for o in offers:
        title = _clean_text(o.get("title"), 80)
        if title:
            return title
    return None


def _digest_item(category: dict[str, Any], item_id: Any) -> Optional[dict[str, Any]]:
    iid = _s(item_id)
    if not iid:
        return None
    for item in category.get("digest") or []:
        if _s(item.get("id")) == iid:
            return item
    return None


def _digest_anchor(item: Optional[dict[str, Any]]) -> str:
    if not item:
        return ""
    bits: list[str] = []
    title = _clean_text(item.get("title"), 135)
    source = _clean_text(item.get("source"), 65)
    trial_n = item.get("trial_n")
    if trial_n:
        bits.append(f"{int(trial_n):,}-participant")
    if title:
        bits.append(title)
    if source:
        bits.append(f"({source})")
    return " ".join(bits)


def _summary_fact(item: Optional[dict[str, Any]]) -> str:
    if not item:
        return ""
    summary = _clean_text(item.get("summary"), 170)
    # Keep a concise first sentence; this is verbatim context, not invented.
    if "." in summary:
        summary = summary.split(".", 1)[0].strip()
    return summary


def _body_with_cta(core: str, cta_text: str = "") -> str:
    core = WS_RE.sub(" ", URL_RE.sub("", core)).strip()
    cta_text = WS_RE.sub(" ", URL_RE.sub("", cta_text)).strip()
    suffix = f" {cta_text}" if cta_text else ""
    if len(core) + len(suffix) <= MAX_BODY_CHARS:
        return (core + suffix).strip()
    allowed = max(30, MAX_BODY_CHARS - len(suffix) - 1)
    clipped = core[:allowed].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return (clipped + "…" + suffix).strip()


def _strip_taboos(body: str, category: dict[str, Any]) -> str:
    voice = category.get("voice") or {}
    for taboo in voice.get("vocab_taboo") or []:
        taboo_s = _clean_text(taboo, 80)
        if taboo_s:
            body = re.sub(re.escape(taboo_s), "", body, flags=re.I)
    body = WS_RE.sub(" ", body).replace(" ,", ",").replace("  ", " ").strip()
    return body


def _customer_consent_scope(trigger_kind: str) -> tuple[str, ...]:
    mapping = {
        "recall_due": ("recall_reminders",),
        "appointment_tomorrow": ("appointment_reminders",),
        "wedding_package_followup": ("bridal_package_followup",),
        "trial_followup": ("kids_program_updates", "program_updates", "appointment_reminders"),
        "customer_lapsed_hard": ("winback_offers", "renewal_reminders"),
        "chronic_refill_due": ("refill_reminders",),
        "recall_alert": ("recall_alerts",),
        "promotional_offer": ("promotional_offers",),
        "match_night_special": ("match_night_specials", "promotional_offers"),
    }
    return mapping.get(trigger_kind, ())


def customer_consent_allows(customer: Optional[dict[str, Any]], trigger_kind: str) -> bool:
    if not customer:
        return False
    prefs = customer.get("preferences") or {}
    consent = customer.get("consent") or {}
    if prefs.get("reminder_opt_in") is False:
        return False
    opted_in = consent.get("opted_in_at")
    scopes = {str(x) for x in (consent.get("scope") or [])}
    if not opted_in or not scopes:
        return False
    required = _customer_consent_scope(trigger_kind)
    if not required:
        # Unknown customer trigger: do not guess permission.
        return False
    return any(s in scopes for s in required)


BASE_TRIGGER_WEIGHTS = {
    "supply_alert": 16,
    "regulation_change": 14,
    "active_planning_intent": 14,
    "renewal_due": 12,
    "perf_dip": 11,
    "recall_due": 11,
    "chronic_refill_due": 11,
    "gbp_unverified": 10,
    "review_theme_emerged": 9,
    "competitor_opened": 8,
    "customer_lapsed_hard": 8,
    "trial_followup": 8,
    "wedding_package_followup": 8,
    "ipl_match_today": 8,
    "winback_eligible": 7,
    "perf_spike": 6,
    "milestone_reached": 6,
    "research_digest": 6,
    "cde_opportunity": 5,
    "festival_upcoming": 5,
    "category_seasonal": 5,
    "seasonal_perf_dip": 5,
    "curious_ask_due": 3,
    "dormant_with_vera": 3,
}


def score_trigger(trigger: dict[str, Any], merchant: dict[str, Any], customer: Optional[dict[str, Any]] = None) -> float:
    kind = _s(trigger.get("kind"))
    urgency = trigger.get("urgency", 1)
    try:
        urgency_n = max(1, min(5, int(urgency)))
    except Exception:
        urgency_n = 1
    score = BASE_TRIGGER_WEIGHTS.get(kind, 4) + urgency_n * 2
    if kind == "renewal_due":
        try:
            if int((trigger.get("payload") or {}).get("days_remaining", 999)) <= 14:
                score += 3
        except Exception:
            pass
    if kind in {"perf_dip", "seasonal_perf_dip"}:
        delta = (trigger.get("payload") or {}).get("delta_pct")
        try:
            score += min(4, abs(float(delta)) * 8)
        except Exception:
            pass
    if trigger.get("scope") == "customer" and customer:
        score += 1
    signals = " ".join(str(x) for x in merchant.get("signals") or []).lower()
    if kind == "gbp_unverified" and "unverified" in signals:
        score += 2
    if kind == "dormant_with_vera" and "dormant" in signals:
        score += 1
    return score


def _merchant_prefix(merchant: dict[str, Any], category: dict[str, Any]) -> str:
    first = _first_name(merchant)
    slug = _s(category.get("slug") or merchant.get("category_slug"))
    if slug == "dentists":
        return f"Dr. {first}" if first and first.lower() not in {"there", "dr."} else "Doctor"
    return first


def _reply_yes_stop(core: str) -> tuple[str, str]:
    return _body_with_cta(core, "Want me to turn this into the next step? Reply YES or STOP."), "binary_yes_no"


def _compose_research(category, merchant, trigger, customer):
    p = trigger.get("payload") or {}
    item = _digest_item(category, p.get("top_item_id"))
    who = _merchant_prefix(merchant, category)
    source = _clean_text((item or {}).get("source"), 70)
    title = _clean_text((item or {}).get("title"), 125)
    summary = _summary_fact(item)
    trial_n = (item or {}).get("trial_n")
    if trial_n and summary:
        core = f"{who}, {source or 'a new category digest'} reports a {int(trial_n):,}-participant study: {summary}."
    elif summary:
        core = f"{who}, {source or 'a new category digest'}: {summary}."
    else:
        core = f"{who}, new category research{f' from {source}' if source else ''}: {title or 'an update is available'}."
    body = _body_with_cta(core, "Worth a 3-line takeaway? Reply YES or STOP.")
    return body, "binary_yes_no", "research_digest_v2", [who, source or "category digest"]


def _compose_regulation(category, merchant, trigger, customer):
    p = trigger.get("payload") or {}
    item = _digest_item(category, p.get("top_item_id"))
    who = _merchant_prefix(merchant, category)
    deadline = _date_short(p.get("deadline_iso"))
    title = _clean_text((item or {}).get("title"), 135)
    action = _clean_text((item or {}).get("actionable"), 120)
    core = f"{who}, compliance heads-up: {title or 'a new regulation applies to your category'}."
    if deadline:
        core += f" Deadline: {deadline}."
    if action:
        core += f" Practical check: {action}."
    return _body_with_cta(core, "Want a 3-point checklist? Reply YES or STOP."), "binary_yes_no", "compliance_alert_v2", [who, deadline or "deadline"]


def _compose_recall(category, merchant, trigger, customer):
    p = trigger.get("payload") or {}
    cname, subject = _customer_addressee(customer)
    mname = _merchant_name(merchant)
    service = _service_label(p.get("service_due")) or "follow-up"
    due = _date_short(p.get("due_date"))
    slots = [x.get("label") for x in (p.get("available_slots") or []) if isinstance(x, dict) and x.get("label")]
    slot_text = " or ".join(_clean_text(x, 40) for x in slots[:2])
    pref = _language_pref(customer, merchant)
    if "hi" in pref:
        core = f"Hi {cname}, {mname} se reminder: your {service} is due{f' around {due}' if due else ''}."
        cta = f"{slot_text} mein se koi slot works? Reply 1/2, or STOP." if slot_text else "Book karna ho to YES reply karein, or STOP."
    else:
        core = f"Hi {cname}, {mname} here — your {service} is due{f' around {due}' if due else ''}."
        cta = f"Would {slot_text} work? Reply 1/2, or STOP." if slot_text else "Want to book it? Reply YES or STOP."
    return _body_with_cta(core, cta), "multi_choice_slot" if slot_text else "binary_yes_no", "customer_recall_v2", [cname, mname, slot_text or due]


def _compose_perf_dip(category, merchant, trigger, customer, seasonal: bool = False):
    p = trigger.get("payload") or {}
    who = _merchant_prefix(merchant, category)
    metric = _slug_words(p.get("metric")) or "performance"
    verb = "are" if metric in {"calls", "views", "directions", "leads"} else "is"
    delta = _pct(p.get("delta_pct"))
    window = _clean_text(p.get("window"), 20)
    locality = _locality(merchant)
    core = f"{who}, your {metric} {verb} down {delta or 'versus baseline'}{f' over {window}' if window else ''}."
    if p.get("vs_baseline") is not None:
        core += f" Baseline: {_clean_text(p.get('vs_baseline'), 20)} {metric}."
    if seasonal:
        seasonal_item = next((d for d in category.get("digest") or [] if d.get("kind") == "seasonal"), None)
        if seasonal_item:
            action = _clean_text(seasonal_item.get("actionable"), 110)
            core += f" Category context calls this a seasonal window{f' — {action}' if action else ''}."
        elif p.get("season_note"):
            core += f" Context flags it as seasonal: {_slug_words(p.get('season_note'))}."
    else:
        peer = category.get("peer_stats") or {}
        peer_metric_key = {"calls": "avg_calls_30d", "views": "avg_views_30d", "ctr": "avg_ctr"}.get(metric)
        if peer_metric_key and peer.get(peer_metric_key) is not None:
            val = peer[peer_metric_key]
            peer_txt = _pct(val, False) if metric == "ctr" else _clean_text(val, 20)
            core += f" Category benchmark: {peer_txt}."
        if locality:
            core += f" I’d diagnose the {locality} listing first."
    cta = "Want 2 retention moves from your current context? Reply YES or STOP." if seasonal else "Want the 2 most likely fixes from your current profile? Reply YES or STOP."
    return _body_with_cta(core, cta), "binary_yes_no", "performance_dip_v2", [who, metric, delta]


def _compose_renewal(category, merchant, trigger, customer):
    p = trigger.get("payload") or {}
    who = _merchant_prefix(merchant, category)
    days = _clean_text(p.get("days_remaining"), 10)
    plan = _clean_text(p.get("plan"), 30)
    amount = _money(p.get("renewal_amount"))
    core = f"{who}, your {plan or 'subscription'} has {days or 'a few'} days left."
    if amount:
        core += f" Renewal shown in your context: {amount}."
    return _body_with_cta(core, "Want to continue the same plan? Reply YES or STOP."), "binary_confirm_cancel", "renewal_due_v2", [who, days, amount]


def _compose_festival(category, merchant, trigger, customer):
    p = trigger.get("payload") or {}
    who = _merchant_prefix(merchant, category)
    fest = _clean_text(p.get("festival"), 40) or "festival"
    date = _date_short(p.get("date"))
    relevance = [str(x) for x in p.get("category_relevance") or []]
    slug = _s(category.get("slug") or merchant.get("category_slug"))
    offer = _active_offer(merchant)
    core = f"{who}, {fest}{f' is on {date}' if date else ''}."
    if slug in relevance:
        core += f" Your {slug} category is marked relevant."
    if offer:
        core += f" You already have “{offer}” active, so I’d build around that instead of inventing a new discount."
    return _body_with_cta(core, "Want one festival-ready WhatsApp line? Reply YES or STOP."), "binary_yes_no", "festival_v2", [who, fest, offer or slug]


def _compose_wedding(category, merchant, trigger, customer):
    p = trigger.get("payload") or {}
    cname, subject = _customer_addressee(customer)
    mname = _merchant_name(merchant)
    date = _date_short(p.get("wedding_date"))
    trial = _date_short(p.get("trial_completed"))
    window = _program_label(p.get("next_step_window_open"))
    core = f"Hi {cname}, {mname} here — following up after your bridal trial{f' on {trial}' if trial else ''}."
    if date:
        core += f" Your wedding date on file is {date}."
    if window:
        core += f" The next-step window is {window}."
    return _body_with_cta(core, "Want us to plan the next appointment? Reply YES or STOP."), "binary_yes_no", "bridal_followup_v2", [cname, date, window]


def _compose_curious(category, merchant, trigger, customer):
    who = _merchant_prefix(merchant, category)
    perf = merchant.get("performance") or {}
    trend = None
    for x in category.get("trend_signals") or []:
        if x.get("query"):
            trend = x
            break
    core = f"{who}, quick operator question"
    if trend:
        q = _clean_text(trend.get("query"), 60)
        delta = _pct(trend.get("delta_yoy"))
        core += f": searches for “{q}” are {delta} YoY in your category."
    else:
        core += ": which service is getting the most demand this week?"
    if perf.get("calls") is not None:
        core += f" Your 30-day calls: {perf.get('calls')}."
    return _body_with_cta(core, "What are you seeing on the ground?"), "open_ended", "curious_ask_v2", [who]


def _compose_winback(category, merchant, trigger, customer):
    p = trigger.get("payload") or {}
    who = _merchant_prefix(merchant, category)
    days = _clean_text(p.get("days_since_expiry"), 12)
    dip = _pct(p.get("perf_dip_pct"))
    lapsed = _clean_text(p.get("lapsed_customers_added_since_expiry"), 20)
    core = f"{who}, since expiry {days + ' days ago' if days else ''}, your context shows performance down {dip or 'from baseline'}"
    if lapsed:
        core += f" and {lapsed} more lapsed customers."
    else:
        core += "."
    return _body_with_cta(core, "Want a win-back plan using only your existing customer base? Reply YES or STOP."), "binary_yes_no", "merchant_winback_v2", [who, dip, lapsed]


def _compose_ipl(category, merchant, trigger, customer):
    p = trigger.get("payload") or {}
    who = _merchant_prefix(merchant, category)
    match = _clean_text(p.get("match"), 50)
    venue = _clean_text(p.get("venue"), 70)
    match_time = _s(p.get("match_time_iso"))
    time_txt = ""
    if match_time:
        try:
            time_txt = datetime.fromisoformat(match_time.replace("Z", "+00:00")).strftime("%I:%M %p").lstrip("0")
        except Exception:
            pass
    active = _active_offer(merchant)
    digest = next((d for d in category.get("digest") or [] if d.get("id") == "d_2026W17_ipl_window"), None)
    summary = _clean_text((digest or {}).get("summary"), 180)
    pct_match = re.search(r"covers down\s*(\d+%)", summary, flags=re.I)
    shift_fact = f"Category data says Saturday IPL covers are {pct_match.group(1)} below Saturday average as orders shift home." if pct_match else "Category data says weekend IPL can shift orders toward home-watch parties."
    core = f"{who}, {match or 'IPL match'} is {f'at {time_txt}' if time_txt else 'today'}{f' at {venue}' if venue else ''}. {shift_fact}"
    if active:
        core += f" You already have “{active}” active."
    return _body_with_cta(core, "Want a match-night line around it? Reply YES or STOP."), "binary_yes_no", "ipl_match_v2", [who, match, active or ""]


def _compose_review_theme(category, merchant, trigger, customer):
    p = trigger.get("payload") or {}
    who = _merchant_prefix(merchant, category)
    theme = _slug_words(p.get("theme"))
    count = _clean_text(p.get("occurrences_30d"), 10)
    trend = _clean_text(p.get("trend"), 20)
    quote = _clean_text(p.get("common_quote"), 70)
    core = f"{who}, {count or 'multiple'} recent reviews mention {theme or 'the same issue'}"
    if trend:
        core += f" and the theme is {trend}."
    else:
        core += "."
    if quote:
        core += f" One recurring phrase: “{quote}”."
    return _body_with_cta(core, "Want a reply template plus one operational fix? Reply YES or STOP."), "binary_yes_no", "review_theme_v2", [who, theme, count]


def _compose_milestone(category, merchant, trigger, customer):
    p = trigger.get("payload") or {}
    who = _merchant_prefix(merchant, category)
    metric_raw = _s(p.get("metric"))
    metric = "reviews" if metric_raw == "review_count" else (_slug_words(metric_raw) or "milestone")
    now = p.get("value_now")
    target = p.get("milestone_value")
    imminent = bool(p.get("is_imminent"))
    if imminent and isinstance(now, (int, float)) and isinstance(target, (int, float)) and now < target:
        gap = target - now
        core = f"{who}, you’re {int(gap)} {metric} away from {int(target)} — current count is {int(now)}."
    else:
        core = f"{who}, your {metric} is now {_clean_text(now, 20)}."
    return _body_with_cta(core, "Want a thank-you/review nudge for the final stretch? Reply YES or STOP."), "binary_yes_no", "milestone_v2", [who, _clean_text(now,20), _clean_text(target,20)]


def _compose_active_planning(category, merchant, trigger, customer):
    p = trigger.get("payload") or {}
    who = _merchant_prefix(merchant, category)
    topic = _slug_words(p.get("intent_topic")) or "the plan"
    topic_tokens = [x for x in re.findall(r"[a-z]+", topic.lower()) if len(x) > 3 and x not in {"program", "package", "drafting"}]
    offers = category.get("offer_catalog") or []
    offer = None
    best = 0
    for o in offers:
        title = _clean_text(o.get("title"), 80)
        score = sum(1 for tok in topic_tokens if tok in title.lower())
        if score > best:
            best, offer = score, title
    core = f"{who}, you’ve already given a clear planning intent for {topic}."
    if offer:
        core += f" Your category catalog has “{offer}” as a concrete price/style anchor."
    core += " I’ll move straight to a first draft instead of asking another qualification question."
    return _body_with_cta(core, "Reply YES to proceed or STOP."), "binary_yes_no", "planning_intent_v2", [who, topic, offer or ""]


def _compose_customer_lapsed(category, merchant, trigger, customer):
    p = trigger.get("payload") or {}
    cname = _customer_name(customer)
    mname = _merchant_name(merchant)
    days = _clean_text(p.get("days_since_last_visit"), 10)
    focus = _slug_words(p.get("previous_focus"))
    months = _clean_text(p.get("previous_membership_months"), 10)
    core = f"Hi {cname}, {mname} here — it’s been {days or 'a while'} days since your last visit."
    if focus:
        core += f" Your previous focus was {focus}"
        if months:
            core += f" across {months} months"
        core += "."
    return _body_with_cta(core, "Want to restart with a simple first session? Reply YES or STOP."), "binary_yes_no", "customer_winback_v2", [cname, days, focus]


def _compose_trial_followup(category, merchant, trigger, customer):
    p = trigger.get("payload") or {}
    cname, subject = _customer_addressee(customer)
    mname = _merchant_name(merchant)
    trial = _date_short(p.get("trial_date"))
    opts = [x.get("label") for x in (p.get("next_session_options") or []) if isinstance(x, dict) and x.get("label")]
    option = _clean_text(opts[0], 45) if opts else ""
    possessive = f"{subject}'s" if subject != cname else "your"
    core = f"Hi {cname}, {mname} here — following up after {possessive} trial{f' on {trial}' if trial else ''}."
    cta = f"Next session available: {option}. Want it? Reply YES or STOP." if option else "Want the next session option? Reply YES or STOP."
    return _body_with_cta(core, cta), "binary_yes_no", "trial_followup_v2", [cname, trial, option]


def _compose_supply_alert(category, merchant, trigger, customer):
    p = trigger.get("payload") or {}
    who = _merchant_prefix(merchant, category)
    molecule = _clean_text(p.get("molecule"), 50)
    mfr = _clean_text(p.get("manufacturer"), 50)
    batches = [_clean_text(x, 30) for x in (p.get("affected_batches") or [])][:3]
    core = f"{who}, urgent stock alert: {molecule or 'a medicine'}"
    if mfr:
        core += f" from {mfr}"
    if batches:
        core += f" — affected batches: {', '.join(batches)}."
    else:
        core += "."
    return _body_with_cta(core, "Please check shelf stock now. Want a customer-notification draft only for affected buyers? Reply YES or STOP."), "binary_yes_no", "supply_alert_v2", [who, molecule, ", ".join(batches)]


def _compose_refill(category, merchant, trigger, customer):
    p = trigger.get("payload") or {}
    cname = _customer_name(customer)
    mname = _merchant_name(merchant)
    meds = ", ".join(_clean_text(x, 35) for x in (p.get("molecule_list") or [])[:4])
    runs = _date_short(p.get("stock_runs_out_iso"))
    delivery = bool(p.get("delivery_address_saved"))
    core = f"Hi {cname}, {mname} here — your refill reminder covers {meds or 'your regular medicines'}"
    if runs:
        core += f"; the stock-run-out date on file is {runs}."
    else:
        core += "."
    if delivery:
        core += " Your delivery address is saved."
    return _body_with_cta(core, "Want us to prepare the refill request? Reply YES or STOP."), "binary_yes_no", "refill_reminder_v2", [cname, meds, runs]


def _compose_category_seasonal(category, merchant, trigger, customer):
    p = trigger.get("payload") or {}
    who = _merchant_prefix(merchant, category)
    season = _slug_words(p.get("season"))
    trends = [_trend_label(x) for x in (p.get("trends") or [])][:4]
    core = f"{who}, {season or 'seasonal'} demand shift in your context: {', '.join(trends)}."
    if p.get("shelf_action_recommended"):
        core += " Shelf action is flagged as recommended."
    return _body_with_cta(core, "Want a priority list for what to move up/down? Reply YES or STOP."), "binary_yes_no", "seasonal_shift_v2", [who, season, ", ".join(trends)]


def _compose_gbp(category, merchant, trigger, customer):
    p = trigger.get("payload") or {}
    who = _merchant_prefix(merchant, category)
    path = _slug_words(p.get("verification_path"))
    uplift = _pct(p.get("estimated_uplift_pct"))
    core = f"{who}, your Google Business Profile is unverified."
    if path:
        core += f" Context lists the verification path as {path}."
    if uplift:
        core += f" The supplied estimate is {uplift} uplift after verification."
    return _body_with_cta(core, "Want the shortest verification checklist? Reply YES or STOP."), "binary_yes_no", "gbp_verification_v2", [who, path, uplift]


def _compose_cde(category, merchant, trigger, customer):
    p = trigger.get("payload") or {}
    who = _merchant_prefix(merchant, category)
    item = _digest_item(category, p.get("digest_item_id"))
    title = _clean_text((item or {}).get("title"), 125)
    date = _date_short((item or {}).get("date"))
    credits = _clean_text(p.get("credits") or (item or {}).get("credits"), 10)
    fee = _slug_words(p.get("fee"))
    core = f"{who}, CDE opportunity: {title or 'new category session'}"
    if date:
        core += f" on {date}"
    if credits:
        core += f", {credits} credits"
    if fee:
        core += f", {fee}"
    core += "."
    return _body_with_cta(core, "Want the key details in one message? Reply YES or STOP."), "binary_yes_no", "cde_opportunity_v2", [who, title, credits]


def _compose_competitor(category, merchant, trigger, customer):
    p = trigger.get("payload") or {}
    who = _merchant_prefix(merchant, category)
    name = _clean_text(p.get("competitor_name"), 60)
    dist = _clean_text(p.get("distance_km"), 15)
    offer = _clean_text(p.get("their_offer"), 75)
    opened = _date_short(p.get("opened_date"))
    own = _active_offer(merchant)
    core = f"{who}, a new competitor{f' — {name}' if name else ''} opened{f' {dist} km away' if dist else ''}{f' on {opened}' if opened else ''}."
    if offer:
        core += f" Their listed offer: “{offer}”."
    if own:
        core += f" Yours is “{own}”."
    return _body_with_cta(core, "Want a positioning line that competes without price-matching? Reply YES or STOP."), "binary_yes_no", "competitor_opened_v2", [who, name, offer]


def _compose_perf_spike(category, merchant, trigger, customer):
    p = trigger.get("payload") or {}
    who = _merchant_prefix(merchant, category)
    metric = _slug_words(p.get("metric")) or "performance"
    verb = "are" if metric in {"calls", "views", "directions", "leads"} else "is"
    delta = _pct(p.get("delta_pct"))
    base = _clean_text(p.get("vs_baseline"), 15)
    driver = _slug_words(p.get("likely_driver"))
    core = f"{who}, your {metric} {verb} up {delta or 'from baseline'}."
    if base:
        core += f" Baseline: {base} {metric}."
    if driver:
        core += f" Context flags {driver} as the likely driver."
    return _body_with_cta(core, "Want one repeatable follow-up to keep the lift going? Reply YES or STOP."), "binary_yes_no", "performance_spike_v2", [who, metric, delta]


def _compose_dormant(category, merchant, trigger, customer):
    p = trigger.get("payload") or {}
    who = _merchant_prefix(merchant, category)
    days = _clean_text(p.get("days_since_last_merchant_message"), 12)
    last_topic = _slug_words(p.get("last_topic"))
    core = f"{who}, it’s been {days or 'a while'} days since our last chat"
    if last_topic:
        core += f"; the last topic was {last_topic}"
    core += "."
    # Add one merchant-specific fact so dormancy is not a generic ping.
    perf = merchant.get("performance") or {}
    if perf.get("views") is not None:
        core += f" Your current 30-day views are {perf.get('views')}."
    return _body_with_cta(core, "Want one useful update instead of a generic check-in? Reply YES or STOP."), "binary_yes_no", "dormancy_v2", [who, days, last_topic]


def _compose_generic(category, merchant, trigger, customer):
    p = trigger.get("payload") or {}
    kind = _slug_words(trigger.get("kind")) or "update"
    if trigger.get("scope") == "customer":
        cname = _customer_name(customer)
        mname = _merchant_name(merchant)
        core = f"Hi {cname}, {mname} here — a {kind} is due."
        # Safe generic facts: scalars only, no internal IDs.
        facts = []
        for k, v in p.items():
            if k.endswith("_id") or k in {"merchant_id", "customer_id"}:
                continue
            if isinstance(v, (str, int, float, bool)):
                val = _clean_text(v, 50)
                if val:
                    facts.append(f"{_slug_words(k)}: {val}")
            if len(facts) >= 2:
                break
        if facts:
            core += " " + "; ".join(facts) + "."
        return _body_with_cta(core, "Reply YES if you want the next step, or STOP."), "binary_yes_no", "customer_generic_v2", [cname, kind]

    who = _merchant_prefix(merchant, category)
    locality = _locality(merchant)
    facts = []
    for k, v in p.items():
        if k.endswith("_id") or k in {"category", "merchant_id", "customer_id"}:
            continue
        if isinstance(v, (str, int, float, bool)):
            val = _clean_text(v, 55)
            if val:
                facts.append(f"{_slug_words(k)}: {val}")
        if len(facts) >= 3:
            break
    core = f"{who}, quick {kind}"
    if locality:
        core += f" for {locality}"
    core += ": " + ("; ".join(facts) if facts else "new context just came in") + "."
    return _body_with_cta(core, "Want the most practical next step? Reply YES or STOP."), "binary_yes_no", "merchant_generic_v2", [who, kind]


HANDLERS = {
    "research_digest": _compose_research,
    "regulation_change": _compose_regulation,
    "recall_due": _compose_recall,
    "renewal_due": _compose_renewal,
    "festival_upcoming": _compose_festival,
    "wedding_package_followup": _compose_wedding,
    "curious_ask_due": _compose_curious,
    "winback_eligible": _compose_winback,
    "ipl_match_today": _compose_ipl,
    "review_theme_emerged": _compose_review_theme,
    "milestone_reached": _compose_milestone,
    "active_planning_intent": _compose_active_planning,
    "customer_lapsed_hard": _compose_customer_lapsed,
    "trial_followup": _compose_trial_followup,
    "supply_alert": _compose_supply_alert,
    "chronic_refill_due": _compose_refill,
    "category_seasonal": _compose_category_seasonal,
    "gbp_unverified": _compose_gbp,
    "cde_opportunity": _compose_cde,
    "competitor_opened": _compose_competitor,
    "perf_spike": _compose_perf_spike,
    "dormant_with_vera": _compose_dormant,
}


def compose_message(category: dict[str, Any], merchant: dict[str, Any], trigger: dict[str, Any], customer: Optional[dict[str, Any]] = None) -> Optional[dict[str, Any]]:
    """Compose a grounded first outbound message. Returns None when consent blocks customer outreach."""
    kind = _s(trigger.get("kind"))
    scope = _s(trigger.get("scope")) or ("customer" if trigger.get("customer_id") else "merchant")
    if scope == "customer":
        if not customer_consent_allows(customer, kind):
            return None
        send_as = "merchant_on_behalf"
    else:
        send_as = "vera"

    if kind == "perf_dip":
        body, cta, template, params = _compose_perf_dip(category, merchant, trigger, customer, False)
    elif kind == "seasonal_perf_dip":
        body, cta, template, params = _compose_perf_dip(category, merchant, trigger, customer, True)
    else:
        handler = HANDLERS.get(kind, _compose_generic)
        body, cta, template, params = handler(category, merchant, trigger, customer)

    body = _strip_taboos(body, category)
    body = _body_with_cta(body)  # final length/URL normalization
    if not body:
        return None

    locality = _locality(merchant)
    rationale_bits = [f"trigger={kind or 'unknown'}", f"category={category.get('slug') or merchant.get('category_slug') or 'unknown'}"]
    if locality:
        rationale_bits.append(f"merchant_locality={locality}")
    if scope == "customer":
        rationale_bits.append("customer_consent=matched")
    rationale_bits.append("grounding=payload+stored_context_only")

    result = ComposeResult(
        body=body,
        cta=cta,
        send_as=send_as,
        suppression_key=_clean_text(trigger.get("suppression_key"), 160),
        rationale="; ".join(rationale_bits),
        template_name=template,
        template_params=[_clean_text(x, 100) for x in params if _clean_text(x, 100)],
    )
    return result.as_dict()
