#!/usr/bin/env python3
"""
Отчёт покрытия по датам с 2026-01-06: питание, вес, витамины, активность (Garmin), сон.
Запуск: python scripts/coverage_report.py (из корня или из контейнера).
"""

import os
import sys
from pathlib import Path
from datetime import date, timedelta
from collections import defaultdict

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from database import SessionLocal
from sqlalchemy import text

USER_ID = int(os.getenv("HEALTHVAULT_USER_ID", "895655"))
START = date(2026, 1, 6)
END = date.today()


def main():
    db = SessionLocal()
    try:
        # Все даты в диапазоне
        days = (END - START).days + 1
        dates = [START + timedelta(days=i) for i in range(days)]

        # Питание: даты с хотя бы одним приёмом
        r = db.execute(text("""
            SELECT date FROM nutrition_log
            WHERE user_id = :uid AND date >= :start AND date <= :end
            GROUP BY date
        """), {"uid": USER_ID, "start": START, "end": END})
        nutrition_dates = {row[0] for row in r.fetchall()}

        # Вес: даты с хотя бы одним замером (по дате, без времени)
        r = db.execute(text("""
            SELECT (measured_at AT TIME ZONE 'UTC')::date as d
            FROM weights WHERE user_id = :uid
            AND (measured_at AT TIME ZONE 'UTC')::date >= :start AND (measured_at AT TIME ZONE 'UTC')::date <= :end
            GROUP BY (measured_at AT TIME ZONE 'UTC')::date
        """), {"uid": USER_ID, "start": START, "end": END})
        weight_dates = {row[0] for row in r.fetchall()}

        # Витамины/добавки
        r = db.execute(text("""
            SELECT date FROM supplements_log
            WHERE user_id = :uid AND date >= :start AND date <= :end
            GROUP BY date
        """), {"uid": USER_ID, "start": START, "end": END})
        supplements_dates = {row[0] for row in r.fetchall()}

        # Активность (Garmin/другое) — шаги или калории
        r = db.execute(text("""
            SELECT date FROM activity_log
            WHERE user_id = :uid AND date >= :start AND date <= :end
            AND (steps IS NOT NULL OR active_calories IS NOT NULL)
            GROUP BY date
        """), {"uid": USER_ID, "start": START, "end": END})
        activity_dates = {row[0] for row in r.fetchall()}

        # Сон (в activity_log)
        r = db.execute(text("""
            SELECT date FROM activity_log
            WHERE user_id = :uid AND date >= :start AND date <= :end
            AND sleep_hours IS NOT NULL AND sleep_hours > 0
            GROUP BY date
        """), {"uid": USER_ID, "start": START, "end": END})
        sleep_dates = {row[0] for row in r.fetchall()}

        # Сводка по дням
        by_date = defaultdict(lambda: dict(nutrition=False, weight=False, vitamins=False, activity=False, sleep=False))
        for d in dates:
            by_date[d]["nutrition"] = d in nutrition_dates
            by_date[d]["weight"] = d in weight_dates
            by_date[d]["vitamins"] = d in supplements_dates
            by_date[d]["activity"] = d in activity_dates
            by_date[d]["sleep"] = d in sleep_dates

        # Вывод
        print("=" * 80)
        print("ПОКРЫТИЕ ДАННЫХ с 2026-01-06 по", END)
        print("=" * 80)
        print(f"Питание:     {len(nutrition_dates)} дней (из {days})")
        print(f"Вес:         {len(weight_dates)} дней (из {days})")
        print(f"Витамины:   {len(supplements_dates)} дней (из {days})")
        print(f"Активность: {len(activity_dates)} дней (из {days})")
        print(f"Сон:        {len(sleep_dates)} дней (из {days})")
        print()

        # Дни без полного покрытия (все 5 категорий)
        full = [d for d in dates if all(by_date[d].values())]
        missing_any = [d for d in dates if not all(by_date[d].values())]
        print(f"Полное покрытие (все 5): {len(full)} дней")
        print(f"Не хватает чего-то:     {len(missing_any)} дней")
        print()

        # По категориям — какие даты пропущены
        def missing_list(date_set):
            out = [d for d in dates if d not in date_set]
            return out[:7], len(out)
        for label, s in [
            ("питания", nutrition_dates), ("веса", weight_dates), ("витаминов", supplements_dates),
            ("активности", activity_dates), ("сна", sleep_dates)
        ]:
            sample, total = missing_list(s)
            tail = " ..." if total > 7 else ""
            print(f"  Даты БЕЗ {label}: {total} — {sample}{tail}")
        print()

        # Минимальные даты в БД по таблицам
        for name, q, params in [
            ("nutrition_log", "SELECT MIN(date), MAX(date), COUNT(DISTINCT date) FROM nutrition_log WHERE user_id = :uid", {"uid": USER_ID}),
            ("weights", "SELECT MIN((measured_at AT TIME ZONE 'UTC')::date), MAX((measured_at AT TIME ZONE 'UTC')::date), COUNT(*) FROM weights WHERE user_id = :uid", {"uid": USER_ID}),
            ("supplements_log", "SELECT MIN(date), MAX(date), COUNT(DISTINCT date) FROM supplements_log WHERE user_id = :uid", {"uid": USER_ID}),
            ("activity_log", "SELECT MIN(date), MAX(date), COUNT(*) FROM activity_log WHERE user_id = :uid", {"uid": USER_ID}),
        ]:
            row = db.execute(text(q), params).fetchone()
            print(f"  {name}: {row[0]} .. {row[1]}, count = {row[2]}")
        print("=" * 80)
    finally:
        db.close()


if __name__ == "__main__":
    main()
