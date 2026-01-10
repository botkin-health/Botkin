#!/usr/bin/env python3
"""
Комплексный скрипт для обновления данных Apple Health:
1. Распаковывает export.zip из Downloads
2. Перемещает XML в правильную папку
3. Парсит данные
4. Извлекает вес и сравнивает с умными весами
5. Удаляет исходные файлы
"""
import zipfile
import shutil
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from collections import defaultdict

DOWNLOADS_DIR = Path("/Users/alexlyskovsky/Downloads")
EXPORT_DIR = Path("/Users/alexlyskovsky/HealthVault/data/apple-health/export")
PARSED_DIR = Path("/Users/alexlyskovsky/HealthVault/data/apple-health/parsed")
WEIGHTS_FILE = Path("/Users/alexlyskovsky/HealthVault/data/weights/apple_health_weights.json")

def extract_zip():
    """Распаковывает export.zip"""
    zip_file = DOWNLOADS_DIR / "export.zip"
    if not zip_file.exists():
        print("❌ Файл export.zip не найден в Downloads")
        return None
    
    print(f"📦 Найден файл: {zip_file}")
    temp_dir = DOWNLOADS_DIR / "export_temp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()
    
    print("📂 Распаковка архива...")
    with zipfile.ZipFile(zip_file, 'r') as zip_ref:
        zip_ref.extractall(temp_dir)
    
    xml_files = list(temp_dir.rglob("*.xml"))
    if not xml_files:
        print("❌ XML файлы не найдены")
        shutil.rmtree(temp_dir)
        return None
    
    return temp_dir, xml_files

def move_xml_files(temp_dir, xml_files):
    """Перемещает XML файлы в правильную папку"""
    moved_files = []
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    for xml_file in xml_files:
        if "export.xml" in xml_file.name.lower():
            new_name = f"export_{timestamp}.xml"
        else:
            new_name = f"{xml_file.stem}_{timestamp}.xml"
        
        dest_file = EXPORT_DIR / new_name
        if dest_file.exists():
            print(f"⚠️  Файл {new_name} уже существует, пропускаем")
            continue
        
        shutil.move(str(xml_file), str(dest_file))
        moved_files.append(dest_file)
        print(f"✅ Файл сохранен: {dest_file.name}")
    
    return moved_files

def extract_weight_data(xml_file):
    """Извлекает данные о весе из XML"""
    print(f"\n📖 Парсинг {xml_file.name}...")
    
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
    except Exception as e:
        print(f"❌ Ошибка чтения XML: {e}")
        return []
    
    weight_records = []
    for record in root.findall('.//Record'):
        record_type = record.get('type')
        if record_type == 'HKQuantityTypeIdentifierBodyMass':
            weight_data = {
                'value': float(record.get('value', 0)),
                'unit': record.get('unit', 'kg'),
                'sourceName': record.get('sourceName', ''),
                'startDate': record.get('startDate', ''),
                'creationDate': record.get('creationDate', '')
            }
            weight_records.append(weight_data)
    
    print(f"📊 Найдено записей о весе: {len(weight_records)}")
    return weight_records

def parse_date_apple_health(date_str):
    """Парсит дату из формата Apple Health"""
    try:
        # Формат: 2026-01-08 13:16:00 +0300
        dt = datetime.strptime(date_str.split(' +')[0], '%Y-%m-%d %H:%M:%S')
        return dt.date().isoformat(), dt.strftime('%Y-%m-%d %H:%M:%S %z')
    except:
        return None, None

