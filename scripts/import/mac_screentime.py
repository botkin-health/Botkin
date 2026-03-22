#!/usr/bin/env python3
"""
Импорт данных Mac Screen Time (по-приложенно) из двух источников:

  1. knowledgeC.db  — Apple Screen Time база, хранит ~30 дней истории.
                       Даёт bundle IDs (com.google.Chrome и т.п.)
                       Требует Full Disk Access для Terminal/Python.

  2. ActivityWatch aw-watcher-window — накапливается с момента установки AW
                       (с 2026-03-09). Даёт app name + window title.
                       Не требует Full Disk Access.

Стратегия: knowledgeC для исторических данных + AW для накопленных.
Итоговый файл объединяет оба источника (AW приоритетнее, если есть).

Выходной формат (data/activities/mac_screentime_perapp.json):
  {
    "2026-03-09": {
      "total_minutes": 380,
      "source": "knowledgec",     // или "activitywatch" или "merged"
      "apps": [
        {"app_id": "com.google.Chrome", "name": "Google Chrome", "minutes": 112.0},
        ...
      ]
    },
    ...
  }

Запуск:
  python3 scripts/import_mac_screentime.py
"""

import sqlite3
import shutil
import os
import json
import requests
from datetime import datetime, timedelta
from collections import defaultdict

DB_PATH = os.path.expanduser("~/Library/Application Support/Knowledge/knowledgeC.db")
TMP_DB = "/tmp/knowledgeC_healthvault.db"

AW_BASE_URL = "http://localhost:5600/api/0"
AW_BUCKET = "aw-watcher-window_MacBook-Air-M4.local"

# Moscow time UTC+3
UTC_OFFSET = timedelta(hours=3)

OUTPUT_FILE = "data/activities/mac_screentime_perapp.json"

# Словарь bundle ID → читаемое название
BUNDLE_NAMES = {
    "com.google.Chrome": "Google Chrome",
    "ru.keepcoder.Telegram": "Telegram",
    "com.anthropic.claudefordesktop": "Claude",
    "com.google.antigravity": "Antigravity",
    "com.microsoft.Excel": "Excel",
    "com.microsoft.Powerpoint": "PowerPoint",
    "com.microsoft.Word": "Word",
    "com.apple.finder": "Finder",
    "com.readdle.SparkDesktop.appstore": "Spark Mail",
    "ru.bitrix.bitrix24desktop": "Bitrix24",
    "us.zoom.xos": "Zoom",
    "com.apple.Notes": "Notes",
    "com.apple.Preview": "Preview",
    "net.whatsapp.WhatsApp": "WhatsApp",
    "dev.warp.Warp-Stable": "Warp",
    "com.flexibits.fantastical2.mac": "Fantastical",
    "com.macpaw.CleanMyMac-mas": "CleanMyMac",
    "notion.id": "Notion",
    "com.apple.systempreferences": "System Preferences",
    "com.apple.AppStore": "App Store",
    "com.apple.Terminal": "Terminal",
    "com.apple.Safari": "Safari",
    "com.apple.Music": "Music",
    "com.apple.Calendar": "Calendar",
    "com.tinyspeck.slackmacgap": "Slack",
    "com.jetbrains.pycharm": "PyCharm",
    "com.microsoft.VSCode": "VS Code",
    "com.sublimetext.4": "Sublime Text",
}


def bundle_to_name(bundle_id: str) -> str:
    """Превращает bundle ID в читаемое название."""
    if not bundle_id:
        return "Unknown"
    if bundle_id in BUNDLE_NAMES:
        return BUNDLE_NAMES[bundle_id]
    # Берём последний сегмент com.google.Chrome → Chrome, com.apple.finder → Finder
    parts = bundle_id.split(".")
    return parts[-1].capitalize() if parts else bundle_id


