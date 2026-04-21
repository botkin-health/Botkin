"""One-off: backfill nutrition_log from historical psyllium entries in supplements_log.

Idempotent — uses UniqueConstraint (user_id, date, meal_time, meal_name). Re-runs are safe.
Run inside the bot container: docker exec healthvault_bot python scripts/backfill_psyllium_nutrition.py [--apply]
"""

import sys
from sqlalchemy.exc import IntegrityError

from database import SessionLocal
from database.models import SupplementLog, NutritionLog
from core.health.supplements import SUPPLEMENT_NUTRITION, _canonical_supplement_name
from helpers.db_save import normalize_item_to_canonical


def main(apply: bool) -> None:
    db = SessionLocal()
    try:
        rows = db.query(SupplementLog).order_by(SupplementLog.date, SupplementLog.time).all()

        planned = 0
        created = 0
        skipped_existing = 0

        for row in rows:
            canonical = _canonical_supplement_name(row.supplement_name)
            nutri = SUPPLEMENT_NUTRITION.get(canonical) if canonical else None
            if not nutri:
                continue

            planned += 1

            exists = (
                db.query(NutritionLog)
                .filter(
                    NutritionLog.user_id == row.user_id,
                    NutritionLog.date == row.date,
                    NutritionLog.meal_time == row.time,
                    NutritionLog.meal_name == nutri["display"],
                )
                .first()
            )
            if exists:
                skipped_existing += 1
                continue

            print(f"[{'APPLY' if apply else 'DRY '}] uid={row.user_id} {row.date} {row.time} → {nutri['display']}")
            if apply:
                raw = {k: nutri[k] for k in ("calories", "protein", "fats", "carbs", "fiber")}
                raw["name"] = nutri["display"]
                raw["weight_g"] = nutri["weight_g"]
                # Route through single canonical normaliser — no bypass writes
                item = normalize_item_to_canonical(raw)
                totals = {k: nutri[k] for k in ("calories", "protein", "fats", "carbs", "fiber")}
                log = NutritionLog(
                    user_id=row.user_id,
                    date=row.date,
                    meal_time=row.time,
                    meal_name=nutri["display"],
                    items=[item],
                    totals=totals,
                    photo_paths=[],
                )
                db.add(log)
                try:
                    db.commit()
                    created += 1
                except IntegrityError:
                    db.rollback()
                    skipped_existing += 1

        print("---")
        print(f"supplement_log rows matching known nutrition: {planned}")
        print(f"already backfilled (skipped): {skipped_existing}")
        print(f"created new nutrition_log rows: {created}")
        if not apply:
            print("\nDry run. Re-run with --apply to write.")
    finally:
        db.close()


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
