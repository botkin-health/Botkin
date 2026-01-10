#!/usr/bin/env python3
"""
Скрипт для парсинга экспортированных данных из SleepCycle
Ожидает CSV файл экспорта из приложения SleepCycle
"""

import os
import sys
import json
import csv
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

BASE_DIR = Path(__file__).parent.parent.parent
EXPORT_DIR = BASE_DIR / "data" / "sleepcycle" / "export"
PARSED_DIR = BASE_DIR / "data" / "sleepcycle" / "parsed"
DAILY_DIR = BASE_DIR / "data" / "sleepcycle" / "daily"
KNOWLEDGE_BASE = BASE_DIR / "knowledge_base.json"

# Пути для поиска экспортированного файла
DOWNLOADS_DIRS = [
    Path.home() / "Загрузки",
    Path.home() / "Downloads"
]

def ensure_dirs():
    """Создает необходимые директории"""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    DAILY_DIR.mkdir(parents=True, exist_ok=True)

def parse_sleepcycle_csv(csv_file):
    """Парсит CSV файл экспорта SleepCycle"""
    print(f"📖 Парсинг {csv_file.name}...")
    
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=';')
            records = list(reader)
    except Exception as e:
        print(f"❌ Ошибка чтения CSV: {e}")
        return None
    
    if not records:
        print("❌ CSV файл пуст")
        return None
    
    # Определяем дату последнего года (свежие данные)
    one_year_ago = datetime.now() - timedelta(days=365)
    
    # Структура данных
    all_records = []
    fresh_records = []
    historical_records = []
    
    for record in records:
        try:
            # Парсим дату начала сна
            start_str = record.get('Start', '')
            if not start_str:
                continue
            
            start_date = datetime.strptime(start_str, '%Y-%m-%d %H:%M:%S')
            date_str = start_date.strftime('%Y-%m-%d')
            
            # Преобразуем запись в нужный формат
            parsed_record = {
                'Start': start_str,
                'End': record.get('End', ''),
                'Sleep Quality': record.get('Sleep Quality', ''),
                'Regularity': record.get('Regularity', ''),
                'Awake (seconds)': record.get('Awake (seconds)', ''),
                'Dream (seconds)': record.get('Dream (seconds)', ''),
                'Light (seconds)': record.get('Light (seconds)', ''),
                'Deep (seconds)': record.get('Deep (seconds)', ''),
                'Mood': record.get('Mood', ''),
                'Heart rate (bpm)': record.get('Heart rate (bpm)', ''),
                'Steps': record.get('Steps', ''),
                'Alarm mode': record.get('Alarm mode', ''),
                'Air Pressure (Pa)': record.get('Air Pressure (Pa)', ''),
                'City': record.get('City', ''),
                'Movements per hour': record.get('Movements per hour', ''),
                'Time in bed (seconds)': record.get('Time in bed (seconds)', ''),
                'Time asleep (seconds)': record.get('Time asleep (seconds)', ''),
                'Time before sleep (seconds)': record.get('Time before sleep (seconds)', ''),
                'Window start': record.get('Window start', ''),
                'Window stop': record.get('Window stop', ''),
                'Snore time (seconds)': record.get('Snore time (seconds)', ''),
                'Weather temperature (°C)': record.get('Weather temperature (°C)', ''),
                'Weather type': record.get('Weather type', ''),
                'Notes': record.get('Notes', ''),
                'Body temperature deviation (degrees Celsius)': record.get('Body temperature deviation (degrees Celsius)', ''),
                'Ambient Noise (dB)': record.get('Ambient Noise (dB)', ''),
                'Respiratory rate (breaths per minute)': record.get('Respiratory rate (breaths per minute)', ''),
                'Coughs (per hour)': record.get('Coughs (per hour)', ''),
                'Breathing disruptions (per hour)': record.get('Breathing disruptions (per hour)', ''),
            }
            
            all_records.append(parsed_record)
            
            # Разделяем на свежие и исторические
            if start_date >= one_year_ago:
                fresh_records.append((date_str, parsed_record))
            else:
                historical_records.append(parsed_record)
                
        except Exception as e:
            print(f"⚠️  Ошибка парсинга записи: {e}")
            continue
    
    # Находим последнюю дату
    last_record_date = None
    if all_records:
        try:
            last_start = max([datetime.strptime(r['Start'], '%Y-%m-%d %H:%M:%S') for r in all_records if r.get('Start')])
            last_record_date = last_start.strftime('%Y-%m-%d')
        except:
            pass
    
    data = {
        'export_date': datetime.now().strftime('%Y-%m-%d'),
        'source_file': csv_file.name,
        'total_records': len(all_records),
        'fresh_records_count': len(fresh_records),
        'historical_records_count': len(historical_records),
        'records': all_records,
        'last_record_date': last_record_date
    }
    
    return data, fresh_records

