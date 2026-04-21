"""One-off: normalise every nutrition_log.items dialect to canonical schema.

Canonical schema: {food, amount, unit, calories, protein, fats, carbs, fiber}
(+ optional note, drinks)

Scans all nutrition_log rows, routes every item through
helpers.db_save.normalize_item_to_canonical(), and writes back only if
the row actually changes (idempotent).

Usage:
    # Dry run (default):
    docker exec healthvault_bot python scripts/backfill/normalize_item_schemas.py

    # Apply:
    docker exec healthvault_bot python scripts/backfill/normalize_item_schemas.py --apply

    # Limit to single user:
    docker exec healthvault_bot python scripts/backfill/normalize_item_schemas.py --user 895655 --apply
"""

import argparse
import sys

from sqlalchemy.orm.attributes import flag_modified

from database import SessionLocal
from database.models import NutritionLog
from helpers.db_save import normalize_item_to_canonical


def _items_equal(a: list, b: list) -> bool:
    """Conservative equality check — differs if any canonical field differs."""
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if dict(x) != dict(y):
            return False
    return True


def main(apply: bool, user_filter: int | None) -> None:
    db = SessionLocal()
    try:
        q = db.query(NutritionLog).order_by(NutritionLog.date, NutritionLog.meal_time)
        if user_filter:
            q = q.filter(NutritionLog.user_id == user_filter)
        rows = q.all()

        scanned = 0
        changed = 0
        unchanged = 0

        for row in rows:
            scanned += 1
            old_items = list(row.items or [])
            if not old_items:
                unchanged += 1
                continue

            new_items = [normalize_item_to_canonical(dict(it)) for it in old_items]

            if _items_equal(old_items, new_items):
                unchanged += 1
                continue

            changed += 1
            first_old = dict(old_items[0])
            first_new = dict(new_items[0])
            diff_keys = sorted(set(first_old) ^ set(first_new))
            print(
                f"[{'APPLY' if apply else 'DRY '}] id={row.id} uid={row.user_id} "
                f"{row.date} {row.meal_name!r} items={len(old_items)} diff={diff_keys or 'values'}"
            )

            if apply:
                row.items = new_items
                flag_modified(row, "items")

        if apply:
            db.commit()

        print("---")
        print(f"scanned: {scanned}")
        print(f"already canonical: {unchanged}")
        print(f"normalised: {changed}")
        if not apply:
            print("\nDry run. Re-run with --apply to write.")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write changes to DB")
    parser.add_argument("--user", type=int, default=None, help="Limit to single user_id")
    args = parser.parse_args()
    main(apply=args.apply, user_filter=args.user)
