#!/usr/bin/env python3
"""
Импорт данных Netatmo Home Coach (воздух дома).

Авторизация — OAuth2 через CLIENT_ID + CLIENT_SECRET + REFRESH_TOKEN (.env).
Все секреты в .env, в коде хардкода нет.

Запуск:
    python scripts/import/netatmo.py                # текущие + история 60 дней
"""

import json
import os
import time
from pathlib import Path

import lnetatmo
import requests
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ENV_DIR = PROJECT_ROOT / "data" / "environment"

CLIENT_ID = os.getenv("NETATMO_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("NETATMO_CLIENT_SECRET", "")
REFRESH_TOKEN = os.getenv("NETATMO_REFRESH_TOKEN", "")

# Станции которые игнорируем (старые/неактивные)
SKIP_STATIONS = {"Гнездышко"}


def fetch_homecoach_data():
    if not (CLIENT_ID and CLIENT_SECRET and REFRESH_TOKEN):
        print("❌ В .env нет NETATMO_CLIENT_ID / NETATMO_CLIENT_SECRET / NETATMO_REFRESH_TOKEN")
        return []

    try:
        auth = lnetatmo.ClientAuth(clientId=CLIENT_ID, clientSecret=CLIENT_SECRET, refreshToken=REFRESH_TOKEN)
        homecoach = lnetatmo.HomeCoach(auth)
    except Exception as e:
        print(f"❌ Ошибка авторизации Netatmo: {e}")
        return []

    current = []
    print("🔄 Текущие метрики Netatmo...")
    for st in homecoach.rawData:
        name = st.get("station_name", "Unknown")
        if name in SKIP_STATIONS or not st.get("reachable", False) or "dashboard_data" not in st:
            continue
        d = st["dashboard_data"]
        entry = {
            "device_name": name,
            "temperature_c": d.get("Temperature"),
            "humidity_percent": d.get("Humidity"),
            "co2_ppm": d.get("CO2"),
            "noise_db": d.get("Noise"),
            "health_idx": d.get("health_idx"),
            "timestamp": d.get("time_utc"),
        }
        current.append(entry)
        print(f"  🌡️  {name}: {entry['temperature_c']}°C, CO₂ {entry['co2_ppm']} ppm, шум {entry['noise_db']} дБ")

    # История 60 дней
    print("🔄 История Netatmo за 60 дней...")
    history = {}
    for st in homecoach.rawData:
        device_id = st.get("_id")
        name = st.get("station_name", "Unknown")
        if not device_id or name in SKIP_STATIONS:
            continue
        resp = requests.post(
            "https://api.netatmo.com/api/getmeasure",
            data={
                "access_token": homecoach.getAuthToken,
                "device_id": device_id,
                "scale": "1day",
                "type": "Temperature,CO2,Humidity,Noise",
                "date_begin": int(time.time() - 60 * 24 * 3600),
                "optimize": "false",
            },
            timeout=15,
        )
        if resp.status_code == 200:
            history[name] = resp.json().get("body", {})
            print(f"  ✓ История {name}: {len(history[name])} дней")
        else:
            print(f"  ⚠️ Ошибка истории {name}: {resp.status_code}")

    ENV_DIR.mkdir(parents=True, exist_ok=True)
    if current:
        (ENV_DIR / "netatmo_log.json").write_text(json.dumps(current, ensure_ascii=False, indent=2))
        print(f"  ✓ Сохранено: {ENV_DIR / 'netatmo_log.json'}")
    if history:
        (ENV_DIR / "netatmo_history.json").write_text(json.dumps(history, ensure_ascii=False, indent=2))
        print(f"  ✓ Сохранено: {ENV_DIR / 'netatmo_history.json'}")

    return current


if __name__ == "__main__":
    fetch_homecoach_data()
