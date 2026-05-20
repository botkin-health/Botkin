"""Agent Tools API — 8 endpoints for NanoClaw containers.

All endpoints require JWT auth via Depends(get_agent_user).
Prefix: /api/agent

Tasks 5-7 of HealthVault Sprint 1a:
  - Task 5: Write endpoints (log_meal_text, log_supplement, log_bp, regenerate_health_token)
  - Task 6: Write endpoints continued
  - Task 7: Read endpoints (recent_meals, kb_value, dashboard_summary, user_profile)
"""

import sys
import secrets
import logging
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

# Ensure project root on path for database imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from webhook.jwt_auth import get_agent_user, get_db  # noqa: E402

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent-tools"])


# ── Request / Response schemas ────────────────────────────────────────────────


class LogMealTextRequest(BaseModel):
    text: str
    date: Optional[str] = None  # YYYY-MM-DD; defaults to today
    slot: Optional[str] = None  # breakfast | lunch | dinner | snack; auto-detected if None


class LogSupplementRequest(BaseModel):
    supplement_name: str
    dosage: Optional[str] = None
    date: Optional[str] = None  # YYYY-MM-DD; defaults to today
    time: Optional[str] = None  # HH:MM


class LogBPRequest(BaseModel):
    systolic: int = Field(..., ge=50, le=300, description="Systolic pressure mmHg")
    diastolic: int = Field(..., ge=30, le=200, description="Diastolic pressure mmHg")
    pulse: Optional[int] = Field(None, ge=30, le=250, description="Pulse bpm")
    measured_at: Optional[str] = None  # ISO datetime; defaults to now


# ── Helpers ───────────────────────────────────────────────────────────────────


def _parse_date(date_str: Optional[str]) -> date:
    """Parse YYYY-MM-DD string or return today."""
    if not date_str:
        return date.today()
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {date_str!r}. Use YYYY-MM-DD.")


def _parse_time(time_str: Optional[str]):
    """Parse HH:MM string or return None."""
    if not time_str:
        return None
    from datetime import time as time_cls

    try:
        h, m = time_str.split(":")
        return time_cls(int(h), int(m))
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid time format: {time_str!r}. Use HH:MM.")


def _slot_to_meal_time(slot: Optional[str]):
    """Map slot name to a default meal time."""
    from datetime import time as time_cls

    mapping = {
        "breakfast": time_cls(8, 0),
        "lunch": time_cls(13, 0),
        "dinner": time_cls(19, 0),
        "snack": time_cls(16, 0),
    }
    if slot is None:
        return time_cls(12, 0), "Приём пищи"
    slot = slot.lower()
    if slot not in mapping:
        raise HTTPException(status_code=400, detail=f"Invalid slot {slot!r}. Use: breakfast, lunch, dinner, snack.")
    name_map = {
        "breakfast": "Завтрак",
        "lunch": "Обед",
        "dinner": "Ужин",
        "snack": "Перекус",
    }
    return mapping[slot], name_map[slot]


# ── Task 5: Write endpoints ───────────────────────────────────────────────────


