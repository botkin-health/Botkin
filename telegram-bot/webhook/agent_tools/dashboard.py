"""Agent tools: dashboard summary, day summary, recent trends."""

import logging
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import ActivityLog, NutritionLog, Weight
from webhook.jwt_auth import get_agent_user, get_db
from config.settings import public_base_url
from .common import _today_in_user_tz

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent", tags=["agent-tools-dashboard"])


@router.get("/dashboard_summary")
async def dashboard_summary(
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Aggregated health metrics for the last 7 days.

    Returns averages for steps, HR, calories consumed, and latest weight.
    Handles missing data gracefully (None values).
    """
    from database.crud import (
        get_activity_logs_by_period,
        get_nutrition_logs_by_period,
        get_latest_weight,
    )

    end_date = _today_in_user_tz(user)
    start_date = end_date - timedelta(days=6)

    activity_rows = get_activity_logs_by_period(db, user.telegram_id, start_date, end_date)
    nutrition_rows = get_nutrition_logs_by_period(db, user.telegram_id, start_date, end_date)
    latest_weight = get_latest_weight(db, user.telegram_id)

    # Activity aggregations
    steps_vals = [r.steps for r in activity_rows if r.steps is not None]
    hr_vals = [r.heart_rate_avg for r in activity_rows if r.heart_rate_avg is not None]
    kcal_burned_vals = [r.total_calories for r in activity_rows if r.total_calories is not None]

    # Nutrition aggregations — sum per day, then average
    from collections import defaultdict

    kcal_by_day: dict = defaultdict(float)
    for row in nutrition_rows:
        totals = row.totals or {}
        kcal = totals.get("calories") or 0
        kcal_by_day[row.date.isoformat()] += kcal
    kcal_consumed_vals = list(kcal_by_day.values())

    def _avg(vals):
        return round(sum(vals) / len(vals), 1) if vals else None

    return {
        "status": "ok",
        "period": {"start": start_date.isoformat(), "end": end_date.isoformat(), "days": 7},
        "activity": {
            "avg_steps": int(_avg(steps_vals)) if _avg(steps_vals) is not None else None,
            "avg_hr": int(_avg(hr_vals)) if _avg(hr_vals) is not None else None,
            "avg_kcal_burned": _avg(kcal_burned_vals),
            "days_with_data": len(activity_rows),
        },
        "nutrition": {
            "avg_kcal_consumed": _avg(kcal_consumed_vals),
            "days_with_logs": len(kcal_by_day),
        },
        "weight": {
            "latest_kg": latest_weight.weight if latest_weight else None,
            "latest_date": latest_weight.measured_at.date().isoformat() if latest_weight else None,
            "body_fat_pct": latest_weight.body_fat if latest_weight else None,
        },
        "dashboard_url": f"{public_base_url()}/mc/{user.share_token}" if user.share_token else None,
    }


@router.get("/day_summary")
async def day_summary(
    date: str,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Сводка за конкретный день: ккал, БЖУ, шаги, сон, вес, АД, был ли воркаут.

    Live-агрегация из nutrition_log + activity_log + weights + blood_pressure_logs
    (таблица daily_summaries никогда не заполнялась — аудит 11.06.2026).

    Используй для вопросов «что у меня было 14 марта», «как был день N»,
    «сравни такой-то день с другим».
    """
    from sqlalchemy import text as sql_text
    from datetime import date as date_cls

    try:
        target_date = date_cls.fromisoformat(date)
    except ValueError:
        return {"status": "error", "error": f"invalid date format: {date!r} (expected YYYY-MM-DD)"}

    uid = user.telegram_id

    # Питание: суммируем totals по всем приёмам за день
    nutrition = None
    meals = db.query(NutritionLog).filter(NutritionLog.user_id == uid, NutritionLog.date == target_date).all()
    if meals:
        from core.food.water_table import sum_water_ml

        def _tot(key: str) -> float:
            return round(sum(float((m.totals or {}).get(key) or 0) for m in meals), 1)

        # Вода (#526) не хранится в totals — считаем из items на чтении, как
        # в get_nutrition_totals_by_date (database/crud.py).
        water_ml = round(sum(sum_water_ml(m.items or []) for m in meals), 1)

        nutrition = {
            "calories": _tot("calories"),
            "protein_g": _tot("protein"),
            "fats_g": _tot("fats"),
            "carbs_g": _tot("carbs"),
            "fiber_g": _tot("fiber"),
            "water_ml": water_ml,
            "meals_count": len(meals),
        }

    # Активность: одна строка на день (HAE/Garmin upsert)
    act = db.query(ActivityLog).filter(ActivityLog.user_id == uid, ActivityLog.date == target_date).first()
    activity = None
    sleep_hours = None
    if act:
        activity = {
            "steps": act.steps,
            "active_calories": act.active_calories,
            "distance_km": act.distance_km,
            "heart_rate_avg": act.heart_rate_avg,
            "hrv": act.hrv,
        }
        sleep_hours = float(act.sleep_hours) if act.sleep_hours is not None else None

    # Вес: последний замер за день
    w = (
        db.query(Weight)
        .filter(Weight.user_id == uid, func.date(Weight.measured_at) == target_date)
        .order_by(Weight.measured_at.desc())
        .first()
    )

    # АД и воркауты — таблицы вне ORM (нет на SQLite в тестах) → guarded raw SQL
    blood_pressure = None
    had_workout = None
    try:
        bp = db.execute(
            sql_text(
                """SELECT systolic, diastolic, heart_rate FROM blood_pressure_logs
                   WHERE user_id = :uid AND measured_at::date = :d
                   ORDER BY measured_at DESC LIMIT 1"""
            ),
            {"uid": uid, "d": target_date},
        ).fetchone()
        if bp:
            blood_pressure = {"systolic": bp.systolic, "diastolic": bp.diastolic, "pulse": bp.heart_rate}
        wk = db.execute(
            sql_text("SELECT COUNT(*) FROM workouts WHERE user_id = :uid AND start_time::date = :d"),
            {"uid": uid, "d": target_date},
        ).scalar()
        had_workout = bool(wk)
    except Exception as e:
        logger.warning(f"day_summary raw-SQL part failed (ok on SQLite tests): {e}")
        db.rollback()

    if not meals and not act and not w and not blood_pressure:
        return {"status": "no_data", "date": target_date.isoformat(), "reason": "no records for this date"}

    return {
        "status": "ok",
        "date": target_date.isoformat(),
        "nutrition": nutrition,
        "activity": activity,
        "had_workout": had_workout,
        "sleep_hours": sleep_hours,
        "weight_kg": float(w.weight) if w else None,
        "blood_pressure": blood_pressure,
    }


# Метрики, которые Apple Health присылает, а колонок под них в activity_log нет:
# парсер кладёт их в raw_data (см. apple_health.py, список raw_extra). Данные есть
# с первого дня канала, но инструментами не читались — 15.09.2026 выяснилось, что
# агент про сатурацию, VO2max, фазы сна и температуру запястья не знает вовсе.
# Заводить 18 колонок ради этого не нужно, достаточно отдать raw_data как есть.
_APPLE_RAW_FIELDS = (
    "vo2_max",
    "spo2_pct",
    "respiratory_rate",
    "wrist_temperature",
    "heart_rate_min",
    "heart_rate_max",
    "sleep_deep_h",
    "sleep_rem_h",
    "sleep_core_h",
    "sleep_awake_h",
    "walking_speed_km_h",
    "walking_step_length_cm",
    "walking_double_support_pct",
    "walking_asymmetry_pct",
    "flights_climbed",
    "apple_active_energy_kcal",
    "apple_basal_energy_kcal",
)


@router.get("/daily_metrics")
async def daily_metrics(
    days: int = 14,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Посуточные метрики Apple Health, которых нет отдельными колонками.

    Сатурация, VO2max, частота дыхания, температура запястья, min/max пульса,
    фазы сна (глубокий/REM/базовый/пробуждения), метрики походки, этажи и
    active energy Apple. Всё это приезжает с первого дня канала и лежит в
    `activity_log.raw_data` — до 15.09.2026 прочитать было нечем.

    `available` перечисляет, по скольким дням окна метрика реально есть: если
    поля там нет, значит телефон его не присылает, а не «данных нет вообще».
    """
    days = max(1, min(days, 180))
    since = _today_in_user_tz(user) - timedelta(days=days)
    rows = (
        db.query(ActivityLog)
        .filter(ActivityLog.user_id == user.telegram_id, ActivityLog.date >= since)
        .order_by(ActivityLog.date.desc())
        .limit(180)
        .all()
    )

    items: list[dict[str, Any]] = []
    available: dict[str, int] = {}
    for r in rows:
        raw = r.raw_data if isinstance(r.raw_data, dict) else {}
        item: dict[str, Any] = {
            "date": r.date.isoformat(),
            "steps": r.steps,
            "rhr": r.heart_rate_avg,
            "hrv": r.hrv,
            "sleep_hours": r.sleep_hours,
        }
        for key in _APPLE_RAW_FIELDS:
            val = raw.get(key)
            if val is not None:
                item[key] = val
                available[key] = available.get(key, 0) + 1
        items.append(item)

    return {
        "status": "ok",
        "period_days": days,
        "count": len(items),
        "available": available,
        "items": items[:30],  # cap for token budget
    }


@router.get("/recent_trends")
async def recent_trends(
    days: int = 14,
    full_series: bool = False,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Per-day trends from activity_log.raw_data: HRV, Body Battery, Stress, Steps, Alcohol.

    Complementary to get_dashboard_summary (which gives 7-day AVG only).
    Use this for trend questions: 'падает ли мой HRV?', 'сколько у меня
    Body Battery утром', 'когда самый высокий стресс'.

    `alcohol` (bool) per day — был ли в этот день приём пищи с алкоголем
    (флаг из nutrition_log.totals.has_alcohol). Полезно для корреляций
    'алкоголь → HRV/стресс следующего дня'.

    Окно до 180 дней. По умолчанию возвращается до 30 последних точек в
    `items`. Для корреляций/графиков на длинном окне передай
    `full_series=true` — тогда вернутся ВСЕ точки окна (тяжелее, но нужно
    чтобы посчитать связь на 90-180 днях).
    """
    from sqlalchemy import text as sql_text

    days = max(1, min(days, 180))
    sql = sql_text(
        """
        SELECT al.date,
               al.steps,
               al.heart_rate_avg AS rhr,
               al.hrv,
               al.stress_level,
               al.sleep_hours,
               (al.raw_data->>'bodyBatteryHighestValue')::int  AS body_battery_max,
               (al.raw_data->>'bodyBatteryAtWakeTime')::int    AS body_battery_wake,
               (al.raw_data->>'bodyBatteryLowestValue')::int   AS body_battery_min,
               (al.raw_data->>'averageStressLevel')::int       AS stress_avg,
               COALESCE(nu.alcohol, false)                     AS alcohol
        FROM activity_log al
        LEFT JOIN (
            SELECT date, bool_or((totals->>'has_alcohol') = 'true') AS alcohol
            FROM nutrition_log
            WHERE user_id = :uid
            GROUP BY date
        ) nu ON nu.date = al.date
        WHERE al.user_id = :uid
          AND al.date >= CURRENT_DATE - (:days || ' days')::interval
        ORDER BY al.date DESC
        """
    )
    rows = db.execute(sql, {"uid": user.telegram_id, "days": days}).fetchall()

    items = [
        {
            "date": r.date.isoformat(),
            "steps": r.steps,
            "rhr": r.rhr,
            "hrv": r.hrv,
            "stress_level": r.stress_level or r.stress_avg,
            "sleep_h": float(r.sleep_hours) if r.sleep_hours else None,
            "body_battery_morning": r.body_battery_wake,
            "body_battery_max": r.body_battery_max,
            "body_battery_min": r.body_battery_min,
            "alcohol": bool(r.alcohol),
        }
        for r in rows
    ]

    def _avg_or_none(vals: list):
        clean = [v for v in vals if v is not None]
        return round(sum(clean) / len(clean), 1) if clean else None

    return {
        "status": "ok",
        "period_days": days,
        "count": len(items),
        "stats": {
            "hrv_avg": _avg_or_none([i["hrv"] for i in items]),
            "hrv_min": min((i["hrv"] for i in items if i["hrv"]), default=None),
            "hrv_max": max((i["hrv"] for i in items if i["hrv"]), default=None),
            "rhr_avg": _avg_or_none([i["rhr"] for i in items]),
            "stress_avg": _avg_or_none([i["stress_level"] for i in items]),
            "body_battery_morning_avg": _avg_or_none([i["body_battery_morning"] for i in items]),
            "steps_avg": _avg_or_none([i["steps"] for i in items]),
            "alcohol_days": sum(1 for i in items if i["alcohol"]),
        },
        "items": items if full_series else items[:30],
    }
