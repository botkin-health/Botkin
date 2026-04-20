#!/usr/bin/env python3
"""One-time migration: backfill fiber field on every nutrition_log item in DB.

Idempotent — existing fiber > 0 is preserved.
Updates `items` and `totals` JSONB columns.

Usage:
    # On the server (where DB is reachable):
    docker exec -i healthvault_bot python3 /app/scripts/backfill_fiber_all_history.py [--dry-run]

Reports:
    - rows scanned
    - items enriched (gained fiber > 0)
    - items already OK (had fiber)
    - items not matched (stayed 0)
    - unmatched names (top 20, to grow fiber_table)
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

# Bootstrap imports — works both inside container (/app) and local (project root).
HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "telegram-bot"))

from sqlalchemy.orm.attributes import flag_modified  # noqa: E402

from database import SessionLocal  # noqa: E402
from database.models import NutritionLog  # noqa: E402
from core.food.fiber_table import (  # noqa: E402
    enrich_items_with_fiber,
    _item_name,
    _item_weight,
    estimate_fiber,
    sum_fiber,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Print changes, don't commit")
    ap.add_argument("--user-id", type=int, default=None, help="Limit to specific user_id")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        q = db.query(NutritionLog)
        if args.user_id:
            q = q.filter(NutritionLog.user_id == args.user_id)
        rows = q.order_by(NutritionLog.date, NutritionLog.meal_time).all()

        rows_scanned = 0
        rows_changed = 0
        items_enriched = 0
        items_already_ok = 0
        items_stayed_zero = 0
        unmatched: Counter[str] = Counter()

        for r in rows:
            rows_scanned += 1
            if not r.items:
                continue

            before_fiber_per_item = [float(it.get("fiber") or 0) for it in r.items]
            enrich_items_with_fiber(r.items)  # mutates in place
            after_fiber_per_item = [float(it.get("fiber") or 0) for it in r.items]

            row_changed = False
            for it, before, after in zip(r.items, before_fiber_per_item, after_fiber_per_item):
                if before > 0:
                    items_already_ok += 1
                elif after > 0:
                    items_enriched += 1
                    row_changed = True
                else:
                    items_stayed_zero += 1
                    name = _item_name(it)
                    w = _item_weight(it)
                    if name and w > 0:
                        unmatched[name[:80]] += 1

            if row_changed:
                rows_changed += 1
                # Recompute totals.fiber from enriched items
                new_totals = dict(r.totals or {})
                new_totals["fiber"] = sum_fiber(r.items)
                r.totals = new_totals
                flag_modified(r, "items")
                flag_modified(r, "totals")

        if args.dry_run:
            print("=== DRY RUN — no changes committed ===")
            db.rollback()
        else:
            db.commit()
            print("=== COMMITTED ===")

        print(f"Rows scanned:          {rows_scanned}")
        print(f"Rows changed:          {rows_changed}")
        print(f"Items enriched:        {items_enriched}")
        print(f"Items already had fib: {items_already_ok}")
        print(f"Items stayed at 0:     {items_stayed_zero}")
        print()
        print("Top 20 unmatched food names (add to fiber_table.py to improve coverage):")
        for name, cnt in unmatched.most_common(20):
            # Show what estimate_fiber returns for 100g as baseline
            est = estimate_fiber(name, 100)
            print(f"  {cnt:4d}x  [{est:5.1f}g/100g]  {name}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
