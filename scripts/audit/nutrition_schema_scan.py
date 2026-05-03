#!/usr/bin/env python3
"""
Audit nutrition_log.items schema fragmentation.

Connects to production PostgreSQL via SSH + docker exec, scans every row,
classifies its items[] schema, and reports:
  - How many rows use each schema
  - Which fields actually appear (and how often)
  - Counts of null weights, inconsistent totals, etc.
  - Date ranges per schema (to see migration over time)

Read-only. No writes to DB.
"""

import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date
from typing import Any

# ── server connection ───────────────────────────────────────────────────────
SERVER = "root@116.203.213.137"
PASSWORD = "SERVER_PASSWORD_REDACTED"
SSHPASS = "/opt/homebrew/bin/sshpass"
PSQL = "docker exec healthvault_postgres psql -U healthvault -d healthvault -t -A -c"


def run_sql(sql: str) -> str:
    """Run SQL on prod, return stdout."""
    cmd = [SSHPASS, "-p", PASSWORD, "ssh", "-o", "StrictHostKeyChecking=no", SERVER, f'{PSQL} "{sql}"']
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        sys.exit(f"SQL failed: {res.stderr}")
    return res.stdout


def fetch_rows() -> list[dict[str, Any]]:
    """Fetch nutrition_log rows for user 895655 + 485132."""
    sql = (
        "SELECT json_agg(t) FROM ("
        "  SELECT id, user_id, date::text, meal_time::text, meal_name, items, totals "
        "  FROM nutrition_log "
        "  WHERE user_id IN (895655, 485132) "
        "  ORDER BY date, meal_time"
        ") t"
    )
    raw = run_sql(sql).strip()
    if not raw or raw == "":
        return []
    return json.loads(raw)


# ── classification ──────────────────────────────────────────────────────────
# Canonical fields we expect going forward
CANONICAL_FIELDS = {"product", "weight_g", "calories", "protein", "fats", "carbs"}

# Legacy/alternative fields we've seen
LEGACY_MARKERS = {
    "name": "legacy_name",  # old schema uses 'name' not 'product'
    "amount": "legacy_amount",  # old schema uses 'amount' not 'weight_g'
    "weight": "intermediate_weight",  # intermediate schema
    "fat": "legacy_fat",  # old singular 'fat' not 'fats'
}


def classify_item(item: dict) -> str:
    """
    Classify a single item dict into a schema bucket.
    Returns a schema label like 'canonical' / 'legacy' / 'mixed'.
    """
    keys = set(item.keys())

    has_product = "product" in keys
    has_name = "name" in keys
    has_weight_g = "weight_g" in keys
    has_amount = "amount" in keys
    has_weight = "weight" in keys
    has_fats = "fats" in keys
    has_fat = "fat" in keys

    # Pure canonical: product + weight_g + fats
    if has_product and has_weight_g and has_fats and not has_name and not has_amount and not has_fat:
        return "canonical"

    # Pure legacy old: name + amount + fat (no s)
    if has_name and has_amount and has_fat and not has_product and not has_weight_g:
        return "legacy_old"

    # Intermediate: name + weight (not weight_g, not amount) + fats
    if has_name and has_weight and has_fats and not has_product and not has_amount:
        return "intermediate"

    # Mixed: canonical fields + legacy fields present together
    canonical_keys = {"product", "weight_g", "fats"} & keys
    legacy_keys = {"name", "amount", "fat", "weight"} & keys
    if canonical_keys and legacy_keys:
        return "mixed"

    # No name at all
    if not has_product and not has_name:
        return "no_name_field"

    return "other"


def null_weight_flag(item: dict) -> bool:
    """Does this item have null/zero weight but non-zero calories?"""
    w = item.get("weight_g") or item.get("amount") or item.get("weight")
    cal = item.get("calories") or 0
    return (w is None or w == 0) and cal > 0


