"""One-off: backfill fiber on historical nutrition_log items using fiber_table.

For each NutritionLog:
  - For each item without a positive fiber value, estimate from product name + weight_g/amount.
  - Recompute totals.fiber = sum of item fibers (only if totals.fiber <= 0, to avoid
    overwriting explicit totals from recipe cards).

Idempotent: items that already have fiber>0 are not touched.

Run inside the bot container:
  docker exec -w /app healthvault_bot python -m scripts.backfill_fiber_history          # dry run
  docker exec -w /app healthvault_bot python -m scripts.backfill_fiber_history --apply  # apply
"""

import sys

from sqlalchemy.orm.attributes import flag_modified

from database import SessionLocal
from database.models import NutritionLog
from core.food.fiber_table import estimate_fiber


def item_weight(it: dict) -> float | None:
    for k in ("weight_g", "amount", "weight"):
        v = it.get(k)
        if v:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None


def item_name(it: dict) -> str:
    return (it.get("product") or it.get("name") or it.get("food") or "").strip()


def main(apply: bool) -> None:
    db = SessionLocal()
    try:
        rows = db.query(NutritionLog).order_by(NutritionLog.date).all()

        logs_touched = 0
        items_updated = 0
        total_fiber_added = 0.0

        for row in rows:
            items = list(row.items or [])
            if not items:
                continue

            row_changed = False
            added_fiber_sum = 0.0

            for it in items:
                existing = it.get("fiber")
                if existing is not None and existing > 0:
                    continue
                fb = estimate_fiber(item_name(it), item_weight(it))
                if fb <= 0:
                    if existing is None:
                        it["fiber"] = 0.0
                        row_changed = True
                    continue
                it["fiber"] = fb
                added_fiber_sum += fb
                items_updated += 1
                row_changed = True

            if not row_changed:
                continue

            # Recompute totals.fiber unless the log already had a positive totals.fiber.
            totals = dict(row.totals or {})
            existing_total_fiber = totals.get("fiber") or 0
            if existing_total_fiber <= 0:
                totals["fiber"] = round(sum((it.get("fiber") or 0) for it in items), 1)

            if apply:
                row.items = items
                row.totals = totals
                flag_modified(row, "items")
                flag_modified(row, "totals")

            logs_touched += 1
            total_fiber_added += added_fiber_sum
            print(
                f"[{'APPLY' if apply else 'DRY '}] uid={row.user_id} {row.date} "
                f"{row.meal_name!r}: +{round(added_fiber_sum, 1)}g fiber across items"
            )

        if apply:
            db.commit()

        print("---")
        print(f"logs touched:    {logs_touched}")
        print(f"items updated:   {items_updated}")
        print(f"total fiber added (sum over items): {round(total_fiber_added, 1)} g")
        if not apply:
            print("\nDry run. Re-run with --apply to write.")
    finally:
        db.close()


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
