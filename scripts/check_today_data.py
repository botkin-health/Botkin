
#!/usr/bin/env python3
"""
Скрипт проверки данных в базе за сегодня
"""
import sys
from pathlib import Path
from datetime import date
from sqlalchemy import text

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import SessionLocal, get_activity_by_date, get_nutrition_totals_by_date

from datetime import date, timedelta

def check_date(target_date):
    print(f"\n🔎 Проверка данных за {target_date}...")
    
    db = SessionLocal()
    try:
        # 1. Activity
        activity = get_activity_by_date(db, 895655, target_date)
        print("🏃‍♂️ АКТИВНОСТЬ (ActivityLog):")
        if activity:
            print(f"   ID: {activity.id}")
            print(f"   Active Calories: {activity.active_calories}")
            print(f"   Total Calories: {activity.total_calories}")
            print(f"   Steps: {activity.steps}")
            print(f"   Synced At: {activity.synced_at}")
        else:
            print("   ❌ Запись не найдена!")
            
        print("-" * 30)
            
        # 2. Nutrition
        totals = get_nutrition_totals_by_date(db, 895655, target_date)
        print("🥦 ПИТАНИЕ (NutritionLog Totals):")
        print(f"   Calories: {totals.get('calories')}")
        print(f"   Protein: {totals.get('protein')}")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    finally:
        db.close()

def check_data():
    today = date.today()
    check_date(today)
    
    yesterday = today - timedelta(days=1)
    check_date(yesterday)

if __name__ == "__main__":
    check_data()
