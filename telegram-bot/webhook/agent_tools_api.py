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
from typing import Any, Optional

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
        llm_result = analyze_message(text=req.text, user_id=user.telegram_id)
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

    Resolution order:
      1. Per-user KB at `kb_<telegram_id>.json` at repo root (any cohort) —
         synced from FamilyHealth/<user>/knowledge_base.json on demand.
      2. Owner-cohort fallback: legacy `knowledge_base.json` (Alex-only).
      3. Otherwise: returns null with source='kb-not-available'.
    """
    project_root = Path(__file__).resolve().parents[2]
    per_user_kb = project_root / f"kb_{user.telegram_id}.json"

    if per_user_kb.exists():
        kb_path = per_user_kb
        source = f"kb_{user.telegram_id}.json"
    elif user.cohort == "owner":
        kb_path = project_root / "knowledge_base.json"
        source = "knowledge_base.json"
    else:
        return {"key": key, "value": None, "source": "kb-not-available"}

    if not kb_path.exists():
        return {"key": key, "value": None, "source": "kb-not-found"}

    import json

    try:
        with open(kb_path, encoding="utf-8") as f:
            kb = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read {source}: {e}")

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

    return {"key": key, "value": value, "source": source}


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


@router.get("/recent_supplements")
async def recent_supplements(
    days: int = 30,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Recent supplement intake log with per-supplement aggregation.

    Reads from `supplements_log` (filled by aiogram bot when user logs
    "выпил магний" etc). Returns:
      - per-supplement: days_taken in period, total_intakes (multi-dose/day OK),
        last_taken_date, last_dosage seen
      - period stats: total log lines

    Default 30 days — typical regimen feedback window.
    """
    from sqlalchemy import text as sql_text

    days = max(1, min(days, 180))
    sql = sql_text(
        """
        SELECT supplement_name,
               COUNT(*)                          AS total_intakes,
               COUNT(DISTINCT date)              AS days_taken,
               MAX(date)                         AS last_date,
               (ARRAY_AGG(dosage ORDER BY date DESC, time DESC NULLS LAST))[1] AS last_dosage
        FROM supplements_log
        WHERE user_id = :uid
          AND date >= CURRENT_DATE - (:days || ' days')::interval
        GROUP BY supplement_name
        ORDER BY days_taken DESC, supplement_name
        """
    )
    rows = db.execute(sql, {"uid": user.telegram_id, "days": days}).fetchall()
    items = [
        {
            "supplement": r.supplement_name,
            "days_taken": r.days_taken,
            "total_intakes": r.total_intakes,
            "intakes_per_day_avg": round(r.total_intakes / r.days_taken, 2) if r.days_taken else 0,
            "adherence_pct": round(100 * r.days_taken / days, 1),
            "last_date": r.last_date.isoformat() if r.last_date else None,
            "last_dosage": r.last_dosage,
        }
        for r in rows
    ]
    return {
        "status": "ok",
        "period_days": days,
        "unique_supplements": len(items),
        "total_log_entries": sum(i["total_intakes"] for i in items),
        "items": items,
    }


