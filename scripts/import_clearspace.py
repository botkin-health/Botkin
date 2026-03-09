#!/usr/bin/env python3
"""
Импорт данных экранного времени iPhone из Screen Time Network API (Clearspace)
https://thescreentimenetwork.com/api

Данные: суммарное время экрана iPhone в минутах по дням.
"""

import requests
import json
import os
from datetime import datetime

API_KEY = "CLEARSPACE_API_KEY_REDACTED"
HANDLE = "alexlyskovsky"
BASE_URL = "https://api.thescreentimenetwork.com/v1"
OUTPUT_FILE = "data/activities/clearspace_iphone_screentime.json"

HEADERS = {"x-api-key": API_KEY}


def get_historical():
    resp = requests.get(
        f"{BASE_URL}/getScreenTimeHistorical",
        params={"handle": HANDLE},
        headers=HEADERS,
        timeout=15
    )
    resp.raise_for_status()
    return resp.json()


def get_today():
    resp = requests.get(
        f"{BASE_URL}/getScreenTimeToday",
        params={"handle": HANDLE},
        headers=HEADERS,
        timeout=15
    )
    resp.raise_for_status()
    return resp.json()


def fmt_time(minutes):
    h, m = divmod(int(minutes), 60)
    return f"{h}ч {m:02d}м" if h else f"{m}м"


if __name__ == "__main__":
    print("📱 Загружаю данные iPhone Screen Time (Screen Time Network API)...")

    # Historical
    hist = get_historical()
    if not hist.get("success"):
        print(f"❌ Ошибка исторических данных: {hist.get('error')}")
        exit(1)

    # Normalize dates: historical API returns MM/DD/YYYY, convert to YYYY-MM-DD
    raw_days = hist["data"]["days"]
    days = []
    for d in raw_days:
        date_str = d["date"]
        try:
            # Try MM/DD/YYYY format
            dt = datetime.strptime(date_str, "%m/%d/%Y")
            date_str = dt.strftime("%Y-%m-%d")
        except ValueError:
            pass  # Already YYYY-MM-DD
        days.append({"date": date_str, "screenTime": d["screenTime"]})

    # Today (актуальнее чем в historical)
    today_resp = get_today()
    if today_resp.get("success"):
        td = today_resp["data"]
        today_entry = {
            "date": td["localDate"],
            "screenTime": td["totalScreenTime"]
        }
        existing_dates = {d["date"] for d in days}
        if today_entry["date"] in existing_dates:
            days = [today_entry if d["date"] == today_entry["date"] else d for d in days]
        else:
            days.append(today_entry)
        print(f"   Сегодня ({td['localDate']}): {fmt_time(td['totalScreenTime'])}")

    # Только дни с данными (screenTime > 0)
    days_with_data = [d for d in days if d.get("screenTime", 0) > 0]
    days_sorted = sorted(days, key=lambda d: d["date"])

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(days_sorted, f, indent=2, ensure_ascii=False)

    print(f"✅ Сохранено {len(days_sorted)} дней → {OUTPUT_FILE}")
    if days_with_data:
        print(f"📅 Период с данными: {days_with_data[0]['date']} — {days_with_data[-1]['date']}")
        print(f"📊 Дней с данными (>0 мин): {len(days_with_data)}")
        avg = sum(d["screenTime"] for d in days_with_data) / len(days_with_data)
        print(f"📈 Среднее: {fmt_time(avg)}/день")
        for d in days_with_data[-7:]:
            print(f"   {d['date']}: {fmt_time(d['screenTime'])}")
    else:
        print("⚠️  Данных пока нет — приложение только что подключено, синхронизация займёт несколько минут")
