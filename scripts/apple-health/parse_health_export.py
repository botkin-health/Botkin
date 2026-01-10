#!/usr/bin/env python3
"""
Скрипт для парсинга экспортированных данных из Apple Health
Ожидает XML файл экспорта из приложения Health
"""

import os
import sys
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime
from collections import defaultdict

BASE_DIR = Path(__file__).parent.parent.parent
EXPORT_DIR = BASE_DIR / "data" / "apple-health" / "export"
PARSED_DIR = BASE_DIR / "data" / "apple-health" / "parsed"

def ensure_dirs():
    """Создает необходимые директории"""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    PARSED_DIR.mkdir(parents=True, exist_ok=True)

def parse_health_xml(xml_file):
    """Парсит XML файл экспорта Apple Health"""
    print(f"📖 Парсинг {xml_file.name}...")
    
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
    except Exception as e:
        print(f"❌ Ошибка чтения XML: {e}")
        return None
    
    # Структура данных
    data = {
        'export_date': datetime.now().isoformat(),
        'source_file': xml_file.name,
        'records': [],
        'workouts': [],
        'activity_summary': [],
        'clinical_records': [],
        'metadata': {}
    }
    
    # Парсим записи (Record)
    records_by_type = defaultdict(list)
    
    for record in root.findall('.//Record'):
        record_data = {
            'type': record.get('type'),
            'sourceName': record.get('sourceName'),
            'sourceVersion': record.get('sourceVersion'),
            'unit': record.get('unit'),
            'value': record.get('value'),
            'creationDate': record.get('creationDate'),
            'startDate': record.get('startDate'),
            'endDate': record.get('endDate'),
        }
        
        # Удаляем None значения
        record_data = {k: v for k, v in record_data.items() if v is not None}
        
        records_by_type[record_data['type']].append(record_data)
        data['records'].append(record_data)
    
    # Парсим тренировки (Workout)
    for workout in root.findall('.//Workout'):
        workout_data = {
            'workoutActivityType': workout.get('workoutActivityType'),
            'duration': workout.get('duration'),
            'durationUnit': workout.get('durationUnit'),
            'totalDistance': workout.get('totalDistance'),
            'totalDistanceUnit': workout.get('totalDistanceUnit'),
            'totalEnergyBurned': workout.get('totalEnergyBurned'),
            'totalEnergyBurnedUnit': workout.get('totalEnergyBurnedUnit'),
            'creationDate': workout.get('creationDate'),
            'startDate': workout.get('startDate'),
            'endDate': workout.get('endDate'),
        }
        
        workout_data = {k: v for k, v in workout_data.items() if v is not None}
        data['workouts'].append(workout_data)
    
    # Парсим ActivitySummary
    for summary in root.findall('.//ActivitySummary'):
        summary_data = {
            'dateComponents': summary.get('dateComponents'),
            'activeEnergyBurned': summary.get('activeEnergyBurned'),
            'activeEnergyBurnedGoal': summary.get('activeEnergyBurnedGoal'),
            'activeEnergyBurnedUnit': summary.get('activeEnergyBurnedUnit'),
            'appleExerciseTime': summary.get('appleExerciseTime'),
            'appleExerciseTimeGoal': summary.get('appleExerciseTimeGoal'),
            'appleStandHours': summary.get('appleStandHours'),
            'appleStandHoursGoal': summary.get('appleStandHoursGoal'),
        }
        
        summary_data = {k: v for k, v in summary_data.items() if v is not None}
        data['activity_summary'].append(summary_data)
    
    # Парсим ClinicalRecords (если есть)
    for clinical in root.findall('.//ClinicalRecord'):
        clinical_data = {
            'type': clinical.get('type'),
            'identifier': clinical.get('identifier'),
            'sourceName': clinical.get('sourceName'),
            'sourceURL': clinical.get('sourceURL'),
            'fhirVersion': clinical.get('fhirVersion'),
            'creationDate': clinical.get('creationDate'),
            'startDate': clinical.get('startDate'),
            'endDate': clinical.get('endDate'),
        }
        
        clinical_data = {k: v for k, v in clinical_data.items() if v is not None}
        data['clinical_records'].append(clinical_data)
    
    # Метаданные
    data['metadata'] = {
        'total_records': len(data['records']),
        'total_workouts': len(data['workouts']),
        'total_activity_summaries': len(data['activity_summary']),
        'total_clinical_records': len(data['clinical_records']),
        'record_types': list(records_by_type.keys()),
        'record_types_count': {k: len(v) for k, v in records_by_type.items()}
    }
    
    return data

def save_parsed_data(data, output_file):
    """Сохраняет распарсенные данные в JSON"""
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)

def main():
    ensure_dirs()
    
    # Ищем XML файлы в папке export
    xml_files = list(EXPORT_DIR.glob('*.xml'))
    
    if not xml_files:
        print("❌ Не найдено XML файлов в data/apple-health/export/")
        print("\n📋 Инструкция по экспорту:")
        print("1. Откройте приложение Health на iPhone")
        print("2. Нажмите на ваш профиль (иконка в правом верхнем углу)")
        print("3. Прокрутите вниз и выберите 'Экспорт данных о здоровье'")
        print("4. Сохраните файл и переместите его в data/apple-health/export/")
        sys.exit(1)
    
    for xml_file in xml_files:
        print(f"\n{'='*60}")
        print(f"Обработка: {xml_file.name}")
        print(f"{'='*60}")
        
        data = parse_health_xml(xml_file)
        
        if data:
            # Сохраняем полные данные
            output_file = PARSED_DIR / f"{xml_file.stem}_parsed.json"
            save_parsed_data(data, output_file)
            
            print(f"\n✅ Данные сохранены в {output_file}")
            print(f"\n📊 Статистика:")
            print(f"   Записей: {data['metadata']['total_records']}")
            print(f"   Тренировок: {data['metadata']['total_workouts']}")
            print(f"   Сводок активности: {data['metadata']['total_activity_summaries']}")
            print(f"   Клинических записей: {data['metadata']['total_clinical_records']}")
            print(f"\n   Типы записей: {len(data['metadata']['record_types'])}")
            for record_type, count in sorted(data['metadata']['record_types_count'].items(), key=lambda x: x[1], reverse=True)[:10]:
                print(f"      {record_type}: {count}")

if __name__ == "__main__":
    main()

