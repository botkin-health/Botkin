#!/usr/bin/env python3
"""
Миграция данных Garmin из JSON файлов в PostgreSQL
Обрабатывает daily_stats (основные данные) и activities (детали тренировок)
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import SessionLocal, create_or_update_activity

def parse_date_from_filename(filename: str) -> Optional[datetime]:
    """Извлекает дату из имени файла"""
    try:
        # Формат: "2026-01-24.json" или "2026-01-24 12:00:00_21648459335.json"
        date_str = filename.split('.')[0].split('_')[0].strip()
        return datetime.strptime(date_str, '%Y-%m-%d')
    except Exception as e:
        print(f"⚠️  Не удалось распарсить дату из {filename}: {e}")
        return None

def migrate_daily_stats(user_id: int = 895655):
    """Мигрирует данные из data/garmin/stats/*.json"""
    
    db = SessionLocal()
    stats_dir = Path("data/garmin/stats")
    
    if not stats_dir.exists():
        print(f"❌ Папка {stats_dir} не найдена")
        return 0, 0
    
    migrated = 0
    errors = 0
    
    json_files = sorted(stats_dir.glob("*.json"))
    total_files = len(json_files)
    
    print(f"\n📊 Миграция stats: найдено {total_files} файлов")

    
    for json_file in json_files:
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Извлечь дату
            date_obj = parse_date_from_filename(json_file.name)
            if not date_obj:
                errors += 1
                continue
            
            # Извлечь данные
            steps = data.get('totalSteps') or data.get('dailyStepCount')
            active_cal = data.get('activeKilocalories')
            total_cal = data.get('totalKilocalories')
            bmr_cal = data.get('bmrKilocalories') or data.get('wellnessKilocalories')
            distance_m = data.get('totalDistanceMeters')
            
            # Сохранить в БД
            create_or_update_activity(
                db=db,
                user_id=user_id,
                date=date_obj.date(),
                steps=steps,
                active_calories=active_cal,
                total_calories=total_cal,
                bmr_calories=bmr_cal,
                distance_km=(distance_m / 1000.0) if distance_m else None,
                source='json_import_stats',
                raw_data=data
            )
            
            migrated += 1
            
            if migrated % 10 == 0:
                print(f"  ✅ {migrated}/{total_files} файлов")
                db.commit()  # Commit каждые 10 записей
                
        except Exception as e:
            errors += 1
            print(f"  ❌ {json_file.name}: {e}")
    
    db.commit()
    db.close()
    
    return migrated, errors

def migrate_activities(user_id: int = 895655):
    """Мигрирует данные из data/garmin/activities/*.json (дополнительно)"""
    
    db = SessionLocal()
    activities_dir = Path("data/garmin/activities")
    
    if not activities_dir.exists():
        print(f"❌ Папка {activities_dir} не найдена")
        return 0, 0
    
    updated = 0
    errors = 0
    
    json_files = sorted(activities_dir.glob("*.json"))
    total_files = len(json_files)
    
    print(f"\n🏃 Обновление из activities: найдено {total_files} файлов")
    
    # Группируем по датам (может быть несколько активностей в день)
    activities_by_date: Dict[str, list] = {}
    
    for json_file in json_files:
        try:
            date_obj = parse_date_from_filename(json_file.name)
            if not date_obj:
                continue
            
            date_key = date_obj.strftime('%Y-%m-%d')
            
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if date_key not in activities_by_date:
                activities_by_date[date_key] = []
            
            activities_by_date[date_key].append(data)
            
        except Exception as e:
            errors += 1
            print(f"  ❌ {json_file.name}: {e}")
    
    # Обновляем записи в БД дополнительными данными
    for date_str, activities in activities_by_date.items():
        try:
            # Агрегируем данные за день
            total_calories_from_activities = sum(
                a.get('calories', 0) for a in activities
            )
            
            # Можно добавить логику обновления, если нужно
            # Пока просто считаем
            updated += 1
            
        except Exception as e:
            errors += 1
            print(f"  ❌ {date_str}: {e}")
    
    db.close()
    
    return updated, errors

def main():
    """Основная функция миграции"""
    
    print("="*60)
    print("🔄 МИГРАЦИЯ ДАННЫХ GARMIN ИЗ JSON В POSTGRESQL")
    print("="*60)
    
    user_id = 895655
    
    # Фаза 1: Мигрировать daily_stats (основные данные)
    migrated_stats, errors_stats = migrate_daily_stats(user_id)
    
    # Фаза 2: Обновить из activities (опционально)
    # updated_activities, errors_activities = migrate_activities(user_id)
    
    print("\n" + "="*60)
    print("✅ МИГРАЦИЯ ЗАВЕРШЕНА")
    print("="*60)
    print(f"Daily Stats: {migrated_stats} мигрировано, {errors_stats} ошибок")
    # print(f"Activities: {updated_activities} обновлено, {errors_activities} ошибок")
    
    # Проверка результата
    from database import SessionLocal
    db = SessionLocal()
    
    result = db.execute("""
        SELECT 
            COUNT(*) as total_days,
            MIN(date) as first_date,
            MAX(date) as last_date,
            AVG(active_calories) as avg_active_cal,
            AVG(steps) as avg_steps
        FROM activity_log
        WHERE user_id = :user_id
    """, {"user_id": user_id}).fetchone()
    
    db.close()
    
    if result:
        print(f"\n📊 СТАТИСТИКА В БД:")
        print(f"  Всего дней: {result[0]}")
        print(f"  Период: {result[1]} - {result[2]}")
        print(f"  Средние активные калории: {result[3]:.0f} ккал")
        print(f"  Средние шаги: {result[4]:.0f}")
    
    print("\n🎉 Готово! Проверьте командой /day в боте")

if __name__ == "__main__":
    main()
