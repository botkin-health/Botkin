#!/usr/bin/env python3
"""
Скрипт для загрузки данных из Garmin Connect
Загружает все доступные данные за указанный период
"""

import os
import sys
import json
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv(Path(__file__).parent.parent.parent / '.env')

try:
    from garminconnect import Garmin
except ImportError:
    print("❌ Библиотека garminconnect не установлена")
    print("Установите: pip install garminconnect python-dotenv")
    sys.exit(1)

# Настройки
BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data" / "garmin"
EMAIL = os.getenv('GARMIN_EMAIL')
PASSWORD = os.getenv('GARMIN_PASSWORD')

def ensure_dirs():
    """Создает необходимые директории"""
    for subdir in ['activities', 'daily-summary', 'sleep', 'metrics', 'body-battery', 'stress', 'hrv']:
        (DATA_DIR / subdir).mkdir(parents=True, exist_ok=True)

def save_json(data, filepath):
    """Сохраняет данные в JSON файл"""
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)

def download_activities(client, start_date, end_date):
    """Загружает все активности за период"""
    print(f"\n📥 Загрузка активностей с {start_date} по {end_date}...")
    activities_dir = DATA_DIR / "activities"
    
    try:
        activities = client.get_activities_by_date(start_date, end_date)
        print(f"   Найдено активностей: {len(activities)}")
        
        for activity in activities:
            activity_id = activity.get('activityId')
            if not activity_id:
                continue
                
            # Сохраняем краткую информацию
            date_str = activity.get('startTimeLocal', '').split('T')[0] if activity.get('startTimeLocal') else 'unknown'
            filename = f"{date_str}_{activity_id}.json"
            save_json(activity, activities_dir / filename)
            
            # Загружаем детальную информацию об активности
            try:
                details = client.get_activity(activity_id)
                details_filename = f"{date_str}_{activity_id}_details.json"
                save_json(details, activities_dir / details_filename)
                print(f"   ✅ {activity.get('activityName', 'Activity')} - {date_str}")
            except Exception as e:
                print(f"   ⚠️  Ошибка загрузки деталей активности {activity_id}: {e}")
        
        return len(activities)
    except Exception as e:
        print(f"   ❌ Ошибка загрузки активностей: {e}")
        return 0

def download_daily_summary(client, start_date, end_date):
    """Загружает дневные сводки (шаги, калории, статистика)"""
    print(f"\n📥 Загрузка дневных сводок с {start_date} по {end_date}...")
    summary_dir = DATA_DIR / "daily-summary"
    
    current_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_dt = datetime.strptime(end_date, '%Y-%m-%d')
    count = 0
    
    while current_date <= end_dt:
        date_str = current_date.strftime('%Y-%m-%d')
        filename = f"{date_str}.json"
        filepath = summary_dir / filename
        
        # Пропускаем если уже загружено, НО если это сегодня - обновляем
        today_str = datetime.now().strftime('%Y-%m-%d')
        if filepath.exists() and date_str != today_str:
            current_date += timedelta(days=1)
            continue
        
        try:
            # Собираем данные из разных источников
            summary = {}
            
            # Статистика за день
            try:
                stats = client.get_stats(date_str)
                summary['stats'] = stats
            except:
                pass
            
            # Шаги
            try:
                steps = client.get_steps_data(date_str)
                summary['steps'] = steps
            except:
                pass
            
            # Дневные шаги (альтернативный метод)
            try:
                daily_steps = client.get_daily_steps(date_str)
                summary['daily_steps'] = daily_steps
            except:
                pass
            
            if summary:
                save_json(summary, filepath)
                count += 1
                print(f"   ✅ {date_str}")
            else:
                print(f"   ⚠️  {date_str}: нет данных")
        except Exception as e:
            print(f"   ⚠️  {date_str}: {e}")
        
        current_date += timedelta(days=1)
    
    return count

def download_sleep(client, start_date, end_date):
    """Загружает данные о сне"""
    print(f"\n📥 Загрузка данных о сне с {start_date} по {end_date}...")
    sleep_dir = DATA_DIR / "sleep"
    
    current_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_dt = datetime.strptime(end_date, '%Y-%m-%d')
    count = 0
    
    while current_date <= end_dt:
        date_str = current_date.strftime('%Y-%m-%d')
        filename = f"{date_str}.json"
        filepath = sleep_dir / filename
        
        today_str = datetime.now().strftime('%Y-%m-%d')
        if filepath.exists() and date_str != today_str:
            current_date += timedelta(days=1)
            continue
        
        try:
            sleep_data = client.get_sleep_data(date_str)
            save_json(sleep_data, filepath)
            count += 1
            print(f"   ✅ {date_str}")
        except Exception as e:
            print(f"   ⚠️  {date_str}: {e}")
        
        current_date += timedelta(days=1)
    
    return count

