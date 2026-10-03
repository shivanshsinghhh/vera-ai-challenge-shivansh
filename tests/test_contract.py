from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def setup_function():
    client.post("/v1/teardown", json={})


def push(scope, cid, payload, version=1):
    return client.post("/v1/context", json={
        "scope": scope,
        "context_id": cid,
        "version": version,
        "payload": payload,
        "delivered_at": "2026-04-26T10:00:00Z",
    })


def fixtures():
    cat = {
        "slug": "dentists",
        "voice": {"vocab_taboo": ["guaranteed"]},
        "peer_stats": {"avg_calls_30d": 12, "avg_ctr": 0.03},
        "offer_catalog": [{"title": "Dental Cleaning @ ₹299"}],
        "digest": [{
            "id": "d1", "title": "3-month fluoride recall outperforms 6-month",
            "source": "JIDA Oct 2026, p.14", "trial_n": 2100,
            "summary": "Multi-center trial shows 38% lower recurrence in high-risk adults.",
        }],
    }
    merchant = {
        "merchant_id": "m1", "category_slug": "dentists",
        "identity": {"name": "Dr. Meera's Dental Clinic", "owner_first_name": "Meera", "locality": "Lajpat Nagar", "languages": ["en", "hi"]},
        "performance": {"calls": 18},
        "offers": [{"title": "Dental Cleaning @ ₹299", "status": "active"}],
        "signals": ["high_risk_adult_cohort"],
    }
    customer = {
        "customer_id": "c1", "merchant_id": "m1",
        "identity": {"name": "Priya", "language_pref": "hi-en mix"},
        "preferences": {"reminder_opt_in": True},
        "consent": {"opted_in_at": "2025-11-04", "scope": ["recall_reminders"]},
    }
    return cat, merchant, customer


def test_health_and_metadata():
    assert client.get("/v1/healthz").status_code == 200
    md = client.get("/v1/metadata").json()
    assert md["team_name"]
    assert md["model"]


def test_context_idempotency_and_conflict():
    cat, _, _ = fixtures()
    assert push("category", "dentists", cat, 3).status_code == 200
    same = push("category", "dentists", cat, 3)
    assert same.status_code == 200 and same.json().get("duplicate") is True
    stale = push("category", "dentists", cat, 2)
    assert stale.status_code == 409
    fresh = push("category", "dentists", cat, 4)
    assert fresh.status_code == 200 and fresh.json()["accepted"] is True


def test_invalid_scope_400():
    r = push("wrong", "x", {}, 1)
    assert r.status_code == 400


def test_tick_suppression_and_grounding():
    cat, merchant, _ = fixtures()
    push("category", "dentists", cat)
    push("merchant", "m1", merchant)
    trg = {
        "id": "t1", "scope": "merchant", "kind": "research_digest", "source": "external",
        "merchant_id": "m1", "customer_id": None,
        "payload": {"top_item_id": "d1"}, "urgency": 2,
        "suppression_key": "research:d1", "expires_at": "2026-05-03T00:00:00Z",
    }
    push("trigger", "t1", trg)
    first = client.post("/v1/tick", json={"now": "2026-04-26T10:30:00Z", "available_triggers": ["t1"]}).json()["actions"]
    assert len(first) == 1
    assert "2,100" in first[0]["body"]
    assert "JIDA" in first[0]["body"]
    assert len(first[0]["body"]) <= 300
    second = client.post("/v1/tick", json={"now": "2026-04-26T10:35:00Z", "available_triggers": ["t1"]}).json()["actions"]
    assert second == []


def test_customer_consent_and_correct_addressee():
    cat, merchant, customer = fixtures()
    push("category", "dentists", cat)
    push("merchant", "m1", merchant)
    push("customer", "c1", customer)
    trg = {
        "id": "t2", "scope": "customer", "kind": "recall_due", "source": "internal",
        "merchant_id": "m1", "customer_id": "c1",
        "payload": {"service_due": "6_month_cleaning", "due_date": "2026-11-12", "available_slots": [{"label": "Wed 5 Nov, 6pm"}]},
        "urgency": 3, "suppression_key": "recall:c1", "expires_at": "2026-11-30T00:00:00Z",
    }
    push("trigger", "t2", trg)
    actions = client.post("/v1/tick", json={"now": "2026-11-01T10:00:00Z", "available_triggers": ["t2"]}).json()["actions"]
    assert len(actions) == 1
    assert actions[0]["send_as"] == "merchant_on_behalf"
    assert actions[0]["body"].startswith("Hi Priya")


def test_customer_without_consent_is_silent():
    cat, merchant, customer = fixtures()
    customer["consent"] = {"opted_in_at": None, "scope": []}
    customer["preferences"]["reminder_opt_in"] = False
    push("category", "dentists", cat)
    push("merchant", "m1", merchant)
    push("customer", "c1", customer)
    trg = {
        "id": "t3", "scope": "customer", "kind": "recall_due", "source": "internal",
        "merchant_id": "m1", "customer_id": "c1", "payload": {}, "urgency": 3,
        "suppression_key": "recall:no-consent", "expires_at": "2026-11-30T00:00:00Z",
    }
    push("trigger", "t3", trg)
    actions = client.post("/v1/tick", json={"now": "2026-11-01T10:00:00Z", "available_triggers": ["t3"]}).json()["actions"]
    assert actions == []


def test_replay_auto_reply_and_intent_transition():
    # Unknown conversation still handles replay edge cases safely.
    r1 = client.post("/v1/reply", json={"conversation_id":"auto1","merchant_id":"m1","from_role":"merchant","message":"Thank you for contacting us. We will respond shortly.","received_at":"2026-04-26T10:00:00Z","turn_number":2}).json()
    assert r1["action"] == "send"
    r2 = client.post("/v1/reply", json={"conversation_id":"auto1","merchant_id":"m1","from_role":"merchant","message":"Thank you for contacting us. We will respond shortly.","received_at":"2026-04-26T10:01:00Z","turn_number":3}).json()
    assert r2["action"] == "end"

    yes = client.post("/v1/reply", json={"conversation_id":"commit1","merchant_id":"m1","from_role":"merchant","message":"Yes let's do it","received_at":"2026-04-26T10:00:00Z","turn_number":2}).json()
    assert yes["action"] == "send"
    assert all(x not in yes["body"].lower() for x in ["would you", "do you want", "shall we"])


def test_teardown():
    cat, _, _ = fixtures()
    push("category", "dentists", cat)
    assert client.get("/v1/healthz").json()["contexts_loaded"]["category"] == 1
    assert client.post("/v1/teardown", json={}).json()["status"] == "wiped"
    assert client.get("/v1/healthz").json()["contexts_loaded"]["category"] == 0
