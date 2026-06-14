"""Profile API — BMR and user profile settings.

Three modes for BMR:
  • Garmin / Apple Health (auto): live from wearable; bot shows source badge.
  • Manual (Mifflin-St Jeor): user enters height / weight / age / sex / activity.
  • Default fallback: 2150 ккал when nothing else available.

Endpoints:
  GET   /api/profile/bmr      — resolved value + source + manual params for the form
  POST  /api/profile/bmr      — save manual override or switch back to auto
  PATCH /api/profile/timezone — update user timezone (called by WebApp on every open)
"""

from datetime import date as date_cls, datetime as dt_cls, timedelta
from typing import Optional, Literal

# All date/age math uses MSK (project is Moscow-only; server runs in UTC).
from core.infra.tz import MSK  # noqa: E402  (общая TZ проекта)


def _today_msk() -> date_cls:
    return dt_cls.now(MSK).date()


from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from webhook.tg_auth import get_tg_user

router = APIRouter()


# ── Mifflin-St Jeor + PAL ────────────────────────────────────────────────────

PAL_MULTIPLIERS = {
    "sedentary": 1.2,  # офис, минимум движения
    "light": 1.375,  # бытовая ходьба, без спорта
    "moderate": 1.55,  # 3–5 тренировок/неделя
    "high": 1.725,  # ежедневные тренировки
}


def mifflin_st_jeor(sex: str, weight_kg: float, height_cm: float, age: int) -> int:
    """Returns BMR in kcal/day. sex in {'male','female'}."""
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    return round(base + 5) if sex == "male" else round(base - 161)


# ── Schemas ──────────────────────────────────────────────────────────────────


class TimezonePayload(BaseModel):
    timezone: str


class BmrManualPayload(BaseModel):
    sex: Literal["male", "female"]
    height_cm: int
    weight_kg: float
    age: int
    activity_level: Literal["sedentary", "light", "moderate", "high"]


class BmrSettingsPayload(BaseModel):
    source: Literal["auto", "manual"]
    manual: Optional[BmrManualPayload] = None  # required if source == 'manual'


# ── GET ──────────────────────────────────────────────────────────────────────


@router.get("/api/profile/bmr")
async def get_bmr(tg_user: dict = Depends(get_tg_user)):
    """Returns current resolved BMR + the source + form prefill values."""
    from database import SessionLocal
    from database.crud import (
        get_user_by_telegram_id,
        get_user_settings,
        get_latest_weight,
        get_activities_by_period,
    )
    from core.health.caloric_budget import get_daily_budget

    user_id = tg_user.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="No user id in initData")

    db = SessionLocal()
    try:
        user = get_user_by_telegram_id(db, user_id)
        s = get_user_settings(db, user_id)

        # Resolved current values (from caloric_budget — same logic as mini-app banner)
        budget = get_daily_budget(user_id=user_id)
        resolved_source = budget.get("bmr_source") or "default"
        resolved_bmr = budget.get("bmr_avg")
        resolved_tdee = budget.get("tdee_avg")
        resolved_activity = budget.get("activity_avg")

        # What sources are *available* (for showing user's options)
        today = _today_msk()
        rows = get_activities_by_period(db, user_id, today - timedelta(days=14), today)
        garmin_available = any(r.source and "garmin" in r.source.lower() and r.total_calories for r in rows)
        apple_available = any(
            r.source
            and "apple" in r.source.lower()
            and (r.bmr_calories or (r.raw_data or {}).get("apple_basal_energy_kcal"))
            for r in rows
        )

        # Form prefill — use existing values, or sensible defaults from User profile
        latest_weight = get_latest_weight(db, user_id)
        weight_kg = latest_weight.weight if latest_weight else None
        height_cm = user.height_cm if user else None
        sex = user.sex if user else "male"
        age = None
        if user and user.birth_date:
            today_d = _today_msk()
            age = (
                today_d.year
                - user.birth_date.year
                - ((today_d.month, today_d.day) < (user.birth_date.month, user.birth_date.day))
            )
        activity_level = (s.activity_level if s else None) or "light"

        return {
            "selected_source": (s.bmr_source if s else "auto"),  # 'auto' | 'manual'
            "resolved": {
                "source": resolved_source,  # 'garmin' | 'apple_health' | 'manual' | 'default'
                "bmr": resolved_bmr,
                "activity": resolved_activity,
                "tdee": resolved_tdee,
            },
            "available": {
                "garmin": garmin_available,
                "apple_health": apple_available,
            },
            "manual": {
                "sex": sex,
                "height_cm": height_cm,
                "weight_kg": weight_kg,
                "age": age,
                "activity_level": activity_level,
                "bmr_override": s.bmr_override if s else None,
                "activity_avg_override": s.activity_avg_override if s else None,
            },
        }
    finally:
        db.close()


