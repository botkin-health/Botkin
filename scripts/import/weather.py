#!/usr/bin/env python3
"""
Import weather data for HealthVault.
Gets current location via CoreLocationCLI (WiFi-based, VPN-safe),
fetches weather from Open-Meteo API, saves to data/weather/.

Usage:
    python3 scripts/import_weather.py              # today only
    python3 scripts/import_weather.py --backfill   # full history from 2026-01-06
"""

import json
import os
import subprocess
import sys
import requests
from datetime import date, timedelta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
WEATHER_DIR = os.path.join(PROJECT_ROOT, "data/weather")
HISTORY_FILE = os.path.join(WEATHER_DIR, "weather_history.json")

DEFAULT_LAT = 55.7816
DEFAULT_LON = 37.5706
DEFAULT_CITY = "Москва"
MOSCOW_RADIUS_DEG = 0.5  # ~55 km — если GPS дальше, считаем не Москвой

GARMIN_ACTIVITIES_DIR = os.path.join(os.path.dirname(__file__), "../data/garmin/activities")

# Manual location overrides for known trips (date → city, lat, lon)
LOCATION_OVERRIDES = {
    "2026-01-29": ("Санкт-Петербург", 59.9343, 30.3351),
    "2026-01-30": ("Санкт-Петербург", 59.9343, 30.3351),
    "2026-05-05": ("Челябинск", 55.1644, 61.4368),
    "2026-05-06": ("Челябинск", 55.1644, 61.4368),
}

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


def get_location_from_garmin(day_str: str):
    """Extract GPS location from Garmin activity files for a given date."""
    if not os.path.exists(GARMIN_ACTIVITIES_DIR):
        return None
    for fname in os.listdir(GARMIN_ACTIVITIES_DIR):
        if not fname.startswith(day_str) or "_details" in fname:
            continue
        try:
            with open(os.path.join(GARMIN_ACTIVITIES_DIR, fname)) as f:
                d = json.load(f)
            if not isinstance(d, dict):
                continue
            lat = d.get("startLatitude")
            lon = d.get("startLongitude")
            loc_name = d.get("locationName")
            if lat is None or lon is None:
                continue
            # Check if it's outside Moscow area
            if abs(lat - DEFAULT_LAT) > MOSCOW_RADIUS_DEG or abs(lon - DEFAULT_LON) > MOSCOW_RADIUS_DEG:
                city = loc_name or f"{lat:.2f},{lon:.2f}"
                return lat, lon, city
        except Exception:
            continue
    return None


