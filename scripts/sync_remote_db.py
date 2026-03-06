#!/usr/bin/env python3
import psycopg2
import psycopg2.extras
import json
import os
from datetime import date, time, datetime
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv("DATABASE_URL", "postgresql://healthvault:dev_password_123@db:5432/healthvault")
ALEX_USER_ID = 895655


class CustomJSONEncoder(json.JSONEncoder):
    """Кастомный енкодер для дат и времени в JSON."""
    def default(self, obj):
        if isinstance(obj, (date, datetime, time)):
            return obj.isoformat()
        return super().default(obj)

def sync_data():
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        print("✅ Успешно подключились к удаленной БД")

        # 1. Nutrition Log
        cur.execute("SELECT * FROM nutrition_log WHERE user_id = %s ORDER BY date, meal_time", (ALEX_USER_ID,))
        nutrition_records = []
        for row in cur.fetchall():
            nutrition_records.append(dict(row))
            
        os.makedirs('data/nutrition', exist_ok=True)
        with open('data/nutrition/nutrition_log_remote.json', 'w', encoding='utf-8') as f:
            json.dump(nutrition_records, f, ensure_ascii=False, indent=2, cls=CustomJSONEncoder)
        print(f"✅ Сохранено {len(nutrition_records)} записей питания")

        # 2. Supplements Log
        cur.execute("SELECT * FROM supplements_log WHERE user_id = %s ORDER BY date, time", (ALEX_USER_ID,))
        supps_records = []
        for row in cur.fetchall():
            supps_records.append(dict(row))
            
        os.makedirs('data/supplements', exist_ok=True)
        with open('data/supplements/supplements_log_remote.json', 'w', encoding='utf-8') as f:
            json.dump(supps_records, f, ensure_ascii=False, indent=2, cls=CustomJSONEncoder)
        print(f"✅ Сохранено {len(supps_records)} записей добавок/витаминов")

        # 3. Zepp / OCR Weights & Body composition
        cur.execute("SELECT * FROM weights WHERE user_id = %s AND source IN ('screenshot_ocr', 'manual', 'zepp') ORDER BY measured_at", (ALEX_USER_ID,))
        weight_records = []
        for row in cur.fetchall():
            weight_records.append(dict(row))
        
        os.makedirs('data/weights', exist_ok=True)
        with open('data/weights/weights_remote.json', 'w', encoding='utf-8') as f:
            json.dump(weight_records, f, ensure_ascii=False, indent=2, cls=CustomJSONEncoder)
        print(f"✅ Сохранено {len(weight_records)} записей замеров тела (состав)")
        
        # 4. Garmin Activity Log
        cur.execute("SELECT * FROM activity_log WHERE user_id = %s ORDER BY date", (ALEX_USER_ID,))
        activity_records = []
        for row in cur.fetchall():
            activity_records.append(dict(row))
            
        os.makedirs('data/activities', exist_ok=True)
        with open('data/activities/activities_remote.json', 'w', encoding='utf-8') as f:
            json.dump(activity_records, f, ensure_ascii=False, indent=2, cls=CustomJSONEncoder)
        print(f"✅ Сохранено {len(activity_records)} записей активности (Garmin)")

        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == '__main__':
    sync_data()
