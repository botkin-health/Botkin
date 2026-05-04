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
from pydantic import BaseModel
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
    systolic: int
    diastolic: int
    pulse: Optional[int] = None
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

    record_date = _parse_date(req.date)
    meal_time, meal_name = _slot_to_meal_time(req.slot)

    # Try to use the real parser from core
    items = None
    totals = None
    try:
        from core.nutrition.food_parser import parse_food_text  # type: ignore

        items, totals = parse_food_text(req.text)
    except Exception:
        pass

    if items is None:
        # Fallback stub: store raw text, calories unknown
        items = [{"food": req.text, "amount_g": None, "calories": None}]
        totals = {"calories": None, "protein": None, "fat": None, "carbs": None}

    # Normalize totals to the DB schema (calories key)
    norm_totals = {
        "calories": totals.get("calories") or totals.get("kcal"),
        "protein": totals.get("protein") or totals.get("p"),
        "fats": totals.get("fats") or totals.get("fat") or totals.get("f"),
        "carbs": totals.get("carbs") or totals.get("c"),
        "fiber": totals.get("fiber") or totals.get("fib") or 0,
    }

    log = create_nutrition_log(
        db=db,
        user_id=user.telegram_id,
        date=record_date,
        meal_time=meal_time,
        meal_name=meal_name,
        items=items,
        totals=norm_totals,
    )

    return {
        "status": "ok",
        "meal_id": log.id,
        "date": record_date.isoformat(),
        "slot": req.slot or "auto",
        "meal_name": meal_name,
        "items_count": len(items),
        "totals": norm_totals,
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
        "garmin_email": user.garmin_email,
        "health_token": user.health_token,
        "timezone": getattr(user, "timezone", "Europe/Moscow"),
        "sex": getattr(user, "sex", None),
        "height_cm": getattr(user, "height_cm", None),
        "birth_date": user.birth_date.isoformat() if getattr(user, "birth_date", None) else None,
    }
