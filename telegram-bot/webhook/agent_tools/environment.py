"""Agent tools: indoor air quality (Netatmo) and outdoor weather (Open-Meteo)."""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from webhook.jwt_auth import get_agent_user, get_db
from .common import _dt_isoformat_local

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent", tags=["agent-tools-environment"])


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
                    "measured_at": _dt_isoformat_local(
                        datetime.fromtimestamp(latest["timestamp"], tz=timezone.utc), user
                    )
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
