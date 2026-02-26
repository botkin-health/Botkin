#!/usr/bin/env python3
"""
Печать записей питания пользователя за сегодня (или за указанную дату).
Использование:
  python scripts/print_nutrition_today.py [telegram_id] [YYYY-MM-DD]
  telegram_id по умолчанию 485132 (Ника), дата — сегодня.
Для продакшена на сервере:
  docker exec -i healthvault_bot python scripts/print_nutrition_today.py 485132
"""
import sys
from datetime import date, datetime
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

def main():
    user_id = int(sys.argv[1]) if len(sys.argv) > 1 else 485132
    day_str = sys.argv[2] if len(sys.argv) > 2 else date.today().isoformat()
    try:
        day = datetime.strptime(day_str, "%Y-%m-%d").date()
    except ValueError:
        print("Дата в формате YYYY-MM-DD")
        return 2

    from database import SessionLocal, get_nutrition_logs_by_date

    db = SessionLocal()
    try:
        logs = get_nutrition_logs_by_date(db, user_id, day)
    finally:
        db.close()

    print(f"User {user_id}, дата {day}. Записей: {len(logs)}\n")
    for log in logs:
        t = log.meal_time.strftime("%H:%M") if log.meal_time else "—"
        tot = log.totals or {}
        print(f"  {t} | {log.meal_name or '—'}")
        print(f"      КБЖУ: {tot.get('calories', 0)} ккал, Б:{tot.get('protein', 0)} Ж:{tot.get('fats', 0)} У:{tot.get('carbs', 0)}")
        for it in (log.items or []):
            print(f"      • {it.get('food', '?')} {it.get('amount', 0)}г — {it.get('calories', 0)} ккал")
        print()
    return 0

if __name__ == "__main__":
    sys.exit(main())
