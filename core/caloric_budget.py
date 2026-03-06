"""
Caloric budget: daily limit = (BMR + active_kcal) × 0.85
Used to show remaining calories after each meal save.
"""

import logging
from datetime import date as date_type
from typing import Optional

logger = logging.getLogger(__name__)

DEFICIT_RATIO = 0.85   # 15% deficit target
WARN_THRESHOLD = 0.80  # warn when consumed ≥ 80% of target
DEFAULT_TOTAL = 2150   # fallback if no Garmin data (≈ avg from analysis)


def get_daily_budget(user_id: int, for_date: Optional[date_type] = None) -> dict:
    """
    Returns caloric budget for the day.

    Keys:
        consumed   – kcal eaten so far
        target     – daily limit with 15% deficit
        remaining  – target - consumed (can be negative)
        pct        – consumed / target * 100
        warn       – True if consumed >= 80% of target
        has_garmin – True if Garmin 14-day average data was found
    """
    from database import SessionLocal
    from database.crud import get_nutrition_totals_by_date, get_average_activity_stats

    today = for_date or date_type.today()
    db = SessionLocal()
    try:
        # --- Burned: 14-day average total_calories (same source as /day command) ---
        # Using average instead of today's partial Garmin sync to avoid mid-day discrepancies
        avg_stats = get_average_activity_stats(db, user_id, days=14)
        avg_total = avg_stats.get("total_calories") if avg_stats else None
        if avg_total and avg_total > 1500:
            total_burned = avg_total
            has_garmin = True
        else:
            total_burned = DEFAULT_TOTAL
            has_garmin = False

        target = round(total_burned * DEFICIT_RATIO)

        # --- Consumed: today's nutrition_log ---
        totals = get_nutrition_totals_by_date(db, user_id, today)
        consumed = round(totals.get("calories", 0))

        remaining = target - consumed
        pct = round(consumed / target * 100) if target else 0

        return {
            "consumed": consumed,
            "target": target,
            "remaining": remaining,
            "pct": pct,
            "warn": pct >= WARN_THRESHOLD * 100,
            "has_garmin": has_garmin,
        }
    except Exception as e:
        logger.warning(f"get_daily_budget failed: {e}")
        return {}
    finally:
        db.close()


def make_macro_bar(consumed: float, target: float, invert: bool = False) -> tuple:
    """
    Returns (bar_string, pct) colored-square progress bar for a macro.

    invert=False (default) — over target is bad (calories, fat, carbs):
        🟩 < 80%  |  🟧 80–100%  |  🟥 > 100%

    invert=True — under target is bad (protein, fiber):
        🟥 < 50%  |  🟧 50–70%  |  🟩 >= 70%
    """
    pct = round(consumed / target * 100) if target else 0
    filled = min(10, round(pct / 10))

    if invert:
        sq = "🟩" if pct >= 70 else ("🟧" if pct >= 50 else "🟥")
    else:
        sq = "🟥" if pct > 100 else ("🟧" if pct >= 80 else "🟩")

    return sq * filled + "⬜" * (10 - filled), pct


def format_budget_line(user_id: int, for_date: Optional[date_type] = None) -> str:
    """
    Returns a compact one-block string for appending to a Telegram message.

    Example (within limit):
        📊 1 240 / 1 820 ккал · осталось 580

    Example (warning):
        ⚠️ 1 650 / 1 820 ккал · осталось 170

    Example (over):
        🔴 2 100 / 1 820 ккал · перебор +280
    """
    b = get_daily_budget(user_id, for_date)
    if not b:
        return ""

    consumed  = b["consumed"]
    target    = b["target"]
    remaining = b["remaining"]
    pct       = b["pct"]

    # Progress bar: 10 colored squares
    filled = min(10, round(pct / 10))
    if remaining < 0:
        icon = "🔴"
        sq_fill = "🟥"
        tail = f"перебор +{abs(remaining)} ккал"
    elif b["warn"]:
        icon = "⚠️"
        sq_fill = "🟧"
        tail = f"осталось {remaining} ккал"
    else:
        icon = "📊"
        sq_fill = "🟩"
        tail = f"осталось {remaining} ккал"

    bar = sq_fill * filled + "⬜" * (10 - filled)
    hint = "" if b["has_garmin"] else " (≈ среднее)"
    return (
        f"\n{icon} {bar} {pct}%\n"
        f"Сегодня: {consumed} / {target} ккал · {tail}{hint}"
    )
