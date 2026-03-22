#!/usr/bin/env python3
"""
Импорт данных iPhone Screen Time (по-приложенно) из ActivityWatch.

Pipeline:
  1. aw-import-screentime читает Biome файлы с iPhone (через iCloud)
  2. Этот скрипт вытягивает данные из ActivityWatch API → агрегирует по дням
  3. Сохраняет в data/activities/iphone_screentime_perapp.json

Запуск:
  python3 scripts/import_activitywatch.py

Предварительно (раз в день, желательно перед этим скриптом):
  aw-import-screentime events import --device D2727389-2B2E-4E31-88FE-7BF0E925C580

Формат выходного файла:
  {
    "2026-03-09": {
      "total_minutes": 304,
      "apps": [
        {"app_id": "ph.telegra.Telegraph", "name": "Telegram Messenger", "minutes": 39.2},
        ...
      ]
    },
    ...
  }
"""

import requests
import json
import os
from datetime import datetime, timezone, timedelta
from collections import defaultdict

# ActivityWatch local API
AW_BASE_URL = "http://localhost:5600/api/0"
# iPhone device UUID (confirmed by presence of Telegram, Litres, 2GIS)
DEVICE_UUID = "D2727389-2B2E-4E31-88FE-7BF0E925C580"
BUCKET_ID = f"aw-import-screentime_ios_ios-{DEVICE_UUID}"

# Moscow time (UTC+3) — используется для определения дня события
UTC_OFFSET = timedelta(hours=3)

OUTPUT_FILE = "data/activities/iphone_screentime_perapp.json"

# Максимум событий на запрос (ActivityWatch поддерживает до ~100k)
MAX_EVENTS = 100_000


def check_aw_running():
    """Проверяем что ActivityWatch запущен."""
    try:
        resp = requests.get(f"{AW_BASE_URL}/info", timeout=3)
        resp.raise_for_status()
        return True
    except requests.exceptions.ConnectionError:
        return False
    except Exception:
        return False


def fetch_all_events():
    """Загружаем все события из iPhone bucket."""
    resp = requests.get(
        f"{AW_BASE_URL}/buckets/{BUCKET_ID}/events",
        params={"limit": MAX_EVENTS},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def aggregate_by_day(events):
    """
    Агрегируем события по дням (московское время) и приложениям.
    Возвращает dict: { "YYYY-MM-DD": { app_id: {"name": ..., "seconds": ...} } }
    """
    daily_apps: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {"name": "", "seconds": 0.0}))

    for event in events:
        # Парсим UTC timestamp
        ts_str = event["timestamp"]
        ts = datetime.fromisoformat(ts_str)

        # Переводим в московское время для определения дня
        local_ts = ts + UTC_OFFSET
        date_str = local_ts.strftime("%Y-%m-%d")

        app_id = event["data"]["app"]
        duration_sec = event.get("duration", 0.0)

        daily_apps[date_str][app_id]["seconds"] += duration_sec
        # Обновляем название только если оно непустое
        if event["data"].get("title"):
            daily_apps[date_str][app_id]["name"] = event["data"]["title"]
        elif not daily_apps[date_str][app_id]["name"]:
            daily_apps[date_str][app_id]["name"] = app_id

    return daily_apps


def build_output(daily_apps):
    """Строим финальный словарь для JSON."""
    result = {}
    for date_str in sorted(daily_apps.keys()):
        apps_data = daily_apps[date_str]

        # Сортируем по убыванию времени
        sorted_apps = sorted(apps_data.items(), key=lambda x: x[1]["seconds"], reverse=True)

        total_seconds = sum(v["seconds"] for v in apps_data.values())

        result[date_str] = {
            "total_minutes": round(total_seconds / 60, 1),
            "apps": [
                {
                    "app_id": app_id,
                    "name": info["name"],
                    "minutes": round(info["seconds"] / 60, 1),
                }
                for app_id, info in sorted_apps
                if info["seconds"] > 0
            ],
        }

    return result


def fmt_time(minutes):
    """Форматирует минуты в читаемый вид: 'Xч YYм'."""
    h, m = divmod(int(minutes), 60)
    return f"{h}ч {m:02d}м" if h else f"{m}м"


def main():
    print("📱 Импорт iPhone Screen Time (по-приложенно) из ActivityWatch...")

    # Проверяем что AW запущен
    if not check_aw_running():
        print("❌ ActivityWatch не запущен!")
        print("   Запустите: open /Applications/ActivityWatch.app")
        print("   Затем подождите 5 сек и повторите")
        exit(1)

    print(f"   Bucket: {BUCKET_ID}")

    # Загружаем все события
    print("   Загружаю события из ActivityWatch...")
    events = fetch_all_events()
    print(f"   Получено событий: {len(events)}")

    if not events:
        print("⚠️  Нет данных в ActivityWatch.")
        print("   Запустите сначала: aw-import-screentime events import --device D2727389-2B2E-4E31-88FE-7BF0E925C580")
        exit(1)

    # Агрегируем
    daily_apps = aggregate_by_day(events)
    output = build_output(daily_apps)

    # Сохраняем
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # Статистика
    dates = sorted(output.keys())
    total_days = len(dates)
    all_minutes = [v["total_minutes"] for v in output.values()]
    avg_min = sum(all_minutes) / len(all_minutes) if all_minutes else 0

    print(f"\n✅ Сохранено {total_days} дней → {OUTPUT_FILE}")
    print(f"📅 Период: {dates[0]} — {dates[-1]}")
    print(f"📈 Среднее экранное время: {fmt_time(avg_min)}/день")
    print()

    # Последние 7 дней
    print("📊 Последние 7 дней:")
    for date_str in dates[-7:]:
        day = output[date_str]
        top_app = day["apps"][0] if day["apps"] else None
        top_str = f"  (топ: {top_app['name']} {fmt_time(top_app['minutes'])})" if top_app else ""
        print(f"   {date_str}: {fmt_time(day['total_minutes'])}{top_str}")

    # Топ приложений за весь период
    print()
    print("🏆 Топ 10 приложений за весь период:")
    app_totals: dict[str, dict] = defaultdict(lambda: {"name": "", "seconds": 0.0})
    for day_data in output.values():
        for app in day_data["apps"]:
            app_id = app["app_id"]
            app_totals[app_id]["seconds"] += app["minutes"] * 60
            app_totals[app_id]["name"] = app["name"]

    sorted_totals = sorted(app_totals.items(), key=lambda x: x[1]["seconds"], reverse=True)
    for app_id, info in sorted_totals[:10]:
        print(f"   {fmt_time(info['seconds']/60):>8}  {info['name']}")


if __name__ == "__main__":
    main()