@router.post("/log_meal_text")
async def log_meal_text(
    req: LogMealTextRequest,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Parse free-text meal description and save to nutrition_log.

    Attempts to use the existing food parsing pipeline. Falls back to a stub
    that stores the raw text when the parser is not available / tightly coupled.
    """
    from database.crud import create_nutrition_log
    from core.llm.router import analyze_message
    from core.food.nutrition import process_llm_food_data

    record_date = _parse_date(req.date)
    meal_time, meal_name = _slot_to_meal_time(req.slot)

    # Use the real food parser (Claude vision/text via core.llm.router).
    # Returns dict like {"type": "food", "data": {...}} which the photo/text
    # handlers feed into process_llm_food_data() to get (items, totals).
    items: list = []
    totals: dict = {}
    parse_error: Optional[str] = None

    try:
        llm_result = analyze_message(text=req.text)
        if not llm_result or llm_result.get("type") != "food":
            parse_error = (
                "LLM не распознал это как еду "
                f"(type={llm_result.get('type') if llm_result else 'None'}). "
                "Опиши конкретнее: что, сколько, как приготовлено."
            )
        else:
            items, totals = process_llm_food_data(llm_result, req.text)
    except Exception as e:
        logger.exception("log_meal_text: parser failed")
        parse_error = f"парсер упал: {e}"

    # Refuse to write a row if we got no KБЖУ — empty rows break the
    # Mini App dashboard (None aggregations) and are useless to the user.
    if not items or not (totals.get("calories") or 0):
        return {
            "status": "rejected",
            "reason": parse_error or "не удалось распарсить КБЖУ для этого описания",
            "hint": "опиши подробнее: продукт + примерный вес/количество, например 'куриная грудка 200г и рис 150г'",
        }

    # Normalize fiber default so JSONB stores 0, not null
    if totals.get("fiber") is None:
        totals["fiber"] = 0

    log = create_nutrition_log(
        db=db,
        user_id=user.telegram_id,
        date=record_date,
        meal_time=meal_time,
        meal_name=meal_name,
        items=items,
        totals=totals,
    )

    return {
        "status": "ok",
        "meal_id": log.id,
        "date": record_date.isoformat(),
        "slot": req.slot or "auto",
        "meal_name": meal_name,
        "items_count": len(items),
        "totals": totals,
    }


@router.post("/log_supplement")
async def log_supplement(
    req: LogSupplementRequest,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Save a supplement entry to supplements_log."""
    from database.crud import create_supplement_log

    record_date = _parse_date(req.date)
    sup_time = _parse_time(req.time)

    log = create_supplement_log(
        db=db,
        user_id=user.telegram_id,
        date=record_date,
        time=sup_time,
        supplement_name=req.supplement_name,
        dosage=req.dosage,
    )

    return {
        "status": "ok",
        "supplement_id": log.id,
        "date": record_date.isoformat(),
        "supplement_name": req.supplement_name,
        "dosage": req.dosage,
    }


@router.post("/log_bp")
async def log_bp(
    req: LogBPRequest,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Save a blood pressure reading to blood_pressure_logs."""
    from sqlalchemy import text as _text

    # Parse measured_at
    if req.measured_at:
        try:
            measured_at = datetime.fromisoformat(req.measured_at)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid measured_at: {req.measured_at!r}. Use ISO datetime.")
    else:
        measured_at = datetime.now(timezone.utc)

    db.execute(
        _text(
            """INSERT INTO blood_pressure_logs
               (user_id, measured_at, systolic, diastolic, heart_rate, source)
               VALUES (:uid, :ts, :sys, :dia, :hr, 'agent_api')
               ON CONFLICT (user_id, measured_at) DO UPDATE
                 SET systolic = EXCLUDED.systolic,
                     diastolic = EXCLUDED.diastolic,
                     heart_rate = COALESCE(EXCLUDED.heart_rate, blood_pressure_logs.heart_rate)"""
        ),
        {
            "uid": user.telegram_id,
            "ts": measured_at,
            "sys": req.systolic,
            "dia": req.diastolic,
            "hr": req.pulse,
        },
    )
    db.commit()

    return {
        "status": "ok",
        "measured_at": measured_at.isoformat(),
        "systolic": req.systolic,
        "diastolic": req.diastolic,
        "pulse": req.pulse,
    }


@router.post("/regenerate_health_token")
async def regenerate_health_token(
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Generate a new health_token for the user and save it to users table."""
    new_token = f"hvt_{user.telegram_id}_{secrets.token_hex(16)}"
    user.health_token = new_token
    db.commit()

    return {
        "status": "ok",
        "health_token": new_token,
    }


# ── Task 7: Read endpoints ────────────────────────────────────────────────────


@router.get("/recent_meals")
async def recent_meals(
    days: int = 7,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Return nutrition_log rows for the last N days."""
    from database.crud import get_nutrition_logs_by_period

    if days < 1 or days > 90:
        raise HTTPException(status_code=400, detail="days must be between 1 and 90")

    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)

    logs = get_nutrition_logs_by_period(db, user.telegram_id, start_date, end_date)

    result = []
    for log in logs:
        result.append(
            {
                "id": log.id,
                "date": log.date.isoformat(),
                "meal_time": log.meal_time.strftime("%H:%M") if log.meal_time else None,
                "meal_name": log.meal_name,
                "items": log.items,
                "totals": log.totals,
            }
        )

    return {
        "status": "ok",
        "days": days,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "meals": result,
    }


@router.get("/kb_value")
async def kb_value(
    key: str,
    user=Depends(get_agent_user),
):
    """Look up a value in knowledge_base.json by key path.

    Only available for the 'owner' cohort. Other users receive a stub response.
    """
    if user.cohort != "owner":
        return {"key": key, "value": None, "source": "not-implemented"}

    kb_path = Path(__file__).resolve().parents[2] / "knowledge_base.json"
    if not kb_path.exists():
        return {"key": key, "value": None, "source": "kb-not-found"}

    import json

    try:
        with open(kb_path, encoding="utf-8") as f:
            kb = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read knowledge_base.json: {e}")

    # Support dot-notation path traversal: e.g. "blood_tests.0.values.cholesterol"
    value = kb
    for part in key.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list):
            try:
                value = value[int(part)]
            except (ValueError, IndexError):
                value = None
        else:
            value = None
        if value is None:
            break

    return {"key": key, "value": value, "source": "knowledge_base.json"}


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

    end_date = date.today()
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
    }


@router.get("/recent_bp")
async def recent_bp(
    days: int = 14,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Recent blood-pressure measurements (last `days`).

    Returns each row with measured_at, systolic, diastolic, pulse, source.
    Plus simple aggregates: mean/min/max systolic+diastolic, latest pulse,
    pct of measurements above 140/90 (Stage 1 hypertension threshold).
    """
    from sqlalchemy import text as sql_text

    days = max(1, min(days, 90))
    sql = sql_text(
        """
        SELECT measured_at, systolic, diastolic, heart_rate, source
        FROM blood_pressure_logs
        WHERE user_id = :uid
          AND measured_at >= NOW() - (:days || ' days')::interval
        ORDER BY measured_at DESC
        LIMIT 200
        """
    )
    rows = db.execute(sql, {"uid": user.telegram_id, "days": days}).fetchall()
    items = [
        {
            "measured_at": r.measured_at.isoformat(),
            "systolic": r.systolic,
            "diastolic": r.diastolic,
            "pulse": r.heart_rate,
            "source": r.source,
        }
        for r in rows
    ]

    if not items:
        return {"status": "ok", "period_days": days, "count": 0, "items": []}

    sys_vals = [i["systolic"] for i in items]
    dia_vals = [i["diastolic"] for i in items]
    above_threshold = sum(1 for i in items if i["systolic"] >= 140 or i["diastolic"] >= 90)

    return {
        "status": "ok",
        "period_days": days,
        "count": len(items),
        "stats": {
            "systolic": {"avg": round(sum(sys_vals) / len(sys_vals), 1), "min": min(sys_vals), "max": max(sys_vals)},
            "diastolic": {"avg": round(sum(dia_vals) / len(dia_vals), 1), "min": min(dia_vals), "max": max(dia_vals)},
            "stage1_pct": round(100 * above_threshold / len(items), 1),
        },
        "items": items[:30],  # cap for token budget
    }


@router.get("/recent_sleep")
async def recent_sleep(
    days: int = 14,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Recent sleep — derived from activity_log.raw_data (Garmin daily-summary).

    The dedicated `sleep_records` table exists but isn't populated yet —
    Garmin sync writes daily totals into `activity_log.raw_data.sleepingSeconds`.
    This endpoint reads from there so the agent has live data without a
    separate ETL job (see tech debt in projects/2026-05_nanoclaw-agent-bot/PLAN.md).

    Date semantics: each row's `date` is the calendar day; `sleepingSeconds`
    is for the night ENDING on that day (Garmin convention).

    Extra fields available when source='garmin_sleep' (rare): `deep_h`, `rem_h`, `sleep_score`.
    """
    from sqlalchemy import text as sql_text

    days = max(1, min(days, 90))
    sql = sql_text(
        """
        SELECT date,
               (raw_data->>'sleepingSeconds')::numeric / 3600.0 AS duration_hours,
               (raw_data->>'sleep_score')::int               AS quality_score,
               (raw_data->>'deep_h')::numeric * 60           AS deep_min,
               (raw_data->>'rem_h')::numeric * 60            AS rem_min,
               source
        FROM activity_log
        WHERE user_id = :uid
          AND raw_data ? 'sleepingSeconds'
          AND (raw_data->>'sleepingSeconds')::int > 0
          AND date >= CURRENT_DATE - (:days || ' days')::interval
        ORDER BY date DESC
        """
    )
    rows = db.execute(sql, {"uid": user.telegram_id, "days": days}).fetchall()
    items = [
        {
            "date": r.date.isoformat(),
            "duration_hours": round(float(r.duration_hours), 2) if r.duration_hours is not None else None,
            "quality_score": r.quality_score,
            "deep_min": int(r.deep_min) if r.deep_min is not None else None,
            "rem_min": int(r.rem_min) if r.rem_min is not None else None,
            "source": r.source,
        }
        for r in rows
    ]

    if not items:
        return {"status": "ok", "period_days": days, "count": 0, "items": []}

    dur = [i["duration_hours"] for i in items if i["duration_hours"]]
    qual = [i["quality_score"] for i in items if i["quality_score"]]
    # Sleep quality flags by duration vs 7h adequate / 6h marginal.
    below_6h = sum(1 for d in dur if d < 6)
    return {
        "status": "ok",
        "period_days": days,
        "count": len(items),
        "stats": {
            "avg_duration_h": round(sum(dur) / len(dur), 2) if dur else None,
            "min_duration_h": round(min(dur), 2) if dur else None,
            "max_duration_h": round(max(dur), 2) if dur else None,
            "avg_quality": round(sum(qual) / len(qual), 1) if qual else None,
            "nights_below_6h": below_6h,
            "nights_below_6h_pct": round(100 * below_6h / len(dur), 1) if dur else None,
        },
        "items": items[:14],
    }


@router.get("/recent_biomarkers")
async def recent_biomarkers(
    limit: int = 5,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Most recent blood tests (latest `limit`).

    Each row has test_date + test_type + values (jsonb dict of marker → value).
    Defaults to 5 most recent — enough for "what were my last labs?".
    """
    from sqlalchemy import text as sql_text

    limit = max(1, min(limit, 20))
    sql = sql_text(
        """
        SELECT test_date, test_type, values
        FROM blood_tests
        WHERE user_id = :uid
        ORDER BY test_date DESC
        LIMIT :lim
        """
    )
    rows = db.execute(sql, {"uid": user.telegram_id, "lim": limit}).fetchall()
    return {
        "status": "ok",
        "count": len(rows),
        "tests": [
            {
                "date": r.test_date.isoformat(),
                "type": r.test_type,
                "values": r.values,
            }
            for r in rows
        ],
    }


@router.get("/user_profile")
async def user_profile(
    user=Depends(get_agent_user),
):
    """Return non-sensitive user profile info."""
    return {
        "status": "ok",
        "telegram_id": user.telegram_id,
        "first_name": user.first_name,
        "username": getattr(user, "username", None),
        "cohort": user.cohort,
        "container_id": user.container_id,
        "pack_name": user.pack_name,
        "garmin_email": user.garmin_email,  # intentionally included: agent needs to label data sources
        # NOTE: garmin_password is intentionally excluded
        "health_token": user.health_token,
        "timezone": getattr(user, "timezone", "Europe/Moscow"),
        "sex": getattr(user, "sex", None),
        "height_cm": getattr(user, "height_cm", None),
        "birth_date": user.birth_date.isoformat() if getattr(user, "birth_date", None) else None,
    }
