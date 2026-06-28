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
from config.settings import public_base_url

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


# ── GET /api/dashboard_url ───────────────────────────────────────────────────


def _public_base() -> str:
    """Базовый публичный URL дашборда (без хвостового слэша).

    Тонкая обёртка над единым `config.settings.public_base_url` (#114, #205) —
    источник один для всех билдеров публичных ссылок.
    """
    return public_base_url()


@router.get("/api/dashboard_url")
async def get_dashboard_url(tg_user: dict = Depends(get_tg_user)):
    """Единый дашборд-эндпоинт mini-app (#114): отдаёт `{token, dashboard_url}`.

    - `token` → mini-app встраивает дашборд `/mc/{token}` в iframe (вкладка «Здоровье»).
    - `dashboard_url` → абсолютная ссылка (Настройки: открыть/скопировать, поделиться).

    Идемпотентен: переиспользует share_token юзера или создаёт при первом вызове
    (тот же токен, что у /share). No-user (mini-app открыт до /start) → оба null.
    Заменил дублирующий /api/profile/links.
    """
    from database import SessionLocal
    from database.crud import generate_share_token

    user_id = tg_user.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="No user id in initData")

    db = SessionLocal()
    try:
        token = generate_share_token(db, user_id)
        from services.report_generator import get_report_token

        report_token = get_report_token(db, user_id)
    except ValueError:
        return {"token": None, "dashboard_url": None, "report_url": None}  # юзера ещё нет
    finally:
        db.close()

    base = _public_base()
    report_url = f"{base}/r/{report_token}" if report_token else None
    return {
        "token": token,
        "dashboard_url": f"{base}/mc/{token}",
        "report_url": report_url,
    }


# ── Data Sources ─────────────────────────────────────────────────────────────

_DATA_SOURCES_META = [
    {"id": "garmin", "name": "Garmin", "icon": "⌚"},
    {"id": "apple_health", "name": "Apple Health", "icon": "🍎"},
    {"id": "health_connect", "name": "Google Health Connect", "icon": "🤖"},
    {"id": "zepp", "name": "Zepp / Mi Scale", "icon": "⚖️"},
    {"id": "netatmo", "name": "Netatmo", "icon": "🌡️"},
    {"id": "cgm", "name": "LibreLink (CGM)", "icon": "🩸"},
]

_CONNECT_INFO: dict[str, dict] = {
    "garmin": {"flow": "coming_soon"},
    "apple_health": {"flow": "inline_token"},
    "health_connect": {"flow": "inline_token"},
    "zepp": {"flow": "coming_soon"},
    "netatmo": {"flow": "coming_soon"},
    "cgm": {
        "flow": "tg_deeplink",
        "deeplink": "tg://resolve?domain=Botkin_md_bot&start=connect_cgm",
    },
}


@router.get("/api/profile/data_sources")
async def get_data_sources(tg_user: dict = Depends(get_tg_user)):
    """Статус подключения источников данных для текущего пользователя.

    Возвращает список: id, name, icon, connected, last_updated, connect_info.
    connect_info.flow: 'inline_token' | 'tg_deeplink' | 'coming_soon'
    connect_info.health_token: только для inline_token + connected=False
    """
    import json as _json
    from pathlib import Path as _Path
    from datetime import datetime as _dt
    from database import SessionLocal
    from sqlalchemy import text

    user_id = tg_user.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="No user id in initData")

    cutoff_30 = _today_msk() - timedelta(days=30)
    cutoff_14 = _today_msk() - timedelta(days=14)
    cutoff_7 = _today_msk() - timedelta(days=7)

    health_token: str | None = None
    db = SessionLocal()
    try:

        def _scalar(sql: str, params: dict):
            row = db.execute(text(sql), params).fetchone()
            return row[0] if row and row[0] else None

        garmin_last = _scalar(
            "SELECT MAX(date) FROM activity_log WHERE user_id=:uid AND LOWER(source) LIKE 'garmin%' AND date >= :cutoff",
            {"uid": user_id, "cutoff": cutoff_30},
        )
        apple_last = _scalar(
            "SELECT MAX(date) FROM activity_log WHERE user_id=:uid AND LOWER(source) LIKE 'apple%' AND date >= :cutoff",
            {"uid": user_id, "cutoff": cutoff_30},
        )
        health_connect_last = _scalar(
            "SELECT MAX(date) FROM activity_log WHERE user_id=:uid AND LOWER(source) LIKE 'health_connect%' AND date >= :cutoff",
            {"uid": user_id, "cutoff": cutoff_30},
        )
        zepp_last = _scalar(
            "SELECT DATE(MAX(measured_at)) FROM weights WHERE user_id=:uid AND LOWER(source) LIKE 'zepp%' AND measured_at >= :cutoff",
            {"uid": user_id, "cutoff": cutoff_30},
        )
        cgm_last = _scalar(
            "SELECT DATE(MAX(ts)) FROM glucose_readings WHERE user_id=:uid AND ts >= :cutoff",
            {"uid": user_id, "cutoff": cutoff_14},
        )

        # health_token нужен только для inline_token-источников, только когда не подключены.
        # Проверяем здесь по DB-результатам (netatmo — file-based, flow="coming_soon", не inline_token).
        db_last_by_id = {
            "garmin": garmin_last,
            "apple_health": apple_last,
            "health_connect": health_connect_last,
            "zepp": zepp_last,
            "cgm": cgm_last,
        }
        needs_token = any(
            _CONNECT_INFO[meta["id"]]["flow"] == "inline_token" and not bool(db_last_by_id.get(meta["id"]))
            for meta in _DATA_SOURCES_META
        )
        if needs_token:
            import logging

            from database.crud import get_or_create_health_token

            try:
                health_token = get_or_create_health_token(db, user_id)
            except Exception:
                logging.getLogger(__name__).warning(
                    "get_or_create_health_token failed for user %s", user_id, exc_info=True
                )
    finally:
        db.close()

    # Netatmo — файловый источник, не привязан к user_id
    netatmo_last = None
    netatmo_path = _Path("/app/data/environment/netatmo_log.json")
    if netatmo_path.exists():
        try:
            data = _json.loads(netatmo_path.read_text())
            ts = data.get("timestamp") or data.get("time")
            if ts:
                parsed = _dt.fromisoformat(str(ts).replace("Z", "+00:00")).date()
                if parsed >= cutoff_7:
                    netatmo_last = parsed
        except Exception:
            pass

    last_by_id = {
        "garmin": garmin_last,
        "apple_health": apple_last,
        "health_connect": health_connect_last,
        "zepp": zepp_last,
        "netatmo": netatmo_last,
        "cgm": cgm_last,
    }

    sources = []
    for meta in _DATA_SOURCES_META:
        src_id = meta["id"]
        connected = bool(last_by_id[src_id])
        info = dict(_CONNECT_INFO[src_id])  # shallow copy

        # Добавить токен только если: flow=inline_token AND не подключён
        if info["flow"] == "inline_token":
            info["health_token"] = health_token if not connected else None

        sources.append(
            {
                **meta,
                "connected": connected,
                "last_updated": str(last_by_id[src_id]) if last_by_id[src_id] else None,
                "connect_info": info,
            }
        )

    return {"sources": sources}