def update_weights_json(weight_records):
    """Обновляет файл с весами"""
    # Загружаем существующие данные
    if WEIGHTS_FILE.exists():
        with open(WEIGHTS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        existing_dates = {entry['date'] for entry in data.get('entries', [])}
    else:
        data = {
            "source": "apple_health",
            "export_date": datetime.now().isoformat(),
            "total_days": 0,
            "entries": []
        }
        existing_dates = set()
    
    # Добавляем новые записи
    new_entries = []
    for record in weight_records:
        date, time_str = parse_date_apple_health(record['startDate'])
        if date and date not in existing_dates:
            entry = {
                "date": date,
                "weight_kg": record['value'],
                "time": record['startDate'],
                "source": record['sourceName']
            }
            new_entries.append(entry)
            existing_dates.add(date)
    
    # Сортируем по дате (новые сначала)
    data['entries'] = sorted(data['entries'] + new_entries, 
                            key=lambda x: x['date'], reverse=True)
    data['export_date'] = datetime.now().isoformat()
    data['total_days'] = len(data['entries'])
    
    # Сохраняем
    with open(WEIGHTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"✅ Обновлено записей о весе: {len(new_entries)} новых")
    return data, new_entries

def compare_with_smart_scale(weights_data, smart_scale_weight=81.90, smart_scale_date="2026-01-08", smart_scale_time="13:16"):
    """Сравнивает данные Apple Health с умными весами"""
    print("\n" + "="*60)
    print("📊 СРАВНЕНИЕ ДАННЫХ О ВЕСЕ")
    print("="*60)
    
    # Ищем запись за указанную дату
    target_date = smart_scale_date
    apple_health_entry = None
    
    for entry in weights_data['entries']:
        if entry['date'] == target_date:
            apple_health_entry = entry
            break
    
    print(f"\n🎯 Умные весы (Zepp Life):")
    print(f"   Дата: {smart_scale_date}")
    print(f"   Время: {smart_scale_time}")
    print(f"   Вес: {smart_scale_weight} кг")
    
    if apple_health_entry:
        print(f"\n📱 Apple Health:")
        print(f"   Дата: {apple_health_entry['date']}")
        print(f"   Время: {apple_health_entry.get('time', 'N/A')}")
        print(f"   Вес: {apple_health_entry['weight_kg']} кг")
        print(f"   Источник: {apple_health_entry.get('source', 'N/A')}")
        
        diff = abs(apple_health_entry['weight_kg'] - smart_scale_weight)
        if diff < 0.1:
            print(f"\n✅ Данные совпадают (разница: {diff:.2f} кг)")
            print("✅ Все данные переносятся автоматически, скриншоты не нужны")
        else:
            print(f"\n⚠️  Разница: {diff:.2f} кг")
            print("⚠️  Возможно, нужно проверить синхронизацию")
    else:
        print(f"\n❌ Запись за {target_date} не найдена в Apple Health")
        print("⚠️  Возможно, нужно подгрузить скриншот из умных весов")
    
    # Показываем последние записи
    print(f"\n📋 Последние 5 записей из Apple Health:")
    for entry in weights_data['entries'][:5]:
        print(f"   {entry['date']}: {entry['weight_kg']} кг ({entry.get('source', 'N/A')})")

def main():
    print("🚀 Начало обработки экспорта Apple Health\n")
    
    # 1. Распаковываем ZIP
    result = extract_zip()
    if not result:
        return
    temp_dir, xml_files = result
    
    try:
        # 2. Перемещаем XML файлы
        moved_files = move_xml_files(temp_dir, xml_files)
        if not moved_files:
            print("⚠️  Нет новых файлов для обработки")
            shutil.rmtree(temp_dir)
            if (DOWNLOADS_DIR / "export.zip").exists():
                (DOWNLOADS_DIR / "export.zip").unlink()
            return
        
        # 3. Извлекаем данные о весе
        all_weight_records = []
        for xml_file in moved_files:
            weight_records = extract_weight_data(xml_file)
            all_weight_records.extend(weight_records)
        
        # 4. Обновляем файл с весами
        if all_weight_records:
            weights_data, new_entries = update_weights_json(all_weight_records)
            
            # 5. Сравниваем с умными весами
            compare_with_smart_scale(weights_data, 
                                    smart_scale_weight=81.90,
                                    smart_scale_date="2026-01-08",
                                    smart_scale_time="13:16")
        else:
            print("⚠️  Данные о весе не найдены в экспорте")
        
        # 6. Удаляем временные файлы
        print("\n🧹 Удаление временных файлов...")
        shutil.rmtree(temp_dir)
        if (DOWNLOADS_DIR / "export.zip").exists():
            (DOWNLOADS_DIR / "export.zip").unlink()
            print("✅ export.zip удален из Downloads")
        
        print("\n✅ Обработка завершена!")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        if temp_dir.exists():
            shutil.rmtree(temp_dir)

if __name__ == "__main__":
    main()
