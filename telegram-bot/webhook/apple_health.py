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

from fastapi import FastAPI, HTTPException, Depends, Header, Request
from pydantic import BaseModel, Field
import uvicorn

logger = logging.getLogger(__name__)

app = FastAPI(title="HealthVault Apple Health Webhook", docs_url=None, redoc_url=None)

APPLE_HEALTH_TOKEN = os.getenv("APPLE_HEALTH_TOKEN", "")
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN", "")
# Fallback user for backward compat (single-user setup).
# In multi-user setup each user has their own health_token in users.health_token.
_target_user_id = int(os.getenv("TELEGRAM_USER_ID", "895655"))


# ── Telegram WebApp Auth ──────────────────────────────────────────────────────

from webhook.tg_auth import get_tg_user, verify_telegram_init_data  # noqa: F401


# ── Auth ──────────────────────────────────────────────────────────────────────


def verify_token(authorization: str = Header(...)):
    """Bearer token auth.

    Returns the raw token string so the endpoint can resolve which user sent the data.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=403, detail="Invalid token")
    # Accept either the global APPLE_HEALTH_TOKEN (backward compat / single-user)
    # OR any per-user token stored in users.health_token (multi-user).
    # Actual user resolution happens in the endpoint after DB lookup.
    if APPLE_HEALTH_TOKEN and token == APPLE_HEALTH_TOKEN:
        return token  # global token — will resolve to _target_user_id
    # Per-user tokens are validated inside the endpoint against the DB.
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
    basal_energy_kcal: Optional[float] = None  # Apple's RMR — used as BMR for non-Garmin users

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
    bearer_token: str = Depends(verify_token),
):
    """
    Принимает JSON от iPhone Shortcuts и пишет в БД.

    Роутинг пользователя:
    - Если bearer == APPLE_HEALTH_TOKEN (global) → _target_user_id (backward compat)
    - Иначе → ищем по users.health_token → получаем user_id из БД
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
        from database.crud import (
            create_or_update_activity,
            create_weight,
            get_user_by_health_token,
            get_activity_by_date,
        )

        # ── Resolve user ──────────────────────────────────────────────────────
        if APPLE_HEALTH_TOKEN and bearer_token == APPLE_HEALTH_TOKEN:
            target_user_id = _target_user_id
        else:
            # Per-user token: look up in DB
            _db_auth = SessionLocal()
            try:
                _user = get_user_by_health_token(_db_auth, bearer_token)
            finally:
                _db_auth.close()
            if not _user:
                raise HTTPException(status_code=403, detail="Unknown token")
            target_user_id = _user.telegram_id

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
            # NOTE: blood_pressure_systolic/diastolic НЕ идут в raw_data —
            # они пишутся только в blood_pressure_logs (см. ниже).
            if payload.vo2_max is not None:
                raw["vo2_max"] = payload.vo2_max
            if payload.respiratory_rate is not None:
                raw["respiratory_rate"] = payload.respiratory_rate
            if payload.wrist_temperature is not None:
                raw["wrist_temperature"] = payload.wrist_temperature

            # NOTE: do NOT pass active_calories — Apple Health's "active energy" is
            # computed differently than Garmin's and breaks the (total = bmr + active)
            # invariant. Garmin remains the source of truth for the calories triple.
            # Apple's value is preserved in raw_data for archival.
            if payload.active_energy_kcal is not None:
                raw = raw or {}
                raw["apple_active_energy_kcal"] = payload.active_energy_kcal
            if payload.basal_energy_kcal is not None:
                raw = raw or {}
                raw["apple_basal_energy_kcal"] = payload.basal_energy_kcal
            # BMR (basal): write to bmr_calories ONLY if not yet set (Garmin > Apple priority).
            # If Garmin already populated this row, do not overwrite.
            existing_row = get_activity_by_date(db, target_user_id, record_date)
            apple_bmr_for_db = (
                payload.basal_energy_kcal
                if (
                    payload.basal_energy_kcal is not None
                    and (existing_row is None or existing_row.bmr_calories is None)
                )
                else None
            )
            activity = create_or_update_activity(
                db=db,
                user_id=target_user_id,
                date=record_date,
                steps=payload.steps,
                bmr_calories=apple_bmr_for_db,
                distance_km=payload.distance_walking_km,
                heart_rate_avg=heart_rate,
                source="apple_health_shortcut",
                raw_data=raw if raw else None,
            )
            saved.append(f"activity_log: steps={payload.steps}, HR={heart_rate}, dist={payload.distance_walking_km}km")

            # ── 2. blood_pressure_logs (BP в отдельную таблицу — не затирается Garmin) ──
            if payload.blood_pressure_systolic and payload.blood_pressure_diastolic:
                from sqlalchemy import text as _text

                measured_at = datetime.combine(record_date, datetime.min.time().replace(hour=8))
                db.execute(
                    _text(
                        """INSERT INTO blood_pressure_logs
                           (user_id, measured_at, systolic, diastolic, heart_rate, source)
                           VALUES (:uid, :ts, :sys, :dia, :hr, 'apple_health_shortcut')
                           ON CONFLICT (user_id, measured_at) DO UPDATE
                             SET systolic = EXCLUDED.systolic,
                                 diastolic = EXCLUDED.diastolic"""
                    ),
                    {
                        "uid": target_user_id,
                        "ts": measured_at,
                        "sys": payload.blood_pressure_systolic,
                        "dia": payload.blood_pressure_diastolic,
                        "hr": heart_rate,
                    },
                )
                saved.append(f"blood_pressure: {payload.blood_pressure_systolic}/{payload.blood_pressure_diastolic}")

            # ── 3. weights (если пришёл вес от Zepp через Apple Health) ─────
            if payload.weight_kg and payload.weight_kg > 30:
                weight_entry = create_weight(
                    db=db,
                    user_id=target_user_id,
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


# ── /apple_health_v2 — приёмник нативного формата Health Auto Export ─────────
#
# HAE присылает вложенную структуру:
#   {"data": {"metrics": [
#       {"name": "step_count", "units": "count",
#        "data": [{"date": "2026-05-01 00:00:00 +0300", "qty": 12345}]},
#       {"name": "heart_rate", "units": "count/min",
#        "data": [{"date": "...", "Avg": 72, "Min": 55, "Max": 130}]},
#       ...
#   ]}}
# Адаптер группирует записи по датам и переиспользует ту же логику записи в БД.


def _hae_pick(rec: dict, *keys, default=None):
    """Достать первое не-None поле из записи (qty / Avg / Min / Max)."""
    for k in keys:
        if k in rec and rec[k] is not None:
            return rec[k]
    return default


def _hae_to_daily_payloads(metrics: list[dict]) -> dict[str, AppleHealthPayload]:
    """Сгруппировать HAE metrics → {YYYY-MM-DD: AppleHealthPayload}."""
    by_date: dict[str, dict] = {}

    for m in metrics:
        name = (m.get("name") or "").lower()
        units = (m.get("units") or "").lower()
        for rec in m.get("data") or []:
            d = (rec.get("date") or "")[:10]
            if not d or len(d) != 10 or d[4] != "-":
                continue
            slot = by_date.setdefault(d, {"date": d})

            if name == "step_count":
                slot["steps"] = int(_hae_pick(rec, "qty", "Avg", default=0))
            elif name in ("walking_running_distance", "walking_distance", "distance_walking_running"):
                qty = float(_hae_pick(rec, "qty", "Avg", default=0))
                if units == "m":
                    qty /= 1000
                elif units == "mi":
                    qty *= 1.60934
                slot["distance_walking_km"] = round(qty, 3)
            elif name == "flights_climbed":
                slot["flights_climbed"] = int(_hae_pick(rec, "qty", "Avg", default=0))
            elif name in ("active_energy", "active_energy_burned"):
                slot["active_energy_kcal"] = float(_hae_pick(rec, "qty", "Avg", default=0))
            elif name in ("basal_energy_burned", "resting_energy"):
                slot["basal_energy_kcal"] = float(_hae_pick(rec, "qty", "Avg", default=0))
            elif name == "heart_rate":
                if "Avg" in rec and rec["Avg"] is not None:
                    slot["heart_rate_avg"] = int(round(float(rec["Avg"])))
                if "Min" in rec and rec["Min"] is not None:
                    slot["heart_rate_min"] = int(round(float(rec["Min"])))
                if "Max" in rec and rec["Max"] is not None:
                    slot["heart_rate_max"] = int(round(float(rec["Max"])))
                if "qty" in rec and rec["qty"] is not None and "heart_rate_avg" not in slot:
                    slot["heart_rate_avg"] = int(round(float(rec["qty"])))
            elif name == "resting_heart_rate":
                slot["resting_heart_rate"] = int(round(float(_hae_pick(rec, "qty", "Avg", default=0))))
            elif name == "blood_pressure_systolic":
                slot["blood_pressure_systolic"] = int(round(float(_hae_pick(rec, "qty", "Avg", default=0))))
            elif name == "blood_pressure_diastolic":
                slot["blood_pressure_diastolic"] = int(round(float(_hae_pick(rec, "qty", "Avg", default=0))))
            elif name == "blood_pressure":
                if rec.get("systolic") is not None:
                    slot["blood_pressure_systolic"] = int(round(float(rec["systolic"])))
                if rec.get("diastolic") is not None:
                    slot["blood_pressure_diastolic"] = int(round(float(rec["diastolic"])))
            elif name == "walking_speed":
                qty = float(_hae_pick(rec, "qty", "Avg", default=0))
                if units == "m/s":
                    qty *= 3.6
                slot["walking_speed_km_h"] = round(qty, 2)
            elif name == "walking_step_length":
                qty = float(_hae_pick(rec, "qty", "Avg", default=0))
                if units == "m":
                    qty *= 100
                slot["walking_step_length_cm"] = round(qty, 1)
            elif name in ("walking_double_support_percentage", "walking_double_support"):
                # HAE для *_percentage метрик всегда шлёт в %, не во фракции.
                # Не множим — реальные значения асимметрии 0.5-3% и попадали в фолс-ветвь ×100.
                slot["walking_double_support_pct"] = round(float(_hae_pick(rec, "qty", "Avg", default=0)), 2)
            elif name in ("walking_asymmetry_percentage", "walking_asymmetry"):
                slot["walking_asymmetry_pct"] = round(float(_hae_pick(rec, "qty", "Avg", default=0)), 2)
            elif name in ("weight_body_mass", "body_mass", "weight"):
                slot["weight_kg"] = round(float(_hae_pick(rec, "qty", "Avg", default=0)), 2)
            elif name == "body_fat_percentage":
                # HAE шлёт уже в процентах (например 27.4), не во фракции.
                slot["body_fat_pct"] = round(float(_hae_pick(rec, "qty", "Avg", default=0)), 1)
            elif name == "lean_body_mass":
                slot["muscle_mass_kg"] = round(float(_hae_pick(rec, "qty", "Avg", default=0)), 2)
            elif name == "vo2_max":
                slot["vo2_max"] = round(float(_hae_pick(rec, "qty", "Avg", default=0)), 1)
            elif name == "respiratory_rate":
                slot["respiratory_rate"] = round(float(_hae_pick(rec, "qty", "Avg", default=0)), 1)
            elif name in ("apple_sleeping_wrist_temperature", "wrist_temperature"):
                slot["wrist_temperature"] = round(float(_hae_pick(rec, "qty", "Avg", default=0)), 2)

    # Преобразуем dict-ы в pydantic AppleHealthPayload (для валидации)
    return {d: AppleHealthPayload(**fields) for d, fields in by_date.items()}


@app.post("/apple_health_v2")
async def receive_apple_health_v2(
    request: Request,
    bearer_token: str = Depends(verify_token),
):
    """Приёмник нативного формата Health Auto Export (data.metrics[]).

    Парсит HAE JSON, группирует по дням, и для каждого дня вызывает ту же
    логику записи в БД, что и /apple_health (v1).
    """
    try:
        raw = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")

    # Debug: logнём имена всех метрик чтобы понять какие HAE на самом деле шлёт.
    try:
        names_seen = sorted({(m.get("name") or "?") for m in (raw.get("data") or {}).get("metrics") or []})
        logger.warning(f"HAE_v2 metrics received ({len(names_seen)}): {', '.join(names_seen)}")
    except Exception:
        pass

    data_block = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data_block, dict):
        raise HTTPException(status_code=400, detail="Expected {'data': {'metrics': [...]}}")
    metrics = data_block.get("metrics") or []
    if not isinstance(metrics, list):
        raise HTTPException(status_code=400, detail="'data.metrics' must be a list")

    daily = _hae_to_daily_payloads(metrics)
    if not daily:
        return {"status": "ok", "days": 0, "details": []}

    # Resolve target user (та же логика, что в v1)
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

    from database import SessionLocal
    from database.crud import create_or_update_activity, get_user_by_health_token, get_activity_by_date
    from sqlalchemy import text as _text

    if APPLE_HEALTH_TOKEN and bearer_token == APPLE_HEALTH_TOKEN:
        target_user_id = _target_user_id
    else:
        _db_auth = SessionLocal()
        try:
            _user = get_user_by_health_token(_db_auth, bearer_token)
        finally:
            _db_auth.close()
        if not _user:
            raise HTTPException(status_code=403, detail="Unknown token")
        target_user_id = _user.telegram_id

    details = []
    db = SessionLocal()
    try:
        for d_str, payload in sorted(daily.items()):
            record_date = date.fromisoformat(d_str)
            saved = []

            heart_rate = payload.resting_heart_rate or payload.heart_rate_avg
            raw_extra = {}
            for k in (
                "walking_speed_km_h",
                "walking_step_length_cm",
                "walking_double_support_pct",
                "walking_asymmetry_pct",
                "flights_climbed",
                "heart_rate_min",
                "heart_rate_max",
                "vo2_max",
                "respiratory_rate",
                "wrist_temperature",
            ):
                v = getattr(payload, k, None)
                if v is not None:
                    raw_extra[k] = v

            # See note above: Apple's active_energy_kcal is NOT written to active_calories.
            # Stored in raw_data only — Garmin remains source of truth for calories triple.
            if payload.active_energy_kcal is not None:
                raw_extra = raw_extra or {}
                raw_extra["apple_active_energy_kcal"] = payload.active_energy_kcal
            if payload.basal_energy_kcal is not None:
                raw_extra = raw_extra or {}
                raw_extra["apple_basal_energy_kcal"] = payload.basal_energy_kcal
            # Apple's basal → bmr_calories ONLY if Garmin hasn't populated it (Garmin > Apple).
            existing_row_v2 = get_activity_by_date(db, target_user_id, record_date)
            apple_bmr_v2 = (
                payload.basal_energy_kcal
                if (
                    payload.basal_energy_kcal is not None
                    and (existing_row_v2 is None or existing_row_v2.bmr_calories is None)
                )
                else None
            )
            create_or_update_activity(
                db=db,
                user_id=target_user_id,
                date=record_date,
                steps=payload.steps,
                bmr_calories=apple_bmr_v2,
                distance_km=payload.distance_walking_km,
                heart_rate_avg=heart_rate,
                source="apple_health_v2",
                raw_data=raw_extra if raw_extra else None,
            )
            saved.append(f"activity (steps={payload.steps}, HR={heart_rate})")

            if payload.blood_pressure_systolic and payload.blood_pressure_diastolic:
                measured_at = datetime.combine(record_date, datetime.min.time().replace(hour=8))
                db.execute(
                    _text(
                        """INSERT INTO blood_pressure_logs
                           (user_id, measured_at, systolic, diastolic, heart_rate, source)
                           VALUES (:uid, :ts, :sys, :dia, :hr, 'apple_health_v2')
                           ON CONFLICT (user_id, measured_at) DO UPDATE
                             SET systolic = EXCLUDED.systolic,
                                 diastolic = EXCLUDED.diastolic"""
                    ),
                    {
                        "uid": target_user_id,
                        "ts": measured_at,
                        "sys": payload.blood_pressure_systolic,
                        "dia": payload.blood_pressure_diastolic,
                        "hr": heart_rate,
                    },
                )
                saved.append(f"BP {payload.blood_pressure_systolic}/{payload.blood_pressure_diastolic}")

            if payload.weight_kg and payload.weight_kg > 30:
                weight_ts = datetime.combine(record_date, datetime.min.time().replace(hour=8))
                # Прямой UPSERT — create_weight не имеет ON CONFLICT, и при повторных
                # вызовах (manual export второй раз) валится на UniqueViolation.
                db.execute(
                    _text(
                        """INSERT INTO weights
                           (user_id, measured_at, weight, body_fat, muscle_mass, water, source)
                           VALUES (:uid, :ts, :w, :bf, :mm, :wt, 'apple_health_v2')
                           ON CONFLICT (user_id, measured_at) DO UPDATE
                             SET weight = EXCLUDED.weight,
                                 body_fat = EXCLUDED.body_fat,
                                 muscle_mass = EXCLUDED.muscle_mass,
                                 water = EXCLUDED.water,
                                 source = EXCLUDED.source"""
                    ),
                    {
                        "uid": target_user_id,
                        "ts": weight_ts,
                        "w": payload.weight_kg,
                        "bf": payload.body_fat_pct,
                        "mm": payload.muscle_mass_kg,
                        "wt": payload.water_pct,
                    },
                )
                saved.append(f"weight {payload.weight_kg}kg")

            details.append({"date": d_str, "saved": saved})

        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Apple Health v2 error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"DB error: {e}")
    finally:
        db.close()

    logger.info(f"✅ Apple Health v2 import: {len(daily)} day(s)")
    return {
        "status": "ok",
        "days": len(daily),
        "details": details,
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
    calorie_goal_pct: int = -15  # signed %: -15 = deficit, 0 = maintain, +10 = surplus
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
                "supplements": [],  # new users start with empty list, not owner's supplements
            }
        return {
            "show_calorie_budget_bar": s.show_calorie_budget_bar,
            "bmr_override": s.bmr_override,
            "target_weight_kg": s.target_weight_kg,
            "target_weight_date": s.target_weight_date.isoformat() if s.target_weight_date else None,
            "calorie_goal_pct": s.calorie_goal_pct if s.calorie_goal_pct is not None else -15,
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
            calorie_goal_pct=payload.calorie_goal_pct,
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

from webhook.dashboard import router as dashboard_router

app.include_router(dashboard_router)

from webhook.profile_api import router as profile_router

app.include_router(profile_router)

from webhook.agent_tools_api import router as agent_tools_router

app.include_router(agent_tools_router)


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
