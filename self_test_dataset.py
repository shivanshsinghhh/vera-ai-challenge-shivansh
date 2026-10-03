#!/usr/bin/env python3
"""Static composer test against a supplied magicpin challenge dataset directory.

Usage:
  python self_test_dataset.py /path/to/magicpin-ai-challenge/dataset
"""
from __future__ import annotations

import json
import pathlib
import sys
from collections import Counter

from bot import compose


def load(path: pathlib.Path):
    cats = {p.stem: json.load(open(p, encoding="utf-8")) for p in (path / "categories").glob("*.json")}
    merchants_raw = json.load(open(path / "merchants_seed.json", encoding="utf-8"))
    customers_raw = json.load(open(path / "customers_seed.json", encoding="utf-8"))
    triggers_raw = json.load(open(path / "triggers_seed.json", encoding="utf-8"))
    merchants = {m["merchant_id"]: m for m in merchants_raw.get("merchants", [])}
    customers = {c["customer_id"]: c for c in customers_raw.get("customers", [])}
    triggers = triggers_raw.get("triggers", [])
    return cats, merchants, customers, triggers


def main():
    if len(sys.argv) != 2:
        print("Usage: python self_test_dataset.py /path/to/dataset")
        raise SystemExit(2)
    root = pathlib.Path(sys.argv[1])
    cats, merchants, customers, triggers = load(root)
    failures = []
    kinds = Counter()
    sent = 0
    for t in triggers:
        m = merchants.get(t.get("merchant_id"))
        if not m:
            failures.append((t.get("id"), "missing merchant")); continue
        c = customers.get(t.get("customer_id")) if t.get("customer_id") else None
        cat = cats.get(m.get("category_slug"))
        if not cat:
            failures.append((t.get("id"), "missing category")); continue
        out = compose(cat, m, t, c)
        kinds[t.get("kind")] += 1
        body = out.get("body", "")
        if t.get("scope") == "customer" and not body:
            # Consent-gated silence is valid.
            continue
        sent += 1
        if not body:
            failures.append((t.get("id"), "empty body"))
        if len(body) > 300:
            failures.append((t.get("id"), f"body too long: {len(body)}"))
        if "http://" in body or "https://" in body:
            failures.append((t.get("id"), "URL leaked"))
        if t.get("scope") == "customer" and c:
            name = str((c.get("identity") or {}).get("name") or "").split("(",1)[0].strip()
            if name and name != "(walk-in, no profile)" and name.split()[0].lower() not in body.lower():
                failures.append((t.get("id"), "customer addressee missing"))
    print(f"Trigger kinds: {len(kinds)} | triggers: {len(triggers)} | messages composed: {sent}")
    if failures:
        for f in failures:
            print("FAIL", f)
        raise SystemExit(1)
    print("PASS: all static grounding/format checks")


if __name__ == "__main__":
    main()
