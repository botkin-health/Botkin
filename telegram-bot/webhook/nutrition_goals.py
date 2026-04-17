"""Derive daily macro goals from caloric budget + fixed split.

Used by GET /api/day to populate progress bars.
"""

from datetime import date as date_type
from typing import Optional

from core.health.caloric_budget import get_daily_budget

PROTEIN_SHARE = 0.30
FATS_SHARE = 0.30
CARBS_SHARE = 0.40
FIBER_GOAL_G = 30


def compute_goals(user_id: int, for_date: Optional[date_type] = None) -> dict:
    budget = get_daily_budget(user_id=user_id, for_date=for_date)
    kcal = budget.get("target")
    if not kcal:
        return {"kcal": None, "protein": None, "fats": None, "carbs": None, "fiber": FIBER_GOAL_G}
    return {
        "kcal": int(kcal),
        "protein": round(kcal * PROTEIN_SHARE / 4),
        "fats": round(kcal * FATS_SHARE / 9),
        "carbs": round(kcal * CARBS_SHARE / 4),
        "fiber": FIBER_GOAL_G,
    }
