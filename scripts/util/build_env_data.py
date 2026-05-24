#!/usr/bin/env python3
"""
build_env_data.py — серверный derived-builder для блока «Воздух дома» на дашборде.

Что делает:
  1. Читает /app/data/environment/netatmo_history.json (его обновляет ночной
     cron sync_all.sh шагом netatmo).
  2. Извлекает CO₂, температуру и влажность по дням за последние 30 дней.
  3. Пишет в финальное место, которое читает dashboard_generator.py:
         /app/telegram-bot/env_data_{user_id}.json
     Формат:
         {"co2": {"2026-05-22": 615, ...}, "temp_home": {...}, "humidity": {...}}

Зачем существует отдельным скриптом:
  До этого env_data строился только локально на маке
  (scripts/import/push_netatmo_to_container.py). При запуске cron на сервере
  netatmo_history.json обновлялся, но derived-файл для дашборда — нет, и блок
  «Воздух дома» отставал. Этот скрипт переносит derived-логику на сервер.
  Симметрично build_workouts_log.py.

В sync_all.sh:
    run netatmo  /app/scripts/import/netatmo.py
    run env      /app/scripts/util/build_env_data.py

В /sync в боте: ключ "env" в SOURCES (handlers/sync_cmd.py).

Multi-user: сейчас Netatmo один на семью (Александра), но скрипт принимает
--user-id, чтобы переход на per-user данные был механическим.

Формат netatmo_history.json (см. также scripts/import/push_netatmo_to_container.py):
    {
      "<StationName>": {
        "<unix_timestamp_str>": [Temperature, CO2, Humidity, Noise],
        ...
      }
    }
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULT_USER_ID = 895655
KEEP_DAYS = 30  # дашборду больше не нужно

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SOURCE = BASE_DIR / "data" / "environment" / "netatmo_history.json"


def out_path_for(user_id: int) -> Path:
    """Финальное место, откуда читает dashboard_generator.py."""
    return BASE_DIR / "telegram-bot" / f"env_data_{user_id}.json"


def build_env_data(raw: dict) -> dict:
    """Convert netatmo_history.json → env_data dict keyed by date.

    Если за один день несколько замеров (каждые 30 мин) — берём среднее.
    Это даёт более стабильную дневную картину чем «последний замер»,
    особенно для CO₂ (который сильно колеблется).
    """
    by_day_temp: dict[str, list[float]] = {}
    by_day_co2: dict[str, list[float]] = {}
    by_day_hum: dict[str, list[float]] = {}

    for station_data in raw.values():
        if not isinstance(station_data, dict):
            continue
        for ts_str, values in station_data.items():
            try:
                ts = int(ts_str)
                d = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                continue
            if not isinstance(values, (list, tuple)) or len(values) < 3:
                continue
            t, c, h = values[0], values[1], values[2]
            if t is not None:
                by_day_temp.setdefault(d, []).append(float(t))
            if c is not None:
                by_day_co2.setdefault(d, []).append(float(c))
            if h is not None:
                by_day_hum.setdefault(d, []).append(float(h))

    cutoff = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()

    def _avg(days: dict[str, list[float]], to_int: bool = False) -> dict:
        out: dict = {}
        for d, vals in days.items():
            if d < cutoff or not vals:
                continue
            avg = sum(vals) / len(vals)
            out[d] = int(round(avg)) if to_int else round(avg, 1)
        return dict(sorted(out.items()))

    return {
        "co2": _avg(by_day_co2, to_int=True),
        "temp_home": _avg(by_day_temp),
        "humidity": _avg(by_day_hum, to_int=True),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--user-id", type=int, default=DEFAULT_USER_ID, help=f"Telegram user_id (default {DEFAULT_USER_ID})"
    )
    args = parser.parse_args()

    if not SOURCE.exists():
        print(f"❌ {SOURCE} не найден — сначала запусти netatmo.py", file=sys.stderr)
        return 2

    raw = json.loads(SOURCE.read_text())
    env_data = build_env_data(raw)

    n_co2 = len(env_data.get("co2", {}))
    n_temp = len(env_data.get("temp_home", {}))
    n_hum = len(env_data.get("humidity", {}))

    out = out_path_for(args.user_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(env_data, ensure_ascii=False), encoding="utf-8")

    all_dates = set(env_data.get("co2", {}).keys()) | set(env_data.get("temp_home", {}).keys())
    latest = max(all_dates, default="—")
    print(f"✅ {out.name}: CO₂×{n_co2}, T×{n_temp}, H×{n_hum} за {KEEP_DAYS} дней (latest: {latest})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