def create_daily_json(date_str, record):
    """Создает JSON файл для конкретной даты"""
    try:
        start_time = record.get('Start', '')
        end_time = record.get('End', '')
        
        # Парсим значения
        sleep_quality = record.get('Sleep Quality', '').replace('%', '') if record.get('Sleep Quality') else '0'
        regularity = record.get('Regularity', '').replace('%', '') if record.get('Regularity') else '0'
        
        time_in_bed_seconds = float(record.get('Time in bed (seconds)', 0) or 0)
        time_asleep_seconds = float(record.get('Time asleep (seconds)', 0) or 0)
        snore_time_seconds = float(record.get('Snore time (seconds)', 0) or 0)
        
        awake_seconds = float(record.get('Awake (seconds)', 0) or 0)
        dream_seconds = float(record.get('Dream (seconds)', 0) or 0)
        light_seconds = float(record.get('Light (seconds)', 0) or 0)
        deep_seconds = float(record.get('Deep (seconds)', 0) or 0)
        
        heart_rate_str = record.get('Heart rate (bpm)', '0')
        heart_rate = int(float(heart_rate_str)) if heart_rate_str and heart_rate_str != '0' else None
        
        steps = int(float(record.get('Steps', 0) or 0))
        mood = record.get('Mood', 'Not set')
        notes = record.get('Notes', '')
        
        # Конвертируем в часы
        time_in_bed_hours = round(time_in_bed_seconds / 3600, 2)
        time_asleep_hours = round(time_asleep_seconds / 3600, 2)
        snore_time_minutes = round(snore_time_seconds / 60, 2)
        
        awake_hours = round(awake_seconds / 3600, 2)
        dream_hours = round(dream_seconds / 3600, 2)
        light_hours = round(light_seconds / 3600, 2)
        deep_hours = round(deep_seconds / 3600, 2)
        
        daily_data = {
            'sleepcycle': {
                'source': 'sleepcycle',
                'date': date_str,
                'start_time': start_time,
                'end_time': end_time,
                'sleep_quality': sleep_quality,
                'regularity': regularity,
                'time_in_bed_seconds': time_in_bed_seconds,
                'time_asleep_seconds': time_asleep_seconds,
                'time_in_bed_hours': time_in_bed_hours,
                'time_asleep_hours': time_asleep_hours,
                'snore_time_seconds': snore_time_seconds,
                'snore_time_minutes': snore_time_minutes,
                'heart_rate': heart_rate,
                'steps': steps,
                'mood': mood,
                'notes': notes,
                'phases': {
                    'awake_seconds': awake_seconds,
                    'dream_seconds': dream_seconds,
                    'light_seconds': light_seconds,
                    'deep_seconds': deep_seconds,
                    'awake_hours': awake_hours,
                    'dream_hours': dream_hours,
                    'light_hours': light_hours,
                    'deep_hours': deep_hours
                },
                'imported_at': datetime.now().isoformat()
            }
        }
        
        return daily_data
        
    except Exception as e:
        print(f"⚠️  Ошибка создания JSON для {date_str}: {e}")
        return None

def update_knowledge_base(fresh_records, export_date, total_records, historical_count, last_record_date):
    """Обновляет knowledge_base.json с новыми данными SleepCycle"""
    try:
        # Загружаем существующий knowledge_base
        if KNOWLEDGE_BASE.exists():
            with open(KNOWLEDGE_BASE, 'r', encoding='utf-8') as f:
                kb = json.load(f)
        else:
            kb = {}
        
        # Обновляем секцию sleepcycle
        fresh_data = []
        for date_str, record in fresh_records:
            daily_json = create_daily_json(date_str, record)
            if daily_json:
                sleep_data = daily_json['sleepcycle']
                fresh_data.append({
                    'date': date_str,
                    'sleep_quality': sleep_data['sleep_quality'],
                    'time_asleep_hours': sleep_data['time_asleep_hours'],
                    'time_in_bed_hours': sleep_data['time_in_bed_hours'],
                    'snore_time_minutes': sleep_data['snore_time_minutes'],
                    'heart_rate': sleep_data['heart_rate'],
                    'mood': sleep_data['mood'],
                    'notes': sleep_data['notes'],
                    'file': f"sleepcycle/daily/{date_str}.json"
                })
        
        # Сортируем по дате (новые первыми)
        fresh_data.sort(key=lambda x: x['date'], reverse=True)
        
        kb['sleepcycle'] = {
            'fresh_data': fresh_data,
            'historical_data': {
                'note': 'Исторические данные (до последнего года) доступны в data/sleepcycle/parsed/',
                'export_file': f"sleepcycle_export_{export_date}.csv",
                'export_date': export_date,
                'total_records': total_records,
                'historical_records': historical_count,
                'last_record_date': last_record_date
            }
        }
        
        # Сохраняем обновленный knowledge_base
        with open(KNOWLEDGE_BASE, 'w', encoding='utf-8') as f:
            json.dump(kb, f, ensure_ascii=False, indent=2, default=str)
        
        print(f"\n✅ knowledge_base.json обновлен")
        
    except Exception as e:
        print(f"⚠️  Ошибка обновления knowledge_base.json: {e}")

