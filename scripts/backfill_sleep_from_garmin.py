#!/usr/bin/env python3
"""
Дозаполнение сна из data/garmin/sleep/*.json для дней, где в activity_log нет sleep_hours или 0.
Читает dailySleepDTO.sleepTimeSeconds, обновляет/создаёт запись в activity_log.
Запуск: python scripts/backfill_sleep_from_garmin.py (из корня или в контейнере с PYTHONPATH=/app).
"""

import json
import os
import sys
from pathlib import Path
from datetime import date, timedelta

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from database import SessionLocal
from database.crud import create_or_update_activity
from sqlalchemy import text

USER_ID = int(os.getenv("HEALTHVAULT_USER_ID", "895655"))
SLEEP_DIR = project_root / "data" / "garmin" / "sleep"
START = date(2026, 1, 6)
END = date.today()


def main():
    if not SLEEP_DIR.exists():
        print(f"❌ Папка не найдена: {SLEEP_DIR}")
        return
    db = SessionLocal()
    try:
        # Даты, где в БД уже есть сон > 0
        r = db.execute(text("""
            SELECT date FROM activity_log
            WHERE user_id = :uid AND date >= :start AND date <= :end
            AND sleep_hours IS NOT NULL AND sleep_hours > 0
        """), {"uid": USER_ID, "start": START, "end": END})
        has_sleep = {row[0] for row in r.fetchall()}
        # Недостающие даты
        days = (END - START).days + 1
        missing = [START + timedelta(days=i) for i in range(days) if (START + timedelta(days=i)) not in has_sleep]
        if not missing:
            print("Сон уже есть за все дни в диапазоне.")
            return
        updated = 0
        for d in missing:
            f = SLEEP_DIR / f"{d}.json"
            if not f.exists():
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                dto = data.get("dailySleepDTO") or data
                sec = dto.get("sleepTimeSeconds") or dto.get("sleepTime") or 0
                if not sec:
                    continue
                sleep_hours = round(sec / 3600.0, 2)
                create_or_update_activity(
                    db, USER_ID, d,
                    sleep_hours=sleep_hours,
                    source="garmin_sleep_json",
                )
                updated += 1
            except Exception as e:
                print(f"  ❌ {d}: {e}")
        print(f"Сон из Garmin sleep: обновлено {updated} дней (проверено {len(missing)} без сна).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
