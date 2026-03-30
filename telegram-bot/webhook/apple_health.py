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
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import uvicorn

logger = logging.getLogger(__name__)

app = FastAPI(title="HealthVault Apple Health Webhook", docs_url=None, redoc_url=None)

APPLE_HEALTH_TOKEN = os.getenv("APPLE_HEALTH_TOKEN", "")
PRIMARY_USER_ID = int(os.getenv("TELEGRAM_USER_ID", "895655"))


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

def start_webhook_server(host: str = "0.0.0.0", port: int = 8081):
    """Запускается из bot.py через asyncio.gather."""
    config = uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    return server.serve()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8081)