@router.get("/recent_biomarkers")
async def recent_biomarkers(
    limit: int = 20,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Most recent blood tests (latest `limit`).

    Each row has test_date + test_type + values (jsonb dict of marker → value).
    Default raised to 20 so questions like "как менялся холестерин" cover
    ~1 year of history without follow-up calls.
    """
    from sqlalchemy import text as sql_text

    limit = max(1, min(limit, 100))
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


@router.get("/phenoage")
async def phenoage(
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Biological age via Levine 2018 (Aging Cell) PhenoAge formula.

    Requires 9 markers from blood_tests.values (latest available value per
    marker, scanning all of user's history). Plus chronological age from
    users.birth_date.

    Returns: bio_age, chronological_age, delta, markers with direction
    ('younger'/'older' vs NHANES median for ~48yo male) and freshness.
    """
    import math

    from sqlalchemy import text as sql_text

    # Required markers — keys in blood_tests.values JSONB.
    markers = ["albumin_g_l", "creatinine", "glucose", "hs_CRP", "lymphocytes", "MCV", "RDW_CV", "ALP", "WBC"]

    # Latest value per marker via DISTINCT ON jsonb_each_text scan.
    sql = sql_text(
        """
        SELECT DISTINCT ON (kv.key) kv.key, kv.value, bt.test_date
        FROM blood_tests bt, jsonb_each_text(bt.values) kv
        WHERE bt.user_id = :uid AND kv.key = ANY(:markers)
        ORDER BY kv.key, bt.test_date DESC
        """
    )
    rows = db.execute(sql, {"uid": user.telegram_id, "markers": markers}).fetchall()

    latest: dict[str, dict] = {}
    for row in rows:
        try:
            latest[row.key] = {"value": float(row.value), "date": row.test_date.isoformat()}
        except (TypeError, ValueError):
            pass  # non-numeric value (string label etc) — skip

    # Chronological age
    chrono_age = None
    if user.birth_date:
        today = date.today()
        chrono_age = (
            today.year
            - user.birth_date.year
            - ((today.month, today.day) < (user.birth_date.month, user.birth_date.day))
        )

    # NHANES median for ~48yo male, plus direction (higher_is_younger)
    nhanes = {
        "albumin_g_l": (42.0, True),  # g/L (4.2 g/dL)
        "creatinine": (92.8, False),  # µmol/L (1.05 mg/dL)
        "glucose": (5.3, False),  # mmol/L (95 mg/dL)
        "hs_CRP": (1.0, False),  # mg/L (ln(0.1) → 0)
        "lymphocytes": (28.0, True),  # %
        "MCV": (90.0, False),  # fL
        "RDW_CV": (13.8, False),  # %
        "ALP": (68.0, False),  # U/L
        "WBC": (6.7, False),  # ×10³/µL
    }

    today_date = date.today()
    marker_list: list[dict] = []
    younger_count = 0
    stale_markers: list[str] = []
    for key in markers:
        info = latest.get(key)
        if not info:
            marker_list.append({"name": key, "value": None, "direction": "unknown", "date": None})
            continue
        med, higher_younger = nhanes[key]
        v = info["value"]
        is_younger = (v > med) if higher_younger else (v < med)
        if is_younger:
            younger_count += 1
        days_ago = (today_date - date.fromisoformat(info["date"])).days
        stale = days_ago > 365
        if stale:
            stale_markers.append(f"{key} ({info['date']})")
        marker_list.append(
            {
                "name": key,
                "value": round(v, 3),
                "direction": "younger" if is_younger else "older",
                "date": info["date"],
                "days_ago": days_ago,
                "stale_over_year": stale,
            }
        )

    bio_age: Optional[float] = None
    error: Optional[str] = None
    if chrono_age is None:
        error = "users.birth_date not set"
    elif None in [latest.get(k, {}).get("value") for k in markers]:
        missing = [k for k in markers if k not in latest]
        error = f"missing markers: {missing}"
    elif latest["hs_CRP"]["value"] <= 0:
        error = "hs_CRP must be > 0 for ln()"
    else:
        try:
            # Levine 2018 formula
            alb_gL = latest["albumin_g_l"]["value"]  # already g/L
            creat_umolL = latest["creatinine"]["value"]  # already µmol/L
            gluc_mmolL = latest["glucose"]["value"]  # already mmol/L
            lncrp = math.log(latest["hs_CRP"]["value"] * 0.1)  # ln(CRP mg/dL)
            lymph_pct = latest["lymphocytes"]["value"]
            mcv = latest["MCV"]["value"]
            rdw = latest["RDW_CV"]["value"]
            alp = latest["ALP"]["value"]
            wbc = latest["WBC"]["value"]

            xb = (
                -19.907
                + 0.0804 * chrono_age
                + (-0.0336) * alb_gL
                + 0.0095 * creat_umolL
                + 0.1953 * gluc_mmolL
                + 0.0954 * lncrp
                + (-0.0120) * lymph_pct
                + 0.0268 * mcv
                + 0.3306 * rdw
                + (-0.00188) * alp
                + 0.0554 * wbc
            )
            mort = 1 - math.exp(-math.exp(xb) * (math.exp(0.0076927 * 120) - 1) / 0.0076927)
            if 0 < mort < 1:
                bio_age = round(141.50225 + math.log(-0.00553 * math.log(1 - mort)) / 0.090165, 1)
        except (ValueError, OverflowError) as e:
            error = f"calculation error: {e}"

    return {
        "status": "ok" if bio_age is not None else "incomplete",
        "bio_age": bio_age,
        "chronological_age": chrono_age,
        "delta_years": round(bio_age - chrono_age, 1) if bio_age and chrono_age else None,
        "interpretation": (
            "moложе паспорта"
            if bio_age and chrono_age and bio_age < chrono_age
            else "старше паспорта"
            if bio_age and chrono_age and bio_age > chrono_age
            else None
        ),
        "younger_markers_count": f"{younger_count}/9",
        "stale_markers": stale_markers,
        "error": error,
        "formula": "Levine 2018 (Aging Cell) — 9 biomarkers + chronological age",
        "markers": marker_list,
    }


@router.get("/recent_workouts")
async def recent_workouts(
    days: int = 30,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Workout summary by training-load canons (Seiler/Attia/Maffetone).

    Reads workouts_log_<user_id>.json from /app/telegram-bot/ (Garmin activity
    parser writes there). Returns Z2 min/week, HIIT min/week, A:C load ratio,
    polarized distribution, mistagged HIIT flag.

    Источник данных (приоритет):
    1. File `workouts_log_<user_id>.json` — rich data (Z2 zones, training load, MAF).
       Сейчас есть только у owner (Alex, push_workouts_to_container.py).
    2. Fallback: таблица `workouts` в БД — для остальных пользователей.
       Меньше полей (только type, duration, distance, calories), без zones/load,
       но достаточно для базовых вопросов «сколько раз бегал», «когда тренировался».
    """
    import json as _json
    from pathlib import Path as _Path
    from sqlalchemy import text as sql_text

    days = max(1, min(days, 180))
    today_date = date.today()
    cutoff = today_date - timedelta(days=days)

    wk_path = _Path(f"/app/telegram-bot/workouts_log_{user.telegram_id}.json")

    # ── Fallback: DB-based мульти-юзер (когда file отсутствует) ──────────────
    if not wk_path.exists():
        db_rows = db.execute(
            sql_text(
                """
                SELECT date, workout_type, duration_minutes, distance_km,
                       calories_burned, source, start_time
                FROM workouts
                WHERE user_id = :uid AND date >= :cutoff
                ORDER BY date DESC, start_time DESC NULLS LAST
                """
            ),
            {"uid": user.telegram_id, "cutoff": cutoff},
        ).fetchall()
        if not db_rows:
            return {"status": "no_data", "available": False, "reason": "no workouts in DB or file"}

        from collections import Counter as _Counter

        type_labels_ru = {
            "running": "бег",
            "walking": "ходьба",
            "strength_training": "силовая",
            "yoga": "йога",
            "cycling": "велосипед",
            "swimming": "плавание",
            "elliptical": "эллипс",
            "cardio": "кардио",
            "hiit": "HIIT",
            "fitness_equipment": "тренажёр",
            "other": "другое",
        }
        type_counts = _Counter(r.workout_type or "unknown" for r in db_rows)
        by_type = {type_labels_ru.get(t, t): {"count": c, "garmin_type": t} for t, c in type_counts.most_common()}

        # Extremes per type (по duration и distance)
        extremes_by_type: dict[str, Any] = {}
        for t in type_counts:
            of_type = [r for r in db_rows if (r.workout_type or "unknown") == t]
            with_dur = [r for r in of_type if r.duration_minutes]
            with_dist = [r for r in of_type if r.distance_km]
            longest_dur = max(with_dur, key=lambda r: r.duration_minutes) if with_dur else None
            longest_dist = max(with_dist, key=lambda r: r.distance_km) if with_dist else None
            extremes_by_type[type_labels_ru.get(t, t)] = {
                "count": len(of_type),
                "longest_by_duration": {
                    "date": longest_dur.date.isoformat(),
                    "duration_min": longest_dur.duration_minutes,
                    "distance_km": float(longest_dur.distance_km) if longest_dur.distance_km else None,
                }
                if longest_dur
                else None,
                "longest_by_distance": {
                    "date": longest_dist.date.isoformat(),
                    "distance_km": float(longest_dist.distance_km),
                    "duration_min": longest_dist.duration_minutes,
                }
                if longest_dist
                else None,
            }

        weeks = days / 7
        return {
            "status": "ok",
            "source": "db",
            "period_days": days,
            "count": len(db_rows),
            "by_type": by_type,
            "extremes_by_type": extremes_by_type,
            "stats": {
                "per_week": round(len(db_rows) / weeks, 1) if weeks else 0,
                "note": "DB-fallback: нет training_load/Z2/zones, только базовые поля",
            },
            "items": [
                {
                    "date": r.date.isoformat(),
                    "type": r.workout_type,
                    "type_ru": type_labels_ru.get(r.workout_type, r.workout_type),
                    "duration_min": r.duration_minutes,
                    "distance_km": float(r.distance_km) if r.distance_km else None,
                    "calories_burned": r.calories_burned,
                    "source": r.source,
                }
                for r in db_rows[:15]
            ],
        }

    try:
        wd = _json.loads(wk_path.read_text())
    except Exception as e:
        return {"status": "error", "error": f"parse failed: {e}"}

    workouts = wd.get("workouts", [])
    if not workouts:
        return {"status": "no_data", "available": False, "reason": "empty workouts array"}

    today_date = date.today()
    cutoff = today_date - timedelta(days=days)

    def _to_date(s: str):
        try:
            y, m, d = s.split("-")
            return date(int(y), int(m), int(d))
        except Exception:
            return None

    in_window = []
    for w in workouts:
        wd_date = _to_date(w.get("date", ""))
        if wd_date and cutoff <= wd_date <= today_date:
            in_window.append(w)

    if not in_window:
        return {
            "status": "ok",
            "period_days": days,
            "count": 0,
            "items": [],
            "stats": {"per_week": 0, "z2_min_per_week": 0, "hiit_min_per_week": 0},
        }

    # Aggregate zones (prefer MAF — longevity school — over Garmin hr_zones)
    def _zone_min(w, zone_key):
        zones = w.get("maf_zones") or w.get("hr_zones") or {}
        return zones.get(zone_key, 0) or 0

    weeks = days / 7
    z1_total = sum(_zone_min(w, "z1") for w in in_window)
    z2_total = sum(_zone_min(w, "z2") for w in in_window)
    z3_total = sum(_zone_min(w, "z3") for w in in_window)
    z4_total = sum(_zone_min(w, "z4") for w in in_window)
    z5_total = sum(_zone_min(w, "z5") for w in in_window)
    total_zone_min = z1_total + z2_total + z3_total + z4_total + z5_total

    # Acute vs Chronic load
    seven_ago = today_date - timedelta(days=7)
    acute = [w for w in in_window if _to_date(w["date"]) and _to_date(w["date"]) >= seven_ago]
    acute_load = sum(w.get("training_load") or 0 for w in acute)
    chronic_load_avg = sum(w.get("training_load") or 0 for w in in_window) / weeks if weeks > 0 else 0
    ac_ratio = round(acute_load / chronic_load_avg, 2) if chronic_load_avg > 0 else None

    # Type aggregation — count workouts by Garmin type.
    # IMPORTANT: type is the Garmin classification ('running', 'strength_training',
    # 'walking', 'yoga', ...). activity_name is the user-set route/session label
    # ('Москва - База', 'Гимнастика #3') and is NOT a reliable indicator of
    # exercise type — a session named 'Москва - База' may be running OR walking.
    # ALWAYS read `type` field for classification, not `activity_name`.
    from collections import Counter as _Counter

    type_counts = _Counter(w.get("type") or "unknown" for w in in_window)
    # Russian-friendly labels for the common types so the agent uses them
    type_labels_ru = {
        "running": "бег",
        "walking": "ходьба",
        "strength_training": "силовая",
        "yoga": "йога",
        "cycling": "велосипед",
        "swimming": "плавание",
        "elliptical": "эллипс",
        "cardio": "кардио",
        "hiit": "HIIT",
        "fitness_equipment": "тренажёр",
        "other": "другое",
    }
    by_type = {
        type_labels_ru.get(t, t): {
            "count": c,
            "garmin_type": t,
        }
        for t, c in type_counts.most_common()
    }

    # Extremes per type — рекорды по длительности и дистанции в окне.
    # Нужно потому что items[:15] обрезает выборку до самых свежих, и редкие
    # длинные сессии (марафонские пробежки раз в квартал) туда не попадают.
    # Без этого блока вопрос "самая длинная пробежка года" агенту неотвечаем.
    def _max_by(items, key):
        items = [w for w in items if w.get(key) is not None]
        return max(items, key=lambda w: w[key]) if items else None

    def _extreme_record(w):
        return {
            "date": w.get("date"),
            "name": w.get("activity_name"),
            "duration_min": w.get("duration_min"),
            "distance_km": w.get("distance_km"),
            "avg_hr": w.get("avg_hr"),
        }

    extremes_by_type = {}
    for t in type_counts:
        of_type = [w for w in in_window if (w.get("type") or "unknown") == t]
        longest_dur = _max_by(of_type, "duration_min")
        longest_dist = _max_by(of_type, "distance_km")
        extremes_by_type[type_labels_ru.get(t, t)] = {
            "count": len(of_type),
            "longest_by_duration": _extreme_record(longest_dur) if longest_dur else None,
            "longest_by_distance": _extreme_record(longest_dist) if longest_dist else None,
        }

    return {
        "status": "ok",
        "period_days": days,
        "count": len(in_window),
        "by_type": by_type,
        "extremes_by_type": extremes_by_type,
        "stats": {
            "per_week": round(len(in_window) / weeks, 1),
            "z2_min_per_week": round(z2_total / weeks),
            "hiit_min_per_week": round((z4_total + z5_total) / weeks),
            "z2_target_attia": 150,  # mins/week
            "hiit_target_norwegian": 16,  # mins/week (4x4)
            "ac_ratio": ac_ratio,
            "ac_sweet_spot": "0.8-1.3",
        },
        "zones_total_min": {
            "z1": round(z1_total),
            "z2": round(z2_total),
            "z3": round(z3_total),
            "z4": round(z4_total),
            "z5": round(z5_total),
        },
        "polarized_pct": {
            "low (z1+z2)": round(100 * (z1_total + z2_total) / total_zone_min, 1) if total_zone_min else 0,
            "mid (z3)": round(100 * z3_total / total_zone_min, 1) if total_zone_min else 0,
            "high (z4+z5)": round(100 * (z4_total + z5_total) / total_zone_min, 1) if total_zone_min else 0,
            "ideal_seiler": "80/5/15",
        },
        "items": [
            {
                "date": w.get("date"),
                "type": w.get("type"),  # GARMIN classification — primary
                "type_ru": type_labels_ru.get(w.get("type"), w.get("type")),
                "name": w.get("activity_name"),  # user-set route name (e.g. "Москва - База")
                "duration_min": w.get("duration_min"),
                "distance_km": w.get("distance_km"),
                "avg_hr": w.get("avg_hr"),
                "training_load": w.get("training_load"),
            }
            for w in sorted(in_window, key=lambda w: w.get("date", ""), reverse=True)[:15]
        ],
    }


@router.get("/weight_history")
async def weight_history(
    days: Optional[int] = None,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """История веса и состава тела (жир/мышцы/висцеральный жир).

    Источник: `weights` table — пишется HAE (Apple Health → Mi-весы), Zepp Life,
    Apple Health XML импортом. История с 2015 у долгих пользователей.

    Возвращает агрегаты, НЕ сырой список из сотен записей. Параметр `days`:
    - не задан → агрегат за всю историю (all-time extremes)
    - 7-365 → дополнительно агрегат в окне (для вопросов "как изменился за месяц")

    Поля extremes: запись со значением + дата. body_fat фильтруется > 5
    (нулевые значения = весы не смогли измерить, мусор).
    """
    from sqlalchemy import text as sql_text

    in_window = max(7, min(days, 365)) if days else None

    def _to_date_str(ts) -> Optional[str]:
        """Накласть .date().isoformat() на datetime, или вернуть str иначе.

        SQLAlchemy в SQLite (тесты) возвращает datetime, в Postgres — тоже.
        Старое SQL `measured_at::date AS date` ломалось на SQLite, поэтому теперь
        конвертация в Python.
        """
        if ts is None:
            return None
        if hasattr(ts, "date"):
            return ts.date().isoformat()
        return str(ts)[:10]

    # Latest weighing — current state, most useful single fact
    latest_row = db.execute(
        sql_text(
            """
            SELECT measured_at, weight, body_fat, muscle_mass,
                   visceral_fat, bmi, source
            FROM weights
            WHERE user_id = :uid
            ORDER BY measured_at DESC
            LIMIT 1
            """
        ),
        {"uid": user.telegram_id},
    ).fetchone()

    if not latest_row:
        return {"status": "no_data", "count": 0}

    latest = {
        "date": _to_date_str(latest_row.measured_at),
        "weight_kg": round(latest_row.weight, 1),
        "body_fat_pct": round(latest_row.body_fat, 1) if latest_row.body_fat else None,
        "muscle_mass_kg": round(latest_row.muscle_mass, 1) if latest_row.muscle_mass else None,
        "visceral_fat": latest_row.visceral_fat,
        "bmi": round(latest_row.bmi, 1) if latest_row.bmi else None,
        "source": latest_row.source,
    }

    def _extremes(where_clause: str, params: dict) -> dict:
        # Min/max weight (ignores body_fat NULL)
        w_min = db.execute(
            sql_text(
                f"SELECT measured_at, weight FROM weights "
                f"WHERE user_id = :uid {where_clause} ORDER BY weight ASC LIMIT 1"
            ),
            params,
        ).fetchone()
        w_max = db.execute(
            sql_text(
                f"SELECT measured_at, weight FROM weights "
                f"WHERE user_id = :uid {where_clause} ORDER BY weight DESC LIMIT 1"
            ),
            params,
        ).fetchone()
        # Min/max body_fat (filter > 5 — нулевые значения = весы не измерили)
        bf_min = db.execute(
            sql_text(
                f"SELECT measured_at, body_fat, weight FROM weights "
                f"WHERE user_id = :uid AND body_fat > 5 {where_clause} "
                f"ORDER BY body_fat ASC LIMIT 1"
            ),
            params,
        ).fetchone()
        bf_max = db.execute(
            sql_text(
                f"SELECT measured_at, body_fat, weight FROM weights "
                f"WHERE user_id = :uid AND body_fat > 5 {where_clause} "
                f"ORDER BY body_fat DESC LIMIT 1"
            ),
            params,
        ).fetchone()
        # Counts + date range
        meta = db.execute(
            sql_text(
                f"SELECT COUNT(*) AS n, MIN(measured_at) AS first, "
                f"MAX(measured_at) AS last FROM weights "
                f"WHERE user_id = :uid {where_clause}"
            ),
            params,
        ).fetchone()

        return {
            "count": meta.n,
            "first_date": _to_date_str(meta.first),
            "last_date": _to_date_str(meta.last),
            "min_weight": {"date": _to_date_str(w_min.measured_at), "weight_kg": round(w_min.weight, 1)}
            if w_min
            else None,
            "max_weight": {"date": _to_date_str(w_max.measured_at), "weight_kg": round(w_max.weight, 1)}
            if w_max
            else None,
            "min_body_fat": {
                "date": _to_date_str(bf_min.measured_at),
                "body_fat_pct": round(bf_min.body_fat, 1),
                "weight_kg": round(bf_min.weight, 1),
            }
            if bf_min
            else None,
            "max_body_fat": {
                "date": _to_date_str(bf_max.measured_at),
                "body_fat_pct": round(bf_max.body_fat, 1),
                "weight_kg": round(bf_max.weight, 1),
            }
            if bf_max
            else None,
        }

    result: dict[str, Any] = {
        "status": "ok",
        "latest": latest,
        "all_time": _extremes("", {"uid": user.telegram_id}),
    }

    if in_window:
        # Python-computed cutoff — works одинаково на Postgres и SQLite (тесты)
        cutoff = datetime.now(timezone.utc) - timedelta(days=in_window)
        result["window_days"] = in_window
        result["in_window"] = _extremes(
            "AND measured_at >= :cutoff",
            {"uid": user.telegram_id, "cutoff": cutoff},
        )

    return result


@router.get("/body_measurements")
async def body_measurements(
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Антропометрия: талия, шея, бёдра, грудь, бедро, бицепс (см).

    Источник: `body_measurements` table — ручной ввод пользователя через бот/админку.
    Талия — важная метрика метаболического здоровья (waist circumference > BMI
    по предсказанию ССЗ-риска, особенно для visceral fat).

    Возвращает latest замер, all-time min/max каждой метрики с датами, и
    тренд waist (last 6 measurements) — самая клинически релевантная.
    """
    from sqlalchemy import text as sql_text

    rows = db.execute(
        sql_text(
            """
            SELECT date, waist_cm, neck_cm, hips_cm, chest_cm, thigh_cm, biceps_cm, notes
            FROM body_measurements
            WHERE user_id = :uid
            ORDER BY date DESC
            """
        ),
        {"uid": user.telegram_id},
    ).fetchall()

    if not rows:
        return {"status": "no_data", "count": 0, "reason": "no body_measurements entries"}

    latest = rows[0]
    metrics = ["waist_cm", "neck_cm", "hips_cm", "chest_cm", "thigh_cm", "biceps_cm"]

    def _extremes(metric: str) -> dict | None:
        vals = [(r.date, getattr(r, metric)) for r in rows if getattr(r, metric) is not None]
        if not vals:
            return None
        min_v = min(vals, key=lambda x: x[1])
        max_v = max(vals, key=lambda x: x[1])
        return {
            "min": {"date": min_v[0].isoformat(), "value_cm": round(min_v[1], 1)},
            "max": {"date": max_v[0].isoformat(), "value_cm": round(max_v[1], 1)},
            "current_cm": round(getattr(latest, metric), 1) if getattr(latest, metric) is not None else None,
            "count": len(vals),
        }

    # Waist trend — last 6 measurements (for ratio/direction)
    waist_trend = [
        {"date": r.date.isoformat(), "waist_cm": round(r.waist_cm, 1)} for r in rows[:6] if r.waist_cm is not None
    ]

    return {
        "status": "ok",
        "count": len(rows),
        "latest": {
            "date": latest.date.isoformat(),
            **{m: round(getattr(latest, m), 1) if getattr(latest, m) is not None else None for m in metrics},
            "notes": latest.notes,
        },
        "extremes": {m: _extremes(m) for m in metrics},
        "waist_trend_last_6": waist_trend,
    }


@router.get("/day_summary")
async def day_summary(
    date: str,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Сводка за конкретный день: ккал, БЖУ, сон, вес, АД, был ли воркаут.

    Источник: `daily_summaries` table — агрегаты по дням, заполняется
    скриптами (nightly sync) из nutrition_log, activity_log, weights, BP.

    Используй для вопросов «что у меня было 14 марта», «как был день N»,
    «сравни такой-то день с другим».
    """
    from sqlalchemy import text as sql_text
    from datetime import date as date_cls

    try:
        target_date = date_cls.fromisoformat(date)
    except ValueError:
        return {"status": "error", "error": f"invalid date format: {date!r} (expected YYYY-MM-DD)"}

    try:
        row = db.execute(
            sql_text(
                """
                SELECT date, total_calories, total_protein, total_fats, total_carbs,
                       had_workout, sleep_hours, weight, bp_systolic, bp_diastolic
                FROM daily_summaries
                WHERE user_id = :uid AND date = :d
                """
            ),
            {"uid": user.telegram_id, "d": target_date},
        ).fetchone()
    except Exception as e:
        # daily_summaries отсутствует как ORM-модель — таблицу не создают на SQLite
        # (тестовая фикстура). На Postgres таблица есть. Если откат миграции —
        # возвращаем мягкий error вместо 500.
        logger.warning(f"day_summary query failed: {e}")
        return {"status": "error", "date": target_date.isoformat(), "error": "daily_summaries table not available"}

    if not row:
        return {"status": "no_data", "date": target_date.isoformat(), "reason": "no daily_summary for this date"}

    return {
        "status": "ok",
        "date": row.date.isoformat(),
        "nutrition": {
            "calories": row.total_calories,
            "protein_g": float(row.total_protein) if row.total_protein is not None else None,
            "fats_g": float(row.total_fats) if row.total_fats is not None else None,
            "carbs_g": float(row.total_carbs) if row.total_carbs is not None else None,
        },
        "activity": {
            "had_workout": row.had_workout,
        },
        "sleep_hours": float(row.sleep_hours) if row.sleep_hours is not None else None,
        "weight_kg": float(row.weight) if row.weight is not None else None,
        "blood_pressure": {
            "systolic": row.bp_systolic,
            "diastolic": row.bp_diastolic,
        }
        if row.bp_systolic
        else None,
    }


@router.get("/user_settings")
async def user_settings(
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Настройки пользователя: целевой вес, ежедневные добавки, BMR, цель калорий.

    Источник: `user_settings` table (per-user JSONB с регулярным режимом
    добавок) + поля из `users` (sex, height, birth_date, timezone, smoking_status).
    Используй для 'какие у меня цели', 'какие добавки я регулярно принимаю',
    'какой у меня дефицит калорий', 'когда у меня запланированы напоминания'.
    """
    from sqlalchemy import text as sql_text

    row = db.execute(
        sql_text(
            """
            SELECT show_calorie_budget_bar, bmr_override, target_weight_kg,
                   target_weight_date, supplement_reminders_enabled,
                   supplement_reminder_time, supplements, calorie_goal_pct,
                   bmr_source, activity_level, activity_avg_override
            FROM user_settings WHERE user_id = :uid
            """
        ),
        {"uid": user.telegram_id},
    ).fetchone()

    profile = {
        "first_name": user.first_name,
        "sex": user.sex,
        "height_cm": user.height_cm,
        "birth_date": user.birth_date.isoformat() if user.birth_date else None,
        "timezone": user.timezone,
        "cohort": user.cohort,
        "smoking_status": getattr(user, "smoking_status", None),
        "garmin_connected": bool(user.garmin_email),
    }

    if not row:
        return {"status": "no_settings", "profile": profile, "reason": "user_settings row not created yet"}

    return {
        "status": "ok",
        "profile": profile,
        "goals": {
            "target_weight_kg": row.target_weight_kg,
            "target_weight_date": row.target_weight_date.isoformat() if row.target_weight_date else None,
            "calorie_goal_pct": row.calorie_goal_pct,
        },
        "bmr": {
            "source": row.bmr_source,
            "override": row.bmr_override,
            "activity_level": row.activity_level,
            "activity_avg_override": row.activity_avg_override,
        },
        "supplements_regimen": row.supplements or [],
        "reminders": {
            "supplement_enabled": row.supplement_reminders_enabled,
            "supplement_time": row.supplement_reminder_time.isoformat() if row.supplement_reminder_time else None,
        },
    }


@router.get("/indoor_air")
async def indoor_air(
    days: int = 7,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Воздух в доме: CO2, температура, влажность, шум (Netatmo Healthy Home Coach).

    Источник: файлы `data/environment/netatmo_log.json` (текущий замер) +
    `netatmo_history.json` (история, дневные агрегаты). Owner-only — Netatmo
    есть только у Alex, у других пользователей не настроен.

    Используй для 'какой CO2 в спальне', 'духота сегодня', 'температура дома',
    'был ли проветрен'. CO2 >1000 ppm — плохо для сна и концентрации, >1400 — критично.
    """
    import json as _json
    import time as _time
    from pathlib import Path as _Path

    # Owner-only — у других пользователей датчиков нет
    if user.cohort != "owner":
        return {"status": "no_data", "reason": "Netatmo датчик только у owner"}

    log_path = _Path("/app/data/environment/netatmo_log.json")
    hist_path = _Path("/app/data/environment/netatmo_history.json")

    result: dict[str, Any] = {"status": "ok"}

    # Текущий замер
    if log_path.exists():
        try:
            log = _json.loads(log_path.read_text())
            if log and isinstance(log, list):
                latest = log[0]
                result["latest"] = {
                    "device_name": latest.get("device_name"),
                    "temperature_c": latest.get("temperature_c"),
                    "co2_ppm": latest.get("co2_ppm"),
                    "humidity_percent": latest.get("humidity_percent"),
                    "noise_db": latest.get("noise_db"),
                    "measured_at": datetime.fromtimestamp(latest["timestamp"], tz=timezone.utc).isoformat()
                    if latest.get("timestamp")
                    else None,
                }
        except Exception as e:
            logger.warning(f"indoor_air: failed to read log: {e}")

    # История за N дней (агрегаты)
    days = max(1, min(days, 60))
    if hist_path.exists():
        try:
            history = _json.loads(hist_path.read_text())
            cutoff_ts = int(_time.time()) - days * 24 * 3600
            rooms: dict[str, Any] = {}
            for room_name, room_data in history.items():
                if not isinstance(room_data, dict):
                    continue
                # room_data: {unix_ts: [temp, co2, humidity, noise]}
                points = []
                for ts_str, values in room_data.items():
                    try:
                        ts = int(ts_str)
                        if ts < cutoff_ts:
                            continue
                        if not isinstance(values, list) or len(values) < 4:
                            continue
                        points.append((ts, values))
                    except (ValueError, TypeError):
                        continue
                if not points:
                    continue
                temps = [p[1][0] for p in points if p[1][0] is not None]
                co2s = [p[1][1] for p in points if p[1][1] is not None]
                hums = [p[1][2] for p in points if p[1][2] is not None]
                noises = [p[1][3] for p in points if p[1][3] is not None]
                rooms[room_name] = {
                    "days_with_data": len(points),
                    "co2_avg_ppm": round(sum(co2s) / len(co2s)) if co2s else None,
                    "co2_max_ppm": round(max(co2s)) if co2s else None,
                    "temp_avg_c": round(sum(temps) / len(temps), 1) if temps else None,
                    "humidity_avg_pct": round(sum(hums) / len(hums), 1) if hums else None,
                    "noise_avg_db": round(sum(noises) / len(noises), 1) if noises else None,
                    "noise_max_db": round(max(noises)) if noises else None,
                }
            if rooms:
                result["history"] = {"period_days": days, "by_room": rooms}
        except Exception as e:
            logger.warning(f"indoor_air: failed to read history: {e}")

    if "latest" not in result and "history" not in result:
        return {"status": "no_data", "reason": "no Netatmo files on server"}

    return result


@router.get("/outdoor_weather")
async def outdoor_weather(
    date: Optional[str] = None,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Погода снаружи: температура, давление, влажность, UV, осадки (Open-Meteo, Москва).

    Источник: файл `data/weather/weather_history.json` (Open-Meteo daily aggregates).

    Без параметра date — последний доступный день. С date='YYYY-MM-DD' — конкретный день.
    Используй для 'какая погода', 'какое давление сегодня', 'был ли дождь вчера'.
    """
    import json as _json
    from pathlib import Path as _Path

    weather_path = _Path("/app/data/weather/weather_history.json")
    if not weather_path.exists():
        return {"status": "no_data", "reason": "weather_history.json не найден"}

    try:
        data = _json.loads(weather_path.read_text())
    except Exception as e:
        return {"status": "error", "error": f"parse failed: {e}"}

    entries = data.get("entries", [])
    if not entries:
        return {"status": "no_data", "reason": "empty entries"}

    if date:
        # Конкретный день
        matched = [e for e in entries if e.get("date") == date]
        if not matched:
            return {"status": "no_data", "date": date, "reason": f"нет записи на {date}"}
        e = matched[0]
    else:
        # Последний день
        e = max(entries, key=lambda x: x.get("date", ""))

    return {
        "status": "ok",
        "date": e.get("date"),
        "city": e.get("city"),
        "temp_max_c": e.get("temp_max"),
        "temp_min_c": e.get("temp_min"),
        "temp_mean_c": e.get("temp_mean"),
        "pressure_mmhg": e.get("pressure_mmhg"),
        "humidity_pct": e.get("humidity_pct"),
        "uv_index_max": e.get("uv_index_max"),
        "precipitation_mm": e.get("precipitation_mm"),
        "sunshine_hours": e.get("sunshine_hours"),
        "weather": e.get("weather"),
    }


@router.get("/recent_trends")
async def recent_trends(
    days: int = 14,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Per-day trends from activity_log.raw_data: HRV, Body Battery, Stress, Steps.

    Complementary to get_dashboard_summary (which gives 7-day AVG only).
    Use this for trend questions: 'падает ли мой HRV?', 'сколько у меня
    Body Battery утром', 'когда самый высокий стресс'.
    """
    from sqlalchemy import text as sql_text

    days = max(1, min(days, 90))
    sql = sql_text(
        """
        SELECT date,
               steps,
               heart_rate_avg AS rhr,
               hrv,
               stress_level,
               sleep_hours,
               (raw_data->>'bodyBatteryHighestValue')::int  AS body_battery_max,
               (raw_data->>'bodyBatteryAtWakeTime')::int    AS body_battery_wake,
               (raw_data->>'bodyBatteryLowestValue')::int   AS body_battery_min,
               (raw_data->>'averageStressLevel')::int       AS stress_avg
        FROM activity_log
        WHERE user_id = :uid
          AND date >= CURRENT_DATE - (:days || ' days')::interval
        ORDER BY date DESC
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
        },
        "items": items[:30],
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