def get_current_location():
    """Get current coordinates via CoreLocationCLI (WiFi-based, works with VPN)."""
    try:
        result = subprocess.run(
            ["CoreLocationCLI", "-once", "-format", "%latitude %longitude"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split()
            return float(parts[0]), float(parts[1]), "текущее местоположение"
    except Exception as e:
        print(f"  [!] CoreLocationCLI недоступен: {e}, использую Москву")
    return DEFAULT_LAT, DEFAULT_LON, DEFAULT_CITY


def fetch_weather_range(lat, lon, start_date, end_date):
    """Fetch daily weather from Open-Meteo.
    Uses archive API for past dates, forecast API for today/future.
    Merges results if range spans both."""
    daily_params = [
        "temperature_2m_max",
        "temperature_2m_min",
        "temperature_2m_mean",
        "precipitation_sum",
        "sunshine_duration",
        "uv_index_max",
        "weathercode",
    ]
    hourly_params = ["pressure_msl", "relativehumidity_2m"]
    today = date.today()

    # If entire range is in the past (before today), use archive API
    if end_date < today:
        url = "https://archive-api.open-meteo.com/v1/archive"
    # If range starts in the past but includes today, fetch archive + forecast separately
    elif start_date < today:
        # Archive for past days
        archive_r = requests.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": daily_params,
                "hourly": hourly_params,
                "timezone": "Europe/Moscow",
                "start_date": start_date.isoformat(),
                "end_date": (today - timedelta(days=1)).isoformat(),
            },
            timeout=15,
        )
        archive_r.raise_for_status()
        archive_data = archive_r.json()

        # Forecast for today
        forecast_r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": daily_params,
                "hourly": hourly_params,
                "timezone": "Europe/Moscow",
                "start_date": today.isoformat(),
                "end_date": end_date.isoformat(),
            },
            timeout=15,
        )
        forecast_r.raise_for_status()
        forecast_data = forecast_r.json()

        # Merge daily and hourly arrays
        for key in archive_data.get("daily", {}):
            if key in forecast_data.get("daily", {}) and isinstance(archive_data["daily"][key], list):
                archive_data["daily"][key].extend(forecast_data["daily"][key])
        for key in archive_data.get("hourly", {}):
            if key in forecast_data.get("hourly", {}) and isinstance(archive_data["hourly"][key], list):
                archive_data["hourly"][key].extend(forecast_data["hourly"][key])
        return archive_data
    else:
        url = "https://api.open-meteo.com/v1/forecast"

    r = requests.get(
        url,
        params={
            "latitude": lat,
            "longitude": lon,
            "daily": daily_params,
            "hourly": hourly_params,
            "timezone": "Europe/Moscow",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def parse_day(data, day_idx, day_str, city, lat, lon):
    """Parse one day from Open-Meteo response."""
    daily = data["daily"]
    hourly = data["hourly"]

    h_start, h_end = day_idx * 24, (day_idx + 1) * 24
    pressures = [p for p in hourly["pressure_msl"][h_start:h_end] if p is not None]
    humidities = [h for h in hourly["relativehumidity_2m"][h_start:h_end] if h is not None]

    avg_pressure = round(sum(pressures) / len(pressures) * 0.750062, 1) if pressures else None
    avg_humidity = round(sum(humidities) / len(humidities)) if humidities else None
    sun_raw = daily["sunshine_duration"][day_idx]
    sunshine_h = round(sun_raw / 3600, 1) if sun_raw is not None else None
    wcode = daily["weathercode"][day_idx]

    return {
        "date": day_str,
        "city": city,
        "lat": lat,
        "lon": lon,
        "temp_max": daily["temperature_2m_max"][day_idx],
        "temp_min": daily["temperature_2m_min"][day_idx],
        "temp_mean": daily["temperature_2m_mean"][day_idx],
        "pressure_mmhg": avg_pressure,
        "humidity_pct": avg_humidity,
        "sunshine_hours": sunshine_h,
        "uv_index_max": daily["uv_index_max"][day_idx],
        "precipitation_mm": daily["precipitation_sum"][day_idx],
        "weather_code": wcode,
        "weather": WMO.get(wcode, f"Код {wcode}"),
    }


def load_history():
    os.makedirs(WEATHER_DIR, exist_ok=True)
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return {
        "source": "open-meteo",
        "default_location": {"lat": DEFAULT_LAT, "lon": DEFAULT_LON, "city": DEFAULT_CITY},
        "location_overrides": {k: v[0] for k, v in LOCATION_OVERRIDES.items()},
        "entries": [],
    }


def save_history(data):
    with open(HISTORY_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def update_today():
    """Fetch today's weather and upsert into history."""
    today = date.today()
    today_str = today.isoformat()

    if today_str in LOCATION_OVERRIDES:
        city, lat, lon = LOCATION_OVERRIDES[today_str]
        print(f"  Используем override: {city}")
    else:
        lat, lon, city = get_current_location()
        if city == "текущее местоположение":
            city = DEFAULT_CITY  # will geocode later if needed

    print(f"  Погода для {today_str} ({city}, {lat:.4f}, {lon:.4f})...")
    data_raw = fetch_weather_range(lat, lon, today, today)
    entry = parse_day(data_raw, 0, today_str, city, lat, lon)

    history = load_history()
    entries_by_date = {e["date"]: e for e in history["entries"]}
    entries_by_date[today_str] = entry
    history["entries"] = [entries_by_date[d] for d in sorted(entries_by_date)]
    history["location_overrides"] = {k: v[0] for k, v in LOCATION_OVERRIDES.items()}
    save_history(history)
    print(
        f"  ✓ {today_str}: {entry['temp_min']}°/{entry['temp_max']}° давл.{entry['pressure_mmhg']}мм {entry['sunshine_hours']}ч солнца {entry['weather']}"
    )
    return entry


def backfill():
    """Fetch full history from 2026-01-06 to today with correct locations."""
    start = date(2026, 1, 6)
    end = date.today()
    print(f"  Бэкфил погоды {start} → {end}...")

    # Group dates by location
    groups = {}
    current = start
    while current <= end:
        day_str = current.isoformat()
        if day_str in LOCATION_OVERRIDES:
            city, lat, lon = LOCATION_OVERRIDES[day_str]
        else:
            lat, lon, city = DEFAULT_LAT, DEFAULT_LON, DEFAULT_CITY
        key = (city, lat, lon)
        groups.setdefault(key, []).append(current)
        current += timedelta(days=1)

    entries_by_date = {}
    for (city, lat, lon), dates in groups.items():
        batch_start, batch_end = min(dates), max(dates)
        print(f"  Загружаю {city}: {batch_start} → {batch_end}...")
        data_raw = fetch_weather_range(lat, lon, batch_start, batch_end)
        for i, d in enumerate(data_raw["daily"]["time"]):
            entries_by_date[d] = parse_day(data_raw, i, d, city, lat, lon)

    history = load_history()
    history["entries"] = [entries_by_date[d] for d in sorted(entries_by_date)]
    history["location_overrides"] = {k: v[0] for k, v in LOCATION_OVERRIDES.items()}
    save_history(history)
    print(f"  ✓ Сохранено {len(history['entries'])} дней")


def update_since_last():
    """Fetch all missing days from start of tracking to today."""
    history = load_history()
    existing = {e["date"] for e in history["entries"]}
    today = date.today()
    start = date(2026, 1, 6)

    # Find ALL missing days in the full range, not just after max(existing)
    missing = []
    current = start
    while current <= today:
        if current.isoformat() not in existing:
            missing.append(current)
        current += timedelta(days=1)

    if not missing:
        print(f"  Погода актуальна (последняя запись: {max(existing)})")
        return

    print(f"  Загружаю погоду за {len(missing)} пропущенных дней ({missing[0]} → {missing[-1]})...")

    # Group missing days by location (overrides → Garmin GPS → default Moscow)
    groups = {}
    for d in missing:
        day_str = d.isoformat()
        if day_str in LOCATION_OVERRIDES:
            city, lat, lon = LOCATION_OVERRIDES[day_str]
        else:
            garmin_loc = get_location_from_garmin(day_str)
            if garmin_loc:
                lat, lon, city = garmin_loc
                print(f"  GPS из Garmin: {day_str} → {city} ({lat:.4f}, {lon:.4f})")
            else:
                lat, lon, city = DEFAULT_LAT, DEFAULT_LON, DEFAULT_CITY
        key = (city, lat, lon)
        groups.setdefault(key, []).append(d)

    entries_by_date = {e["date"]: e for e in history["entries"]}

    for (city, lat, lon), dates in groups.items():
        data_raw = fetch_weather_range(lat, lon, min(dates), max(dates))
        for i, day_str in enumerate(data_raw["daily"]["time"]):
            entries_by_date[day_str] = parse_day(data_raw, i, day_str, city, lat, lon)

    history["entries"] = [entries_by_date[d] for d in sorted(entries_by_date)]
    history["location_overrides"] = {k: v[0] for k, v in LOCATION_OVERRIDES.items()}
    save_history(history)
    print(f"  ✓ Погода обновлена до {today.isoformat()} ({len(history['entries'])} дней всего)")


if __name__ == "__main__":
    if "--backfill" in sys.argv:
        backfill()
    else:
        update_since_last()
