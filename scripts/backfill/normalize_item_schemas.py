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


def _is_non_canonical_item(item: dict) -> bool:
    """
    True only if item's SCHEMA is not canonical (wrong key names).
    Canonical requires both "food" and "amount" and no legacy weight_g/weight/name/product keys.

    We do NOT count value-level differences (e.g. 250.5 → 250 from int rounding)
    as reason to rewrite — that would churn every historical row unnecessarily.
    """
    has_canonical_keys = "food" in item and "amount" in item
    has_legacy_keys = any(k in item for k in ("weight_g", "weight", "name", "product"))
    return not has_canonical_keys or has_legacy_keys


def _row_needs_normalization(items: list) -> bool:
    return any(_is_non_canonical_item(dict(it)) for it in items)


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

            if not _row_needs_normalization(old_items):
                unchanged += 1
                continue

            new_items = [normalize_item_to_canonical(dict(it)) for it in old_items]

            changed += 1
            first_old = dict(old_items[0])
            first_new = dict(new_items[0])
            diff_keys = sorted(set(first_old) ^ set(first_new))
            print(
                f"[{'APPLY' if apply else 'DRY '}] id={row.id} uid={row.user_id} "
                f"{row.date} {row.meal_name!r} items={len(old_items)} diff={diff_keys}"
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