# ── POST ─────────────────────────────────────────────────────────────────────


@router.post("/api/profile/bmr")
async def set_bmr(payload: BmrSettingsPayload, tg_user: dict = Depends(get_tg_user)):
    """Save BMR source preference. For 'manual' — also save Mifflin-St Jeor params + result."""
    from database import SessionLocal
    from database.crud import upsert_user_settings, get_user_by_telegram_id

    user_id = tg_user.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="No user id in initData")

    db = SessionLocal()
    try:
        if payload.source == "auto":
            # Switch to auto: clear manual override (so caloric_budget falls back to wearables).
            upsert_user_settings(
                db,
                user_id=user_id,
                bmr_source="auto",
                bmr_override=None,
                activity_avg_override=None,
            )
            return {"status": "ok", "source": "auto"}

        # source == 'manual'
        if payload.manual is None:
            raise HTTPException(status_code=400, detail="manual params required when source='manual'")
        m = payload.manual

        # Persist sex/height/age in User table (canonical home for biometrics)
        user = get_user_by_telegram_id(db, user_id)
        if user:
            user.sex = m.sex
            user.height_cm = m.height_cm
            # Convert age → birth_date (approximate: Jan 1 of birth year)
            today_d = _today_msk()
            user.birth_date = date_cls(today_d.year - m.age, 1, 1)
            db.commit()

        bmr = mifflin_st_jeor(m.sex, m.weight_kg, m.height_cm, m.age)
        pal = PAL_MULTIPLIERS[m.activity_level]
        tdee = round(bmr * pal)
        activity_avg = tdee - bmr

        upsert_user_settings(
            db,
            user_id=user_id,
            bmr_source="manual",
            bmr_override=bmr,
            activity_avg_override=activity_avg,
            activity_level=m.activity_level,
        )

        return {
            "status": "ok",
            "source": "manual",
            "bmr": bmr,
            "tdee": tdee,
            "activity": activity_avg,
        }
    finally:
        db.close()


# ── PATCH /api/profile/timezone ──────────────────────────────────────────────


@router.patch("/api/profile/timezone", status_code=204)
async def patch_timezone(payload: TimezonePayload, tg_user: dict = Depends(get_tg_user)):
    """Called by WebApp on every open: updates users.timezone if the browser-detected value changed.

    Accepts any valid IANA timezone name (e.g. "Asia/Jerusalem", "Europe/Moscow").
    Returns 204 No Content — idempotent, safe to fire-and-forget from JS.
    """
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    from database import SessionLocal
    from database.crud import get_user_by_telegram_id

    user_id = tg_user.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="No user id in initData")

    try:
        ZoneInfo(payload.timezone)
    except (ZoneInfoNotFoundError, KeyError):
        raise HTTPException(status_code=400, detail=f"Unknown timezone: {payload.timezone!r}")

    db = SessionLocal()
    try:
        user = get_user_by_telegram_id(db, user_id)
        if user and user.timezone != payload.timezone:
            user.timezone = payload.timezone
            db.commit()
    finally:
        db.close()
