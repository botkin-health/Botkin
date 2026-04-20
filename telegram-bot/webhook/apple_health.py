"""
Apple Health Webhook — принимает данные от iPhone Shortcuts.
Запускается параллельно с Telegram-ботом на порту 8080.
Данные пишутся в PostgreSQL в те же таблицы что и Garmin/Zepp.

Endpoint: POST https://health.orangegate.cc/apple_health
Auth: Bearer token (APPLE_HEALTH_TOKEN из .env)
"""

import os
import logging
from datetime import date, datetime
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel, Field
import uvicorn

logger = logging.getLogger(__name__)

app = FastAPI(title="HealthVault Apple Health Webhook", docs_url=None, redoc_url=None)

APPLE_HEALTH_TOKEN = os.getenv("APPLE_HEALTH_TOKEN", "")
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN", "")
PRIMARY_USER_ID = int(os.getenv("TELEGRAM_USER_ID", "895655"))


# ── Telegram WebApp Auth ──────────────────────────────────────────────────────

from webhook.tg_auth import get_tg_user, verify_telegram_init_data  # noqa: F401


# ── Auth ──────────────────────────────────────────────────────────────────────


def verify_token(authorization: str = Header(...)):
    """Bearer token auth."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if not APPLE_HEALTH_TOKEN or token != APPLE_HEALTH_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")
    return token


# ── Request schema ────────────────────────────────────────────────────────────


class AppleHealthPayload(BaseModel):
    """
    Данные за один день от iPhone Shortcuts.
    Все поля опциональны — Shortcut присылает только то что есть.
    """

    date: str = Field(..., description="YYYY-MM-DD, обычно вчерашняя дата")

    # Активность
    steps: Optional[int] = None
    distance_walking_km: Optional[float] = None
    flights_climbed: Optional[int] = None
    active_energy_kcal: Optional[float] = None

    # Пульс
    resting_heart_rate: Optional[int] = None
    heart_rate_min: Optional[int] = None
    heart_rate_max: Optional[int] = None
    heart_rate_avg: Optional[int] = None

    # Давление (последнее измерение дня)
    blood_pressure_systolic: Optional[int] = None
    blood_pressure_diastolic: Optional[int] = None

    # Ходьба / Gait
    walking_speed_km_h: Optional[float] = None
    walking_step_length_cm: Optional[float] = None
    walking_double_support_pct: Optional[float] = None
    walking_asymmetry_pct: Optional[float] = None

    # Состав тела (от Zepp через Apple Health)
    weight_kg: Optional[float] = None
    body_fat_pct: Optional[float] = None
    muscle_mass_kg: Optional[float] = None
    water_pct: Optional[float] = None

    # Дополнительно
    vo2_max: Optional[float] = None
    respiratory_rate: Optional[float] = None
    wrist_temperature: Optional[float] = None


# ── Endpoint ──────────────────────────────────────────────────────────────────


@app.get("/health")
async def health_check():
    """Liveness probe для мониторинга."""
    return {"status": "ok", "service": "apple_health_webhook"}


@app.post("/apple_health")
async def receive_apple_health(
    payload: AppleHealthPayload,
    _token: str = Depends(verify_token),
):
    """
    Принимает JSON от iPhone Shortcuts и пишет в БД.
    Возвращает summary что было сохранено.
    """
    try:
        record_date = date.fromisoformat(payload.date)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {payload.date!r}. Use YYYY-MM-DD.")

    saved = []

    try:
        # Импортируем здесь чтобы не ломать импорт если БД недоступна при старте
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

        from database import SessionLocal
        from database.crud import create_or_update_activity, create_weight

        db = SessionLocal()
        try:
            # ── 1. activity_log (шаги, пульс, дистанция, калории) ───────────
            heart_rate = payload.resting_heart_rate or payload.heart_rate_avg

            # Gait и дополнительные метрики идут в raw_data
            raw = {}
            if payload.walking_speed_km_h is not None:
                raw["walking_speed_km_h"] = payload.walking_speed_km_h
            if payload.walking_step_length_cm is not None:
                raw["walking_step_length_cm"] = payload.walking_step_length_cm
            if payload.walking_double_support_pct is not None:
                raw["walking_double_support_pct"] = payload.walking_double_support_pct
            if payload.walking_asymmetry_pct is not None:
                raw["walking_asymmetry_pct"] = payload.walking_asymmetry_pct
            if payload.flights_climbed is not None:
                raw["flights_climbed"] = payload.flights_climbed
            if payload.heart_rate_min is not None:
                raw["heart_rate_min"] = payload.heart_rate_min
            if payload.heart_rate_max is not None:
                raw["heart_rate_max"] = payload.heart_rate_max
            if payload.blood_pressure_systolic is not None:
                raw["blood_pressure_systolic"] = payload.blood_pressure_systolic
            if payload.blood_pressure_diastolic is not None:
                raw["blood_pressure_diastolic"] = payload.blood_pressure_diastolic
            if payload.vo2_max is not None:
                raw["vo2_max"] = payload.vo2_max
            if payload.respiratory_rate is not None:
                raw["respiratory_rate"] = payload.respiratory_rate
            if payload.wrist_temperature is not None:
                raw["wrist_temperature"] = payload.wrist_temperature

            activity = create_or_update_activity(
                db=db,
                user_id=PRIMARY_USER_ID,
                date=record_date,
                steps=payload.steps,
                active_calories=payload.active_energy_kcal,
                distance_km=payload.distance_walking_km,
                heart_rate_avg=heart_rate,
                source="apple_health_shortcut",
                raw_data=raw if raw else None,
            )
            saved.append(f"activity_log: steps={payload.steps}, HR={heart_rate}, dist={payload.distance_walking_km}km")

            # ── 2. weights (если пришёл вес от Zepp через Apple Health) ─────
            if payload.weight_kg and payload.weight_kg > 30:
                weight_entry = create_weight(
                    db=db,
                    user_id=PRIMARY_USER_ID,
                    date=record_date,
                    weight=payload.weight_kg,
                    body_fat=payload.body_fat_pct,
                    muscle_mass=payload.muscle_mass_kg,
                    water=payload.water_pct,
                    source="apple_health_shortcut",
                )
                saved.append(f"weights: {payload.weight_kg}kg, fat={payload.body_fat_pct}%")

            db.commit()

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Apple Health webhook error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

    logger.info(f"✅ Apple Health import [{payload.date}]: {'; '.join(saved)}")

    return {
        "status": "ok",
        "date": payload.date,
        "saved": saved,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ── Standalone run (для локального тестирования) ──────────────────────────────

# ── Settings API ─────────────────────────────────────────────────────────────


class SupplementItem(BaseModel):
    name: str
    slot: str  # morning_before | morning_with | evening


class UserSettingsSchema(BaseModel):
    show_calorie_budget_bar: bool = True
    bmr_override: Optional[int] = None
    target_weight_kg: Optional[float] = None
    target_weight_date: Optional[str] = None  # YYYY-MM-DD string
    supplement_reminders_enabled: bool = False
    supplement_reminder_time: str = "08:00"  # HH:MM string
    supplements: List[SupplementItem] = []


@app.get("/api/settings")
async def get_settings(tg_user: dict = Depends(get_tg_user)):
    """Return current settings for authenticated Telegram user."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

    from database import SessionLocal
    from database.crud import get_user_settings
    from core.health.supplements import DEFAULT_SUPPLEMENTS

    user_id = tg_user.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="No user id in initData")

    db = SessionLocal()
    try:
        s = get_user_settings(db, user_id)
        if s is None:
            return {
                "show_calorie_budget_bar": True,
                "bmr_override": None,
                "target_weight_kg": None,
                "target_weight_date": None,
                "supplement_reminders_enabled": False,
                "supplement_reminder_time": "08:00",
                "supplements": DEFAULT_SUPPLEMENTS,
            }
        return {
            "show_calorie_budget_bar": s.show_calorie_budget_bar,
            "bmr_override": s.bmr_override,
            "target_weight_kg": s.target_weight_kg,
            "target_weight_date": s.target_weight_date.isoformat() if s.target_weight_date else None,
            "supplement_reminders_enabled": s.supplement_reminders_enabled,
            "supplement_reminder_time": s.supplement_reminder_time.strftime("%H:%M")
            if s.supplement_reminder_time
            else "08:00",
            "supplements": s.supplements or [],
        }
    finally:
        db.close()


