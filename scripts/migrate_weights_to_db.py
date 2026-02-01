#!/usr/bin/env python3
"""
Миграция весов из JSON файлов в PostgreSQL
"""

import json
import psycopg2
from pathlib import Path
from datetime import datetime

# Подключение к БД
conn = psycopg2.connect(
    "postgresql://healthvault:dev_password_123@localhost:5432/healthvault"
)
cur = conn.cursor()

user_id = 895655
weights_dir = Path("data/weights")

# Счетчики
migrated = 0
errors = 0

print("Начинаю миграцию весов...")

for json_file in sorted(weights_dir.glob("*.json")):
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Извлекаем данные
        weight = data.get('weight')
        date_str = data.get('date')
        time_str = data.get('time', '08:00')
        
        # Дополнительные метрики
        body_fat = data.get('body_fat_percentage')
        visceral_fat = data.get('visceral_fat')
        muscle_mass = data.get('muscle_mass')
        bone_mass = data.get('bone_mass')
        water_percentage = data.get('water_percentage')
        bmr = data.get('bmr')
        metabolic_age = data.get('metabolic_age')
        source = data.get('source', 'json_import')
        
        # Формируем timestamp
        measured_at = f"{date_str} {time_str}:00+03"
        
        # Вставка в БД
        cur.execute("""
            INSERT INTO weights (
                user_id, measured_at, weight, 
                body_fat, visceral_fat, muscle_mass, bone_mass,
                water_percentage, bmr, metabolic_age, source,
                created_at
            ) VALUES (
                %s, %s::timestamptz, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s::timestamptz
            )
            ON CONFLICT (user_id, measured_at) DO NOTHING
        """, (
            user_id, measured_at, weight,
            body_fat, visceral_fat, muscle_mass, bone_mass,
            water_percentage, bmr, metabolic_age, source,
            measured_at
        ))
        
        if cur.rowcount > 0:
            migrated += 1
            print(f"✅ {json_file.name}: {weight} кг ({date_str})")
        else:
            print(f"⏭️  {json_file.name}: уже существует")
            
    except Exception as e:
        errors += 1
        print(f"❌ {json_file.name}: {e}")

conn.commit()
cur.close()
conn.close()

print(f"\n{'='*50}")
print(f"Миграция завершена!")
print(f"Мигрировано: {migrated}")
print(f"Ошибок: {errors}")
print(f"{'='*50}")