def download_body_battery(client, start_date, end_date):
    """Загружает данные Body Battery"""
    print(f"\n📥 Загрузка Body Battery с {start_date} по {end_date}...")
    bb_dir = DATA_DIR / "body-battery"
    
    current_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_dt = datetime.strptime(end_date, '%Y-%m-%d')
    count = 0
    
    while current_date <= end_dt:
        date_str = current_date.strftime('%Y-%m-%d')
        filename = f"{date_str}.json"
        filepath = bb_dir / filename
        
        today_str = datetime.now().strftime('%Y-%m-%d')
        if filepath.exists() and date_str != today_str:
            current_date += timedelta(days=1)
            continue
        
        try:
            bb_data = client.get_body_battery(date_str)
            save_json(bb_data, filepath)
            count += 1
            print(f"   ✅ {date_str}")
        except Exception as e:
            print(f"   ⚠️  {date_str}: {e}")
        
        current_date += timedelta(days=1)
    
    return count

def download_stress(client, start_date, end_date):
    """Загружает данные о стрессе"""
    print(f"\n📥 Загрузка данных о стрессе с {start_date} по {end_date}...")
    stress_dir = DATA_DIR / "stress"
    
    current_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_dt = datetime.strptime(end_date, '%Y-%m-%d')
    count = 0
    
    while current_date <= end_dt:
        date_str = current_date.strftime('%Y-%m-%d')
        filename = f"{date_str}.json"
        filepath = stress_dir / filename
        
        today_str = datetime.now().strftime('%Y-%m-%d')
        if filepath.exists() and date_str != today_str:
            current_date += timedelta(days=1)
            continue
        
        try:
            stress_data = client.get_stress_data(date_str)
            save_json(stress_data, filepath)
            count += 1
            print(f"   ✅ {date_str}")
        except Exception as e:
            print(f"   ⚠️  {date_str}: {e}")
        
        current_date += timedelta(days=1)
    
    return count

def download_hrv(client, start_date, end_date):
    """Загружает данные HRV"""
    print(f"\n📥 Загрузка HRV данных с {start_date} по {end_date}...")
    hrv_dir = DATA_DIR / "hrv"
    
    current_date = datetime.strptime(start_date, '%Y-%m-%d')
    end_dt = datetime.strptime(end_date, '%Y-%m-%d')
    count = 0
    
    while current_date <= end_dt:
        date_str = current_date.strftime('%Y-%m-%d')
        filename = f"{date_str}.json"
        filepath = hrv_dir / filename
        
        today_str = datetime.now().strftime('%Y-%m-%d')
        if filepath.exists() and date_str != today_str:
            current_date += timedelta(days=1)
            continue
        
        try:
            hrv_data = client.get_hrv_data(date_str)
            save_json(hrv_data, filepath)
            count += 1
            print(f"   ✅ {date_str}")
        except Exception as e:
            print(f"   ⚠️  {date_str}: {e}")
        
        current_date += timedelta(days=1)
    
    return count

def main():
    if not EMAIL or not PASSWORD:
        print("❌ Ошибка: GARMIN_EMAIL и GARMIN_PASSWORD должны быть в .env файле")
        sys.exit(1)
    
    ensure_dirs()
    
    # Подключение к Garmin Connect
    print("🔐 Подключение к Garmin Connect...")
    try:
        client = Garmin(EMAIL, PASSWORD)
        client.login()
        print("✅ Успешный вход в Garmin Connect")
    except Exception as e:
        print(f"❌ Ошибка входа: {e}")
        sys.exit(1)
    
    # Получаем информацию о пользователе
    try:
        user_profile = client.get_user_profile()
        print(f"👤 Пользователь: {user_profile.get('displayName', 'Unknown')}")
    except:
        pass
    
    # Определяем период (последний год)
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    
    print(f"\n📅 Период загрузки: {start_date} - {end_date}")
    
    # Загружаем данные
    results = {
        'activities': download_activities(client, start_date, end_date),
        'daily_summary': download_daily_summary(client, start_date, end_date),
        'sleep': download_sleep(client, start_date, end_date),
        'body_battery': download_body_battery(client, start_date, end_date),
        'stress': download_stress(client, start_date, end_date),
        'hrv': download_hrv(client, start_date, end_date),
    }
    
    # Сохраняем метаданные о загрузке
    metadata = {
        'download_date': datetime.now().isoformat(),
        'period': {'start': start_date, 'end': end_date},
        'results': results
    }
    save_json(metadata, DATA_DIR / 'download_metadata.json')
    
    print(f"\n{'='*60}")
    print("✅ ЗАГРУЗКА ЗАВЕРШЕНА")
    print(f"{'='*60}")
    print(f"Активности: {results['activities']}")
    print(f"Дневные сводки: {results['daily_summary']}")
    print(f"Сон: {results['sleep']}")
    print(f"Body Battery: {results['body_battery']}")
    print(f"Stress: {results['stress']}")
    print(f"HRV: {results['hrv']}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()

