"""
Caloric budget: daily limit = (BMR + active_kcal) × 0.85
Used to show remaining calories after each meal save.
"""

import logging
from datetime import date as date_type
from typing import Optional

logger = logging.getLogger(__name__)

WARN_THRESHOLD = 0.80  # warn when consumed ≥ 80% of target
DEFAULT_TOTAL = 2150  # fallback if no Garmin data (≈ avg from analysis)
DEFAULT_GOAL_PCT = -15  # default calorie goal: 15% deficit


def get_daily_budget(
    user_id: int,
    for_date: Optional[date_type] = None,
    calorie_goal_pct: Optional[int] = None,
) -> dict:
    """
    Returns caloric budget for the day.

    calorie_goal_pct: signed % vs maintenance.
        -15 = 15% deficit (default), 0 = maintenance, +10 = 10% surplus.
        If None, reads from user_settings (falls back to DEFAULT_GOAL_PCT).

    Keys:
        consumed   – kcal eaten so far
        target     – daily limit adjusted for goal
        remaining  – target - consumed (can be negative)
        pct        – consumed / target * 100
        warn       – True if consumed >= 80% of target
        has_garmin – True if Garmin 14-day average data was found
    """
    from database import SessionLocal
    from database.crud import (
        get_nutrition_totals_by_date,
        get_average_activity_stats,
        get_user_settings,
        get_activities_by_period,
    )
    from datetime import timedelta

    today = for_date or date_type.today()
    db = SessionLocal()
    try:
        s = get_user_settings(db, user_id)
        bmr_source_setting = s.bmr_source if s and s.bmr_source else "auto"

        # ── Resolve BMR + activity by source priority ──────────────────────────
        # 'manual'    → user's Mifflin-St Jeor params (bmr_override + activity_avg_override)
        # 'auto'      → Garmin (14-day avg) > Apple Health (14-day avg) > default
        bmr_avg = None
        total_avg = None
        source_label = None  # 'garmin' | 'apple_health' | 'manual' | 'default'

        if bmr_source_setting == "manual" and s and s.bmr_override:
            bmr_avg = s.bmr_override
            activity_avg_manual = s.activity_avg_override or 0
            total_avg = bmr_avg + activity_avg_manual
            source_label = "manual"
        else:
            # Auto mode: try Garmin first (most accurate), then Apple Health.
            avg_stats = get_average_activity_stats(db, user_id, days=14)
            if avg_stats and avg_stats.get("total_calories", 0) > 1500:
                # Garmin path — has full triple (bmr + active + total).
                # Determine if data is from Garmin or Apple by checking source field
                # of recent activity rows. Garmin pushes total_calories;
                # Apple-only users have total_calories = NULL but bmr_calories filled.
                start = today - timedelta(days=14)
                rows = get_activities_by_period(db, user_id, start, today)
                garmin_rows = [r for r in rows if r.source and "garmin" in r.source.lower() and r.total_calories]
                apple_rows = [r for r in rows if r.source and "apple" in r.source.lower()]
                if len(garmin_rows) >= len(apple_rows):
                    source_label = "garmin"
                else:
                    source_label = "apple_health"
                bmr_avg = round(avg_stats.get("bmr_calories", 0))
                total_avg = round(avg_stats.get("total_calories", 0))

        # ── Default fallback (no wearable, no manual setup) ─────────────────────
        if not total_avg:
            total_burned = DEFAULT_TOTAL
            source_label = source_label or "default"
            has_garmin = False
        else:
            total_burned = total_avg
            has_garmin = source_label in ("garmin", "apple_health")

        if calorie_goal_pct is None:
            calorie_goal_pct = s.calorie_goal_pct if s and s.calorie_goal_pct is not None else DEFAULT_GOAL_PCT
        ratio = 1.0 + calorie_goal_pct / 100.0  # -15 → 0.85, 0 → 1.0, +10 → 1.10
        target = round(total_burned * ratio)

        # --- Consumed: today's nutrition_log ---
        totals = get_nutrition_totals_by_date(db, user_id, today)
        consumed = round(totals.get("calories", 0))

        remaining = target - consumed
        pct = round(consumed / target * 100) if target else 0

        # Activity = total − bmr. Derived (NOT from active_calories field) because
        # Apple Health may overwrite that field, breaking the (total = bmr + active)
        # invariant. Keeps display math internally consistent.
        activity_avg = (total_avg - bmr_avg) if (bmr_avg and total_avg) else None
        if activity_avg is not None and activity_avg < 0:
            activity_avg = 0
        return {
            "consumed": consumed,
            "target": target,
            "remaining": remaining,
            "pct": pct,
            "warn": pct >= WARN_THRESHOLD * 100,
            "has_garmin": has_garmin,
            "bmr_avg": bmr_avg,
            "activity_avg": activity_avg,
            "tdee_avg": total_avg,
            "bmr_source": source_label,  # 'garmin' | 'apple_health' | 'manual' | 'default'
            "calorie_goal_pct": calorie_goal_pct,
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


def make_block_bar(consumed: float, target: float, invert: bool = False) -> tuple:
    """
    Returns (bar_string, pct) — emoji progress bar, 10 squares, no hybrid chars.

    invert=False — over target is bad (calories, fat, carbs)
    invert=True  — under target is bad (protein, fiber)
    """
    pct = round(consumed / target * 100) if target else 0
    filled = min(10, round(pct / 10))

    if invert:
        sq = "🟩" if pct >= 70 else ("🟧" if pct >= 50 else "🟥")
    else:
        sq = "🟥" if pct > 100 else ("🟧" if pct >= 80 else "🟩")

    bar = sq * filled + "⬜" * (10 - filled)
    return bar, pct


def format_budget_line(user_id: int, for_date: Optional[date_type] = None, show_bar: bool = True) -> str:
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

    consumed = b["consumed"]
    target = b["target"]
    remaining = b["remaining"]
    pct = b["pct"]

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

    hint = "" if b["has_garmin"] else " (≈ среднее)"
    from datetime import timedelta

    today = date_type.today()
    yesterday = today - timedelta(days=1)
    if for_date is None or for_date == today:
        day_label = "Сегодня"
    elif for_date == yesterday:
        day_label = "Вчера"
    else:
        day_label = for_date.strftime("%d.%m")
    if show_bar:
        bar = sq_fill * filled + "⬜" * (10 - filled)
        return f"\n{icon} {bar} {pct}%\n{day_label}: {consumed} / {target} ккал · {tail}{hint}"
    else:
        return f"\n{icon} {day_label}: {consumed} / {target} ккал · {tail}{hint}"