def read_knowledgec() -> dict[str, dict]:
    """
    Читает knowledgeC.db и возвращает агрегацию по дням.
    { "YYYY-MM-DD": { bundle_id: seconds } }
    """
    if not os.path.exists(DB_PATH):
        print("⚠️  knowledgeC.db не найдена. Нужен Full Disk Access для Terminal.")
        return {}

    try:
        shutil.copy2(DB_PATH, TMP_DB)
    except PermissionError:
        print("⚠️  Нет доступа к knowledgeC.db.")
        print("   System Settings → Privacy & Security → Full Disk Access → добавь Terminal")
        return {}

    conn = sqlite3.connect(TMP_DB)
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT
                date(ZSTARTDATE + 978307200, 'unixepoch', 'localtime') as day,
                ZVALUESTRING as bundle_id,
                SUM(ZENDDATE - ZSTARTDATE) as total_sec
            FROM ZOBJECT
            LEFT JOIN ZSOURCE ON ZOBJECT.ZSOURCE = ZSOURCE.Z_PK
            WHERE ZSTREAMNAME = '/app/usage'
              AND ZVALUESTRING IS NOT NULL
              AND (ZENDDATE - ZSTARTDATE) > 0
            GROUP BY day, bundle_id
            ORDER BY day
        """)
        rows = cur.fetchall()
    except sqlite3.OperationalError as e:
        print(f"⚠️  Ошибка чтения knowledgeC.db: {e}")
        return {}
    finally:
        conn.close()
        if os.path.exists(TMP_DB):
            os.remove(TMP_DB)

    result: dict[str, dict] = defaultdict(lambda: defaultdict(float))
    for day, bundle_id, total_sec in rows:
        if day and bundle_id:
            result[day][bundle_id] += total_sec

    return dict(result)


def check_aw_running() -> bool:
    try:
        resp = requests.get(f"{AW_BASE_URL}/info", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def read_activitywatch() -> dict[str, dict]:
    """
    Читает ActivityWatch Mac watcher bucket.
    Возвращает { "YYYY-MM-DD": { app_name: seconds } }
    """
    if not check_aw_running():
        return {}

    try:
        resp = requests.get(
            f"{AW_BASE_URL}/buckets/{AW_BUCKET}/events",
            params={"limit": 100_000},
            timeout=30,
        )
        if resp.status_code != 200:
            return {}
        events = resp.json()
    except Exception as e:
        print(f"⚠️  Ошибка чтения ActivityWatch Mac: {e}")
        return {}

    result: dict[str, dict] = defaultdict(lambda: defaultdict(float))
    for e in events:
        ts = datetime.fromisoformat(e["timestamp"]) + UTC_OFFSET
        date_str = ts.strftime("%Y-%m-%d")
        app_name = e["data"].get("app", "Unknown")
        result[date_str][app_name] += e.get("duration", 0.0)

    return dict(result)


def build_output(kc_data: dict, aw_data: dict) -> dict:
    """
    Объединяет данные из двух источников.
    - Если день есть только в knowledgeC → source="knowledgec"
    - Если только в AW → source="activitywatch"
    - Если в обоих → AW приоритетнее (более точный, без ограничения 30 дней)
      но если в AW данных мало (<30 мин) → используем knowledgeC с source="knowledgec"
    """
    all_dates = sorted(set(kc_data.keys()) | set(aw_data.keys()))
    result = {}

    for date_str in all_dates:
        in_kc = date_str in kc_data
        in_aw = date_str in aw_data

        if in_aw:
            aw_total = sum(aw_data[date_str].values())
            # AW приоритетнее если накопил хотя бы 30 минут
            if aw_total >= 30 * 60:
                apps_raw = aw_data[date_str]
                source = "activitywatch"
            elif in_kc:
                apps_raw = kc_data[date_str]
                source = "knowledgec"
            else:
                apps_raw = aw_data[date_str]
                source = "activitywatch"
        else:
            apps_raw = kc_data[date_str]
            source = "knowledgec"

        # Строим список приложений
        sorted_apps = sorted(apps_raw.items(), key=lambda x: x[1], reverse=True)
        total_sec = sum(v for _, v in sorted_apps)

        if source == "activitywatch":
            apps_list = [
                {"app_id": app_name, "name": app_name, "minutes": round(sec / 60, 1)}
                for app_name, sec in sorted_apps
                if sec > 0
            ]
        else:
            apps_list = [
                {"app_id": bundle_id, "name": bundle_to_name(bundle_id), "minutes": round(sec / 60, 1)}
                for bundle_id, sec in sorted_apps
                if sec > 0
            ]

        result[date_str] = {
            "total_minutes": round(total_sec / 60, 1),
            "source": source,
            "apps": apps_list,
        }

    return result


def fmt_time(minutes: float) -> str:
    h, m = divmod(int(minutes), 60)
    return f"{h}ч {m:02d}м" if h else f"{m}м"


def main():
    print("🖥️  Импорт Mac Screen Time (по-приложенно)...")

    # Источник 1: knowledgeC.db
    print("   📂 Читаю knowledgeC.db...")
    kc_data = read_knowledgec()
    if kc_data:
        dates = sorted(kc_data.keys())
        print(f"   ✅ knowledgeC: {len(kc_data)} дней ({dates[0]} — {dates[-1]})")
    else:
        print("   ⚠️  knowledgeC: нет данных")

    # Источник 2: ActivityWatch Mac watcher
    print("   📡 Читаю ActivityWatch Mac watcher...")
    aw_data = read_activitywatch()
    if aw_data:
        dates_aw = sorted(aw_data.keys())
        print(f"   ✅ ActivityWatch: {len(aw_data)} дней ({dates_aw[0]} — {dates_aw[-1]})")
    else:
        print("   ⚠️  ActivityWatch: нет данных (или не запущен)")

    if not kc_data and not aw_data:
        print("❌ Нет данных ни из одного источника. Выход.")
        exit(1)

    # Объединяем
    output = build_output(kc_data, aw_data)

    # Сохраняем
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # Статистика
    dates_all = sorted(output.keys())
    all_minutes = [v["total_minutes"] for v in output.values()]
    avg_min = sum(all_minutes) / len(all_minutes) if all_minutes else 0

    kc_days = sum(1 for v in output.values() if v["source"] == "knowledgec")
    aw_days = sum(1 for v in output.values() if v["source"] == "activitywatch")

    print(f"\n✅ Сохранено {len(output)} дней → {OUTPUT_FILE}")
    print(f"📅 Период: {dates_all[0]} — {dates_all[-1]}")
    print(f"📈 Среднее время за Mac: {fmt_time(avg_min)}/день")
    print(f"📊 Источники: knowledgeC={kc_days} дней, ActivityWatch={aw_days} дней")
    print()

    print("📋 Последние 7 дней:")
    for date_str in dates_all[-7:]:
        day = output[date_str]
        top_app = day["apps"][0] if day["apps"] else None
        src_icon = "📂" if day["source"] == "knowledgec" else "📡"
        top_str = f"  (топ: {top_app['name']} {fmt_time(top_app['minutes'])})" if top_app else ""
        print(f"   {src_icon} {date_str}: {fmt_time(day['total_minutes'])}{top_str}")

    print()
    print("🏆 Топ 10 Mac-приложений за весь период:")
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