@app.post("/api/settings")
async def save_settings(payload: UserSettingsSchema, tg_user: dict = Depends(get_tg_user)):
    """Save settings for authenticated Telegram user."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

    from database import SessionLocal
    from database.crud import upsert_user_settings
    from datetime import date as date_cls, time as time_cls

    user_id = tg_user.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="No user id in initData")

    twd = None
    if payload.target_weight_date:
        try:
            twd = date_cls.fromisoformat(payload.target_weight_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid target_weight_date format, use YYYY-MM-DD")

    try:
        h, m = payload.supplement_reminder_time.split(":")
        reminder_time = time_cls(int(h), int(m))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid supplement_reminder_time, use HH:MM")

    supplements_list = [s.model_dump() for s in payload.supplements]

    db = SessionLocal()
    try:
        upsert_user_settings(
            db,
            user_id=user_id,
            show_calorie_budget_bar=payload.show_calorie_budget_bar,
            bmr_override=payload.bmr_override,
            target_weight_kg=payload.target_weight_kg,
            target_weight_date=twd,
            supplement_reminders_enabled=payload.supplement_reminders_enabled,
            supplement_reminder_time=reminder_time,
            supplements=supplements_list,
        )
    finally:
        db.close()

    return {"status": "ok"}


# ── Nutrition day editor API ─────────────────────────────────────────────────

from webhook.nutrition_api import router as nutrition_router
from webhook.supplements_api import router as supplements_router

app.include_router(nutrition_router)
app.include_router(supplements_router)


# ── Static webapp ─────────────────────────────────────────────────────────────

import hashlib
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path as _Path

_webapp_dir = _Path(__file__).parent.parent / "webapp"


def _webapp_version() -> str:
    """Short hash of mtimes for day.js + api.js + day.css — forces cache bust on any change."""
    parts = []
    for fname in ("day.js", "api.js", "day.css"):
        p = _webapp_dir / fname
        if p.exists():
            parts.append(str(p.stat().st_mtime_ns))
    return hashlib.md5("-".join(parts).encode()).hexdigest()[:8] if parts else "0"


async def _serve_index() -> HTMLResponse:
    """Serve index.html with {{V}} placeholder replaced by version hash."""
    index_path = _webapp_dir / "index.html"
    html = index_path.read_text(encoding="utf-8")
    html = html.replace("{{V}}", _webapp_version())
    # Prevent CDN/browser from caching the HTML itself — JS/CSS get cached via ?v=hash
    headers = {"Cache-Control": "no-cache, no-store, must-revalidate"}
    return HTMLResponse(content=html, headers=headers)


if _webapp_dir.exists():
    # Explicit routes for index — must be registered BEFORE the mount.
    app.get("/webapp/")(_serve_index)
    app.get("/webapp/index.html")(_serve_index)
    # Everything else (day.js, api.js, day.css, etc.) served as static.
    app.mount("/webapp", StaticFiles(directory=str(_webapp_dir), html=True), name="webapp")


def start_webhook_server(host: str = "0.0.0.0", port: int = 8081):
    """Запускается из bot.py через asyncio.gather."""
    config = uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    return server.serve()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8081)
