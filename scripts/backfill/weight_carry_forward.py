#!/usr/bin/env python3
"""
Заполнение пропусков веса: для каждого дня без замера в диапазоне 2026-01-06..сегодня
вставляется запись с последним известным весом (carry-forward), source='carry_forward'.
Так получается полное покрытие по дням для отчётов/графиков.
Запуск: python scripts/backfill_weight_carry_forward.py
"""

import os
import sys
from pathlib import Path
from datetime import date, timedelta, datetime

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from database import SessionLocal
from database.crud import create_weight, get_weights_by_period
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

USER_ID = int(os.getenv("HEALTHVAULT_USER_ID", "895655"))
START = date(2026, 1, 6)
END = date.today()


def main():
    db = SessionLocal()
    try:
        # Даты, где уже есть хотя бы один вес (по дате в UTC)
        r = db.execute(text("""
            SELECT DISTINCT (measured_at AT TIME ZONE 'UTC')::date
            FROM weights WHERE user_id = :uid
            AND (measured_at AT TIME ZONE 'UTC')::date >= :start
            AND (measured_at AT TIME ZONE 'UTC')::date <= :end
        """), {"uid": USER_ID, "start": START, "end": END})
        has_weight = set(row[0] for row in r.fetchall())
        days = (END - START).days + 1
        missing_dates = [START + timedelta(days=i) for i in range(days) if (START + timedelta(days=i)) not in has_weight]
        if not missing_dates:
            print("Вес уже есть за все дни в диапазоне.")
            return
        # Все веса до END, упорядочены по убыванию даты
        r = db.execute(text("""
            SELECT weight, (measured_at AT TIME ZONE 'UTC')::date as d
            FROM weights WHERE user_id = :uid AND (measured_at AT TIME ZONE 'UTC')::date <= :end
            ORDER BY measured_at DESC
        """), {"uid": USER_ID, "end": END})
        rows = r.fetchall()
        if not rows:
            print("Нет ни одной записи веса в БД — нечего переносить.")
            return
        # Для каждой недостающей даты — последний вес на момент той даты (последний с measured_at <= конец этого дня)
        added = 0
        for d in sorted(missing_dates):
            # последний вес с датой <= d
            last_weight = None
            for w, wdate in rows:
                if wdate <= d:
                    last_weight = w
                    break
            if last_weight is None:
                continue
            # Вставка в полдень UTC, чтобы не конфликтовать с реальными замерами
            measured_at = datetime(d.year, d.month, d.day, 12, 0, 0)
            try:
                create_weight(
                    db, USER_ID, measured_at,
                    weight=float(last_weight),
                    source="carry_forward",
                )
                added += 1
            except IntegrityError:
                db.rollback()
        print(f"Вес (carry-forward): добавлено {added} дней для полного покрытия.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
