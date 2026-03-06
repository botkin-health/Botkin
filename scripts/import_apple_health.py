#!/usr/bin/env python3
"""
Скрипт для импорта данных из Apple Health Export в базу HealthVault
"""

import xml.etree.ElementTree as ET
import json
from datetime import datetime
from collections import defaultdict
import sys

def parse_apple_health_export(xml_path):
    """Парсит экспорт Apple Health и извлекает нужные данные"""
    
    print(f"Парсинг файла: {xml_path}")
    
    # Данные для извлечения
    weight_data = []
    blood_pressure_data = []
    heart_rate_data = []
    
    # Парсим XML построчно для экономии памяти
    context = ET.iterparse(xml_path, events=('start', 'end'))
    context = iter(context)
    event, root = next(context)
    
    systolic_by_date = {}
    diastolic_by_date = {}
    
    record_count = 0
    
    for event, elem in context:
        if event == 'end':
            if elem.tag == 'Record':
                record_type = elem.get('type', '')
                
                # Вес
                if record_type == 'HKQuantityTypeIdentifierBodyMass':
                    date_str = elem.get('startDate', '')
                    value = elem.get('value', '')
                    unit = elem.get('unit', '')
                    
                    if date_str and value:
                        # Парсим дату
                        dt = datetime.fromisoformat(date_str.replace(' +0300', '+03:00'))
                        weight_data.append({
                            'date': dt.strftime('%Y-%m-%d'),
                            'time': dt.strftime('%H:%M:%S'),
                            'weight_kg': float(value),
                            'source': elem.get('sourceName', 'Unknown')
                        })
                
                # Систолическое давление
                elif record_type == 'HKQuantityTypeIdentifierBloodPressureSystolic':
                    date_str = elem.get('startDate', '')
                    value = elem.get('value', '')
                    
                    if date_str and value:
                        dt = datetime.fromisoformat(date_str.replace(' +0300', '+03:00'))
                        key = dt.strftime('%Y-%m-%d %H:%M:%S')
                        systolic_by_date[key] = float(value)
                
                # Диастолическое давление
                elif record_type == 'HKQuantityTypeIdentifierBloodPressureDiastolic':
                    date_str = elem.get('startDate', '')
                    value = elem.get('value', '')
                    
                    if date_str and value:
                        dt = datetime.fromisoformat(date_str.replace(' +0300', '+03:00'))
                        key = dt.strftime('%Y-%m-%d %H:%M:%S')
                        diastolic_by_date[key] = float(value)
                
                # Пульс в покое
                elif record_type == 'HKQuantityTypeIdentifierRestingHeartRate':
                    date_str = elem.get('startDate', '')
                    value = elem.get('value', '')
                    
                    if date_str and value:
                        dt = datetime.fromisoformat(date_str.replace(' +0300', '+03:00'))
                        heart_rate_data.append({
                            'date': dt.strftime('%Y-%m-%d'),
                            'time': dt.strftime('%H:%M:%S'),
                            'bpm': int(float(value)),
                            'type': 'resting',
                            'source': elem.get('sourceName', 'Unknown')
                        })
                
                record_count += 1
                if record_count % 100000 == 0:
                    print(f"Обработано записей: {record_count}")
            
            # Очищаем элемент для экономии памяти
            elem.clear()
            root.clear()
    
    # Объединяем данные давления
    for timestamp in systolic_by_date:
        if timestamp in diastolic_by_date:
            dt = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
            blood_pressure_data.append({
                'date': dt.strftime('%Y-%m-%d'),
                'time': dt.strftime('%H:%M:%S'),
                'systolic': int(systolic_by_date[timestamp]),
                'diastolic': int(diastolic_by_date[timestamp])
            })
    
    # Сортируем данные по дате
    weight_data.sort(key=lambda x: (x['date'], x['time']))
    blood_pressure_data.sort(key=lambda x: (x['date'], x['time']))
    heart_rate_data.sort(key=lambda x: (x['date'], x['time']))
    
    print(f"\nНайдено записей веса: {len(weight_data)}")
    print(f"Найдено записей давления: {len(blood_pressure_data)}")
    print(f"Найдено записей пульса в покое: {len(heart_rate_data)}")
    
    return {
        'weight': weight_data,
        'blood_pressure': blood_pressure_data,
        'heart_rate': heart_rate_data
    }

def get_daily_averages(weight_data):
    """Вычисляет средний вес за каждый день"""
    daily_weights = defaultdict(list)
    
    for entry in weight_data:
        daily_weights[entry['date']].append(entry['weight_kg'])
    
    daily_avg = []
    for date, weights in sorted(daily_weights.items()):
        daily_avg.append({
            'date': date,
            'weight_kg': round(sum(weights) / len(weights), 2),
            'measurements_count': len(weights)
        })
    
    return daily_avg

def save_to_healthvault(data, base_path):
    """Сохраняет данные в базу HealthVault"""
    
    # Сохраняем данные веса (все замеры)
    weight_file = f"{base_path}/data/apple_health_weight.json"
    with open(weight_file, 'w', encoding='utf-8') as f:
        json.dump({'measurements': data['weight']}, f, ensure_ascii=False, indent=2)
    print(f"✅ Сохранено {len(data['weight'])} записей веса в {weight_file}")
    
    # Сохраняем средний вес по дням
    daily_weight = get_daily_averages(data['weight'])
    daily_weight_file = f"{base_path}/data/apple_health_weight_daily.json"
    with open(daily_weight_file, 'w', encoding='utf-8') as f:
        json.dump({'daily_averages': daily_weight}, f, ensure_ascii=False, indent=2)
    print(f"✅ Сохранено {len(daily_weight)} дней с весом в {daily_weight_file}")
    
    # Сохраняем данные давления
    bp_file = f"{base_path}/data/apple_health_blood_pressure.json"
    with open(bp_file, 'w', encoding='utf-8') as f:
        json.dump({'measurements': data['blood_pressure']}, f, ensure_ascii=False, indent=2)
    print(f"✅ Сохранено {len(data['blood_pressure'])} записей давления в {bp_file}")
    
    # Сохраняем данные пульса в покое
    hr_file = f"{base_path}/data/apple_health_heart_rate.json"
    with open(hr_file, 'w', encoding='utf-8') as f:
        json.dump({'measurements': data['heart_rate']}, f, ensure_ascii=False, indent=2)
    print(f"✅ Сохранено {len(data['heart_rate'])} записей пульса в {hr_file}")
    
    # Статистика
    if daily_weight:
        print(f"\n📊 Период данных веса: {daily_weight[0]['date']} - {daily_weight[-1]['date']}")
        print(f"📊 Последний вес: {daily_weight[-1]['weight_kg']} кг ({daily_weight[-1]['date']})")
    
    if data['blood_pressure']:
        latest_bp = data['blood_pressure'][-1]
        print(f"📊 Последнее давление: {latest_bp['systolic']}/{latest_bp['diastolic']} ({latest_bp['date']} {latest_bp['time']})")

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Импорт данных из Apple Health Export')
    parser.add_argument('--export_xml', type=str, required=True, help='Путь к XML файлу экспорта')
    parser.add_argument('--healthvault_path', type=str, default='/Users/alexlyskovsky/HealthVault', help='Путь к директории HealthVault')
    args = parser.parse_args()
    
    # Пути
    export_xml = args.export_xml
    healthvault_path = args.healthvault_path
    
    # Парсим данные
    data = parse_apple_health_export(export_xml)
    
    # Сохраняем в базу HealthVault
    save_to_healthvault(data, healthvault_path)
    
    print("\n✅ Импорт завершен!")