# ── report ──────────────────────────────────────────────────────────────────


def main():
    print("Fetching nutrition_log from production…", file=sys.stderr)
    rows = fetch_rows()
    print(f"Fetched {len(rows)} rows.\n", file=sys.stderr)

    if not rows:
        sys.exit("No rows returned.")

    # row-level counters
    per_row_schema: Counter = Counter()
    per_user: Counter = Counter()
    date_range_per_schema: defaultdict = defaultdict(lambda: [None, None])

    # item-level counters (one row has multiple items)
    per_item_schema: Counter = Counter()
    field_freq: Counter = Counter()
    null_weights = 0
    total_items = 0
    examples: dict[str, dict] = {}

    # row-level: when ALL items in a row share one schema, count that; otherwise "mixed_row"
    for row in rows:
        items = row.get("items") or []
        if not isinstance(items, list) or not items:
            per_row_schema["empty_items"] += 1
            continue

        row_classes = set()
        for it in items:
            if not isinstance(it, dict):
                per_item_schema["non_dict"] += 1
                continue
            total_items += 1
            cls = classify_item(it)
            per_item_schema[cls] += 1
            row_classes.add(cls)
            for k in it.keys():
                field_freq[k] += 1
            if null_weight_flag(it):
                null_weights += 1
            if cls not in examples:
                examples[cls] = {"row_id": row["id"], "date": row["date"], "user_id": row["user_id"], "item": it}

        row_schema = next(iter(row_classes)) if len(row_classes) == 1 else "mixed_row"
        per_row_schema[row_schema] += 1
        per_user[(row["user_id"], row_schema)] += 1

        # track date ranges
        d = row["date"]
        rs = row_schema
        lo, hi = date_range_per_schema[rs]
        if lo is None or d < lo:
            date_range_per_schema[rs][0] = d
        if hi is None or d > hi:
            date_range_per_schema[rs][1] = d

    # ── print report ─────────────────────────────────────────────────────────
    print("=" * 70)
    print("NUTRITION_LOG SCHEMA AUDIT")
    print("=" * 70)

    print(f"\nTotal rows:  {len(rows)}")
    print(f"Total items: {total_items}")

    print("\n── Row-level schema (all items in row share schema) ──")
    for s, c in per_row_schema.most_common():
        lo, hi = date_range_per_schema.get(s, [None, None])
        dates = f"{lo} → {hi}" if lo else "—"
        print(f"  {s:<20s} {c:>5d} rows   ({dates})")

    print("\n── Item-level schema ──")
    for s, c in per_item_schema.most_common():
        pct = 100 * c / total_items if total_items else 0
        print(f"  {s:<20s} {c:>5d} items   ({pct:5.1f}%)")

    print("\n── Field frequency across all items ──")
    for f, c in field_freq.most_common():
        pct = 100 * c / total_items if total_items else 0
        mark = " ✓" if f in CANONICAL_FIELDS else "  "
        print(f"  {f:<20s} {c:>5d}   ({pct:5.1f}%){mark}")

    print("\n── Null-weight items with calories > 0 ──")
    print(f"  {null_weights} items (target for Pass 2 #2 backfill)")

    print("\n── Per-user breakdown ──")
    by_user: defaultdict = defaultdict(Counter)
    for (uid, rs), c in per_user.items():
        by_user[uid][rs] = c
    for uid, schemas in by_user.items():
        total = sum(schemas.values())
        print(f"  user_id={uid}: {total} rows")
        for s, c in schemas.most_common():
            print(f"      {s:<20s} {c:>5d}")

    print("\n── Example row per schema ──")
    for s, ex in examples.items():
        print(f"\n  [{s}]  row_id={ex['row_id']}  date={ex['date']}  user={ex['user_id']}")
        item_preview = json.dumps(ex["item"], ensure_ascii=False, indent=2)
        for line in item_preview.split("\n"):
            print(f"    {line}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
