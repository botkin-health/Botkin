#!/usr/bin/env python3
"""Fetch historical weather data from Open-Meteo for HealthVault analysis."""

import json
import requests
from datetime import date

LAT = 55.7816
LON = 37.5706
START = "2026-01-06"
END = date.today().isoformat()

url = "https://api.open-meteo.com/v1/forecast"
params = {
    "latitude": LAT,
    "longitude": LON,
    "daily": [
        "temperature_2m_max",
        "temperature_2m_min",
        "temperature_2m_mean",
        "precipitation_sum",
        "sunshine_duration",  # секунды солнца за день
        "uv_index_max",
        "windspeed_10m_max",
        "weathercode",
    ],
    "hourly": [
        "pressure_msl",  # атмосферное давление мПа
        "relativehumidity_2m",
    ],
    "timezone": "Europe/Moscow",
    "start_date": START,
    "end_date": END,
}

print(f"Fetching weather {START} → {END} for Moscow ({LAT}, {LON})...")
r = requests.get(url, params=params)
r.raise_for_status()
data = r.json()

daily = data["daily"]
hourly = data["hourly"]

# Build per-day pressure average from hourly data
pressure_by_day = {}
for i, dt in enumerate(hourly["time"]):
    day = dt[:10]
    p = hourly["pressure_msl"][i]
    if p is not None:
        pressure_by_day.setdefault(day, []).append(p)

# WMO weather code → description
WMO = {
    0: "Ясно",
    1: "Преим. ясно",
    2: "Переменная облачность",
    3: "Пасмурно",
    45: "Туман",
    48: "Изморозь",
    51: "Лёгкая морось",
    53: "Морось",
    55: "Сильная морось",
    61: "Лёгкий дождь",
    63: "Дождь",
    65: "Сильный дождь",
    71: "Лёгкий снег",
    73: "Снег",
    75: "Сильный снег",
    77: "Снежные зёрна",
    80: "Ливень",
    81: "Сильный ливень",
    82: "Очень сильный ливень",
    85: "Снегопад",
    86: "Сильный снегопад",
    95: "Гроза",
    96: "Гроза с градом",
    99: "Гроза с сильным градом",
}

entries = []
for i, day in enumerate(daily["time"]):
    pressures = pressure_by_day.get(day, [])
    avg_pressure = round(sum(pressures) / len(pressures) * 0.750062, 1) if pressures else None  # hPa → mmHg
    sunshine_h = round(daily["sunshine_duration"][i] / 3600, 1) if daily["sunshine_duration"][i] is not None else None
    wcode = daily["weathercode"][i]

    entry = {
        "date": day,
        "temp_max": daily["temperature_2m_max"][i],
        "temp_min": daily["temperature_2m_min"][i],
        "temp_mean": daily["temperature_2m_mean"][i],
        "pressure_mmhg": avg_pressure,
        "humidity_pct": round(sum(hourly["relativehumidity_2m"][i * 24 : (i + 1) * 24]) / 24)
        if i * 24 < len(hourly["relativehumidity_2m"])
        else None,
        "sunshine_hours": sunshine_h,
        "uv_index_max": daily["uv_index_max"][i],
        "precipitation_mm": daily["precipitation_sum"][i],
        "weather_code": wcode,
        "weather": WMO.get(wcode, f"Код {wcode}"),
    }
    entries.append(entry)

output = {
    "source": "open-meteo",
    "location": {"lat": LAT, "lon": LON, "city": "Москва"},
    "entries": entries,
}

import os

from pathlib import Path

_weather_dir = Path(__file__).resolve().parents[2] / "data" / "weather"
os.makedirs(_weather_dir, exist_ok=True)
out_path = str(_weather_dir / "weather_history.json")
with open(out_path, "w") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"Saved {len(entries)} days to {out_path}")

# Print summary table
print(f"\n{'Дата':<12} {'t°min':>6} {'t°max':>6} {'Давл.':>7} {'Солнце':>8} {'УФ':>4} {'Погода'}")
print("-" * 75)
for e in entries:
    sun = f"{e['sunshine_hours']}ч" if e["sunshine_hours"] is not None else "—"
    pres = f"{e['pressure_mmhg']}" if e["pressure_mmhg"] else "—"
    uv = f"{e['uv_index_max']}" if e["uv_index_max"] is not None else "—"
    print(
        f"{e['date']:<12} {str(e['temp_min']) + '°':>6} {str(e['temp_max']) + '°':>6} {pres + ' мм':>7} {sun:>8} {uv:>4}  {e['weather']}"
    )
