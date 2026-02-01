#!/usr/bin/env python3
"""
Скрипт миграции данных из JSON файлов в PostgreSQL
Использование: python scripts/migrate_to_postgres.py
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import SessionLocal, init_db
from database.models import User, NutritionLog, Weight, SupplementLog, ActivityLog, BloodTest

# Путь к данным
DATA_DIR = Path(__file__).parent.parent / "data"

# ID пользователя (ваш реальный Telegram ID из логов)
YOUR_TELEGRAM_ID = 895655  # Alex Lyskovsky


def migrate_user():
    """Создаёт пользователя-администратора"""
    print("\n=== 1. Creating Admin User ===")
    
    db = SessionLocal()
    try:
        # Проверяем, существует ли уже
        existing = db.query(User).filter(User.telegram_id == YOUR_TELEGRAM_ID).first()
        if existing:
            print(f"✅ User {YOUR_TELEGRAM_ID} already exists. Skipping.")
            return existing
        
        user = User(
            telegram_id=YOUR_TELEGRAM_ID,
            first_name="Alex",
            username="alexlyskovsky",
            role="admin",
            is_active=True
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"✅ Created admin user: {user.telegram_id} ({user.first_name})")
        return user
    finally:
        db.close()


def migrate_nutrition_log():
    """Мигрирует данные питания из nutrition_log.json"""
    print("\n=== 2. Migrating Nutrition Log ===")
    
    nutrition_file = DATA_DIR / "nutrition" / "nutrition_log.json"
    if not nutrition_file.exists():
        print(f"⚠️  File not found: {nutrition_file}")
        return
    
    db = SessionLocal()
    try:
        data = json.loads(nutrition_file.read_text(encoding='utf-8'))
        count = 0
        
        # Structure: {"metadata": {...}, "entries": [{"date": "...", "meals": [...]}]}
        entries = data.get('entries', [])
        
        for day_entry in entries:
            date_str = day_entry.get('date')
            if not date_str:
                continue
                
            for meal in day_entry.get('meals', []):
                meal_name = meal.get('meal', 'Прием пищи')
                time_str = meal.get('time')
                
                # Skip if already exists
                meal_time = datetime.strptime(time_str, '%H:%M').time() if time_str else None
                existing = db.query(NutritionLog).filter(
                    NutritionLog.user_id == YOUR_TELEGRAM_ID,
                    NutritionLog.date == datetime.strptime(date_str, '%Y-%m-%d').date(),
                    NutritionLog.meal_time == meal_time,
                    NutritionLog.meal_name == meal_name
                ).first()
                
                if existing:
                    continue
                
                log = NutritionLog(
                    user_id=YOUR_TELEGRAM_ID,
                    date=datetime.strptime(date_str, '%Y-%m-%d').date(),
                    meal_time=meal_time,
                    meal_name=meal_name,
                    items=meal.get('items', []),
                    totals=meal.get('totals', {}),
                    photo_paths=meal.get('photo_paths', [])
                )
                db.add(log)
                count += 1
        
        db.commit()
        print(f"✅ Migrated {count} nutrition log entries")
    except Exception as e:
        print(f"❌ Error migrating nutrition log: {e}")
        db.rollback()
    finally:
        db.close()


def migrate_weights():
    """Мигрирует данные весов из data/weights/*.json"""
    print("\n=== 3. Migrating Weights ===")
    
    weights_dir = DATA_DIR / "weights"
    if not weights_dir.exists():
        print(f"⚠️  Directory not found: {weights_dir}")
        return
    
    db = SessionLocal()
    try:
        count = 0
        skipped = 0
        
        for weight_file in sorted(weights_dir.glob("*.json")):
            # Skip non-weight files
            if weight_file.name in ['apple_health_weights.json', 'zepp_reminders.json']:
                continue
                
            data = json.loads(weight_file.read_text(encoding='utf-8'))
            
            # Data is a list of entries
            if not isinstance(data, list):
                data = [data]
                
            for entry in data:
                date_val = entry.get('date')
                if not date_val:
                    skipped += 1
                    continue
                
                # Handle both string and float dates
                if isinstance(date_val, (int, float)):
                    skipped += 1
                    continue
                    
                try:
                    measured_at = datetime.strptime(date_val, '%Y-%m-%d %H:%M')
                except ValueError:
                    skipped += 1
                    continue
                
                # Skip if already exists
                existing = db.query(Weight).filter(
                    Weight.user_id == YOUR_TELEGRAM_ID,
                    Weight.measured_at == measured_at
                ).first()
                
                if existing:
                    continue
                
                # Get weight value
                weight_val = entry.get('weight')
                if not weight_val:
                    skipped += 1
                    continue
                
                weight = Weight(
                    user_id=YOUR_TELEGRAM_ID,
                    measured_at=measured_at,
                    weight=weight_val,
                    body_fat=entry.get('body_fat'),
                    muscle_mass=entry.get('muscle'),
                    water=entry.get('water'),
                    bmi=entry.get('bmi'),
                    visceral_fat=entry.get('visceral_fat'),
                    bone_mass=entry.get('bone_mass'),
                    source=entry.get('source', 'zepp')
                )
                db.add(weight)
                count += 1
        
        db.commit()
        print(f"✅ Migrated {count} weight entries (skipped {skipped} invalid entries)")
    except Exception as e:
        print(f"❌ Error migrating weights: {e}")
        db.rollback()
    finally:
        db.close()


def migrate_supplements():
    """Мигрирует данные добавок из supplements_log.json"""
    print("\n=== 4. Migrating Supplements ===")
    
    supplements_file = DATA_DIR / "supplements_log.json"
    if not supplements_file.exists():
        print(f"⚠️  File not found: {supplements_file}")
        return
    
    db = SessionLocal()
    try:
        data = json.loads(supplements_file.read_text(encoding='utf-8'))
        count = 0
        
        # Structure: {"entries": [{"date": "...", "items": [{"name": "...", "time": "..."}]}]}
        entries = data.get('entries', [])
        
        for day_entry in entries:
            date_str = day_entry.get('date')
            if not date_str:
                continue
                
            for item in day_entry.get('items', []):
                supp = SupplementLog(
                    user_id=YOUR_TELEGRAM_ID,
                    date=datetime.strptime(date_str, '%Y-%m-%d').date(),
                    time=datetime.strptime(item['time'], '%H:%M').time() if item.get('time') else None,
                    supplement_name=item.get('name', 'Unknown'),
                    dosage=item.get('dosage')
                )
                db.add(supp)
                count += 1
        
        db.commit()
        print(f"✅ Migrated {count} supplement entries")
    except Exception as e:
        print(f"❌ Error migrating supplements: {e}")
        db.rollback()
    finally:
        db.close()


def migrate_garmin_data():
    """Мигрирует данные Garmin из data/garmin/daily-summary/*.json"""
    print("\n=== 5. Migrating Garmin Activity Data ===")
    
    garmin_dir = DATA_DIR / "garmin" / "daily-summary"
    if not garmin_dir.exists():
        print(f"⚠️  Directory not found: {garmin_dir}")
        return
    
    db = SessionLocal()
    try:
        count = 0
        
        for garmin_file in sorted(garmin_dir.glob("*.json")):
            # Parse date from filename (YYYY-MM-DD.json)
            date_str = garmin_file.stem
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
            
            # Skip if already exists
            existing = db.query(ActivityLog).filter(
                ActivityLog.user_id == YOUR_TELEGRAM_ID,
                ActivityLog.date == date
            ).first()
            
            if existing:
                continue
            
            data = json.loads(garmin_file.read_text(encoding='utf-8'))
            stats = data.get('stats', {})
            
            activity = ActivityLog(
                user_id=YOUR_TELEGRAM_ID,
                date=date,
                steps=stats.get('totalSteps'),
                active_calories=stats.get('activeKilocalories'),
                total_calories=stats.get('totalKilocalories'),
                bmr_calories=stats.get('bmrKilocalories'),
                distance_km=stats.get('totalDistanceMeters', 0) / 1000 if stats.get('totalDistanceMeters') else None,
                sleep_hours=stats.get('sleepingSeconds', 0) / 3600 if stats.get('sleepingSeconds') else None,
                heart_rate_avg=stats.get('averageHeartRate'),
                hrv=stats.get('averageStressLevel'),  # Adjust field names as needed
                source='garmin',
                raw_data=data  # Store full payload for future reference
            )
            db.add(activity)
            count += 1
        
        db.commit()
        print(f"✅ Migrated {count} Garmin activity entries")
    except Exception as e:
        print(f"❌ Error migrating Garmin data: {e}")
        db.rollback()
    finally:
        db.close()


def main():
    print("=" * 60)
    print("  HEALTHVAULT DATA MIGRATION")
    print("=" * 60)
    print(f"\nTarget User ID: {YOUR_TELEGRAM_ID}")
    print(f"Data Directory: {DATA_DIR}")
    
    # Initialize database (create tables)
    print("\n=== 0. Initializing Database ===")
    try:
        init_db()
        print("✅ Database initialized (tables created)")
    except Exception as e:
        print(f"❌ Error initializing database: {e}")
        return
    
    # Run migrations
    migrate_user()
    migrate_nutrition_log()
    migrate_weights()
    migrate_supplements()
    migrate_garmin_data()
    
    print("\n" + "=" * 60)
    print("  MIGRATION COMPLETE!")
    print("=" * 60)
    print("\n✅ Your data has been migrated to PostgreSQL.")
    print("   You can now start the bot with the new database backend.")


if __name__ == "__main__":
    main()
