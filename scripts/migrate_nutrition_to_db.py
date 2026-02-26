#!/usr/bin/env python3
"""
Миграция питания из data/nutrition/nutrition_log.json в PostgreSQL (таблица nutrition_log).
Использует database.crud.create_nutrition_log. Без дублей (unique: user_id, date, meal_time, meal_name).
Запуск из корня: python scripts/migrate_nutrition_to_db.py
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime, time as dt_time

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from database import SessionLocal
from database.crud import create_nutrition_log
from sqlalchemy.exc import IntegrityError

USER_ID = int(os.getenv("HEALTHVAULT_USER_ID", "895655"))
NUTRITION_FILE = project_root / "data" / "nutrition" / "nutrition_log.json"


def parse_time(s):
    """'12:00' -> time(12, 0)."""
    if not s:
        return None
    try:
        parts = str(s).strip()[:5].split(":")
        return dt_time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
    except (ValueError, IndexError):
        return None


def main():
    if not NUTRITION_FILE.exists():
        print(f"❌ Файл не найден: {NUTRITION_FILE}")
        sys.exit(1)

    from sqlalchemy import text
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
    except Exception as e:
        print(f"❌ Не удаётся подключиться к БД: {e}")
        print("   Запустите PostgreSQL или проверьте DATABASE_URL в .env")
        sys.exit(1)

    data = json.loads(NUTRITION_FILE.read_text(encoding="utf-8"))
    entries = data.get("entries", [])
    if not entries:
        print("Нет записей в JSON.")
        db.close()
        return

    migrated = 0
    skipped = 0
    errors = 0

    for entry in entries:
        date_str = entry.get("date")
        if not date_str:
            continue
        try:
            log_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            errors += 1
            continue

        for meal in entry.get("meals", []):
            meal_name = (meal.get("meal") or "Приём пищи").strip() or "Приём пищи"
            meal_time = parse_time(meal.get("time"))
            raw_items = meal.get("items", [])

            items = []
            totals = {"calories": 0.0, "protein": 0.0, "fats": 0.0, "carbs": 0.0}
            for it in raw_items:
                items.append({
                    "food": it.get("food", "?"),
                    "amount": it.get("amount", 0),
                    "unit": it.get("unit", "г"),
                    "calories": int(round(it.get("calories", 0) or 0)),
                    "protein": int(round(it.get("protein", 0) or 0)),
                    "fats": int(round(it.get("fats", 0) or 0)),
                    "carbs": int(round(it.get("carbs", 0) or 0)),
                })
                totals["calories"] += (it.get("calories") or 0)
                totals["protein"] += (it.get("protein") or 0)
                totals["fats"] += (it.get("fats") or 0)
                totals["carbs"] += (it.get("carbs") or 0)

            totals = {k: int(round(v)) for k, v in totals.items()}

            try:
                create_nutrition_log(
                    db,
                    user_id=USER_ID,
                    date=log_date,
                    meal_time=meal_time,
                    meal_name=meal_name,
                    items=items,
                    totals=totals,
                    photo_paths=None,
                )
                migrated += 1
            except IntegrityError:
                db.rollback()
                skipped += 1
            except Exception as e:
                db.rollback()
                errors += 1
                print(f"  ❌ {log_date} {meal_name}: {e}")

    db.close()
    print(f"Питание: добавлено {migrated}, дубликатов пропущено {skipped}, ошибок {errors}")


if __name__ == "__main__":
    main()