def find_and_move_sleepdata_file():
    """Ищет sleepdata.csv в Downloads и перемещает в export с правильным именем"""
    today = datetime.now().strftime('%Y-%m-%d')
    target_name = f"sleepcycle_export_{today}.csv"
    target_path = EXPORT_DIR / target_name
    
    # Проверяем, есть ли уже файл с сегодняшней датой
    if target_path.exists():
        print(f"ℹ️  Файл {target_name} уже существует, используем его")
        return target_path
    
    # Ищем sleepdata.csv в Downloads
    sleepdata_file = None
    for downloads_dir in DOWNLOADS_DIRS:
        potential_file = downloads_dir / "sleepdata.csv"
        if potential_file.exists():
            sleepdata_file = potential_file
            break
    
    if sleepdata_file:
        print(f"📥 Найден файл: {sleepdata_file}")
        print(f"📦 Перемещаю в {target_path}...")
        
        # Перемещаем и переименовываем
        sleepdata_file.rename(target_path)
        print(f"✅ Файл перемещен и переименован в {target_name}")
        return target_path
    else:
        return None

def get_existing_dates():
    """Получает список дат, для которых уже есть JSON файлы"""
    existing_dates = set()
    if DAILY_DIR.exists():
        for json_file in DAILY_DIR.glob('*.json'):
            date_str = json_file.stem
            try:
                # Проверяем, что это валидная дата
                datetime.strptime(date_str, '%Y-%m-%d')
                existing_dates.add(date_str)
            except:
                pass
    return existing_dates

def main():
    ensure_dirs()
    
    # Пытаемся найти и переместить файл из Downloads
    moved_file = find_and_move_sleepdata_file()
    
    # Ищем CSV файлы в папке export
    csv_files = list(EXPORT_DIR.glob('*.csv'))
    
    if not csv_files:
        print("❌ Не найдено CSV файлов в data/sleepcycle/export/")
        print("\n📋 Инструкция по экспорту:")
        print("1. Откройте приложение SleepCycle на iPhone")
        print("2. Перейдите в Profile → Account → Export data")
        print("3. Сохраните файл на компьютер (он будет называться sleepdata.csv)")
        print("4. Запустите этот скрипт снова")
        sys.exit(1)
    
    # Берем самый новый файл
    csv_file = max(csv_files, key=lambda p: p.stat().st_mtime)
    
    print(f"\n{'='*60}")
    print(f"Обработка: {csv_file.name}")
    print(f"{'='*60}")
    
    result = parse_sleepcycle_csv(csv_file)
    
    if not result:
        sys.exit(1)
    
    data, fresh_records = result
    
    # Сохраняем полные данные в parsed
    parsed_file = PARSED_DIR / f"sleepcycle_all_{data['export_date']}.json"
    with open(parsed_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\n✅ Полные данные сохранены в {parsed_file}")
    
    # Сохраняем метаданные
    metadata_file = PARSED_DIR / f"metadata_{data['export_date']}.json"
    metadata = {
        'export_date': data['export_date'],
        'source_file': data['source_file'],
        'total_records': data['total_records'],
        'fresh_records': len(fresh_records),
        'historical_records': data['historical_records_count'],
        'processed_fresh': len(fresh_records),
        'last_record_date': data['last_record_date']
    }
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2, default=str)
    
    # Получаем список уже существующих дат
    existing_dates = get_existing_dates()
    
    # Создаем JSON файлы для свежих записей
    print(f"\n📝 Создание JSON файлов для свежих записей...")
    processed_count = 0
    new_count = 0
    updated_count = 0
    
    for date_str, record in fresh_records:
        daily_json = create_daily_json(date_str, record)
        if daily_json:
            daily_file = DAILY_DIR / f"{date_str}.json"
            is_new = date_str not in existing_dates
            
            with open(daily_file, 'w', encoding='utf-8') as f:
                json.dump(daily_json, f, ensure_ascii=False, indent=2, default=str)
            
            processed_count += 1
            if is_new:
                new_count += 1
                print(f"   ✅ {date_str} (новый)")
            else:
                updated_count += 1
                print(f"   🔄 {date_str} (обновлен)")
    
    # Обновляем knowledge_base.json
    update_knowledge_base(
        fresh_records,
        data['export_date'],
        data['total_records'],
        data['historical_records_count'],
        data['last_record_date']
    )
    
    print(f"\n📊 Статистика:")
    print(f"   Всего записей: {data['total_records']}")
    print(f"   Свежих записей (последний год): {len(fresh_records)}")
    print(f"   Исторических записей: {data['historical_records_count']}")
    print(f"   Обработано JSON файлов: {processed_count}")
    if new_count > 0:
        print(f"   ✨ Новых записей: {new_count}")
    if updated_count > 0:
        print(f"   🔄 Обновленных записей: {updated_count}")
    print(f"   Последняя запись: {data['last_record_date']}")

if __name__ == "__main__":
    main()

