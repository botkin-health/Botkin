#!/usr/bin/env python3
"""
Apple Health Data Parser для HealthVault
Парсит XML экспорт из Apple Health и интегрирует данные в структуру HealthVault
"""

import xml.etree.ElementTree as ET
import json
import csv
import os
from datetime import datetime, date
from pathlib import Path
from collections import defaultdict

class AppleHealthParser:
    def __init__(self, xml_file_path):
        self.xml_file = xml_file_path
        self.data_path = Path(__file__).parent.parent / "data"
        self.apple_health_path = self.data_path / "apple-health"
        self.apple_health_path.mkdir(exist_ok=True)
        
        # Создаем подпапки для различных типов данных
        (self.apple_health_path / "parsed").mkdir(exist_ok=True)
        (self.apple_health_path / "daily_summaries").mkdir(exist_ok=True)
        
    def parse_xml(self):
        """Основной метод парсинга XML файла"""
        print("🔄 Начинаем парсинг Apple Health экспорта...")
        
        # Парсим XML по частям для экономии памяти
        context = ET.iterparse(self.xml_file, events=("start", "end"))
        context = iter(context)
        event, root = next(context)
        
        # Счетчики для статистики
        record_counts = defaultdict(int)
        processed_records = 0
        
        # Контейнеры для данных
        health_data = {
            'weight': [],
            'heart_rate': [],
            'steps': [],
            'sleep': [],
            'active_energy': [],
            'resting_heart_rate': [],
            'body_mass_index': [],
            'body_fat_percentage': [],
            'dietary_water': [],
            'workouts': []
        }
        
        for event, elem in context:
            if event == "end":
                if elem.tag == "Record":
                    record_type = elem.get("type")
                    record_counts[record_type] += 1
                    processed_records += 1
                    
                    # Парсим различные типы записей
                    self._parse_record(elem, health_data)
                    
                    if processed_records % 50000 == 0:
                        print(f"📊 Обработано {processed_records:,} записей...")
                
                elif elem.tag == "Workout":
                    self._parse_workout(elem, health_data)
                
                # Освобождаем память
                elem.clear()
                root.clear()
        
        print(f"✅ Парсинг завершен! Обработано {processed_records:,} записей")
        self._print_statistics(record_counts)
        
        return health_data
    
    def _parse_record(self, record, health_data):
        """Парсит отдельную запись из XML"""
        record_type = record.get("type")
        value = record.get("value")
        unit = record.get("unit")
        start_date = record.get("startDate")
        end_date = record.get("endDate")
        source = record.get("sourceName")
        
        if not value or not start_date:
            return
            
        # Парсим дату
        try:
            start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        except:
            return
            
        record_data = {
            'value': float(value) if value.replace('.', '').replace('-', '').isdigit() else value,
            'unit': unit,
            'start_date': start_dt.isoformat(),
            'end_date': end_dt.isoformat(),
            'source': source,
            'date': start_dt.date().isoformat()
        }
        
        # Сортируем по типам
        if record_type == "HKQuantityTypeIdentifierBodyMass":
            health_data['weight'].append(record_data)
        elif record_type == "HKQuantityTypeIdentifierHeartRate":
            health_data['heart_rate'].append(record_data)
        elif record_type == "HKQuantityTypeIdentifierStepCount":
            health_data['steps'].append(record_data)
        elif record_type == "HKQuantityTypeIdentifierActiveEnergyBurned":
            health_data['active_energy'].append(record_data)
        elif record_type == "HKQuantityTypeIdentifierRestingHeartRate":
            health_data['resting_heart_rate'].append(record_data)
        elif record_type == "HKQuantityTypeIdentifierBodyMassIndex":
            health_data['body_mass_index'].append(record_data)
        elif record_type == "HKQuantityTypeIdentifierBodyFatPercentage":
            health_data['body_fat_percentage'].append(record_data)
        elif record_type == "HKQuantityTypeIdentifierDietaryWater":
            health_data['dietary_water'].append(record_data)
        elif record_type == "HKCategoryTypeIdentifierSleepAnalysis":
            record_data['sleep_value'] = value  # Sleep analysis uses text values
            health_data['sleep'].append(record_data)
    
    def _parse_workout(self, workout, health_data):
        """Парсит тренировки"""
        workout_type = workout.get("workoutActivityType")
        duration = workout.get("duration")
        start_date = workout.get("startDate")
        end_date = workout.get("endDate")
        
        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                
                workout_data = {
                    'type': workout_type,
                    'duration': float(duration) if duration else None,
                    'start_date': start_dt.isoformat(),
                    'end_date': end_dt.isoformat(),
                    'date': start_dt.date().isoformat()
                }
                
                health_data['workouts'].append(workout_data)
            except:
                pass
    
    def _print_statistics(self, record_counts):
        """Выводит статистику по типам записей"""
        print("\n📊 Статистика по типам данных:")
        print("-" * 60)
        
        # Сортируем по количеству
        sorted_counts = sorted(record_counts.items(), key=lambda x: x[1], reverse=True)
        
        for record_type, count in sorted_counts[:20]:  # Топ-20
            # Сокращаем длинные названия типов
            short_type = record_type.replace("HKQuantityTypeIdentifier", "").replace("HKCategoryTypeIdentifier", "")
            print(f"{short_type:40} {count:>8,}")
    
    def save_parsed_data(self, health_data):
        """Сохраняет распарсенные данные"""
        print("\n💾 Сохраняем распарсенные данные...")
        
        parsed_path = self.apple_health_path / "parsed"
        
        for data_type, records in health_data.items():
            if records:
                # Сохраняем в JSON
                json_file = parsed_path / f"{data_type}.json"
                with open(json_file, 'w', encoding='utf-8') as f:
                    json.dump(records, f, indent=2, ensure_ascii=False)
                
                print(f"✅ {data_type}: {len(records):,} записей → {json_file}")
    
    def create_daily_summaries(self, health_data):
        """Создает дневные сводки"""
        print("\n📈 Создаем дневные сводки...")
        
        # Группируем данные по дням
        daily_data = defaultdict(dict)
        
        # Вес (берем среднее за день)
        for record in health_data['weight']:
            date_key = record['date']
            if date_key not in daily_data:
                daily_data[date_key] = {}
            
            if 'weight' not in daily_data[date_key]:
                daily_data[date_key]['weight'] = []
            daily_data[date_key]['weight'].append(record['value'])
        
        # Шаги (сумма за день)
        for record in health_data['steps']:
            date_key = record['date']
            if 'steps' not in daily_data[date_key]:
                daily_data[date_key]['steps'] = 0
            daily_data[date_key]['steps'] += record['value']
        
        # Активные калории (сумма за день)
        for record in health_data['active_energy']:
            date_key = record['date']
            if 'active_energy' not in daily_data[date_key]:
                daily_data[date_key]['active_energy'] = 0
            daily_data[date_key]['active_energy'] += record['value']
        
        # Пульс в покое (среднее за день)
        for record in health_data['resting_heart_rate']:
            date_key = record['date']
            if 'resting_heart_rate' not in daily_data[date_key]:
                daily_data[date_key]['resting_heart_rate'] = []
            daily_data[date_key]['resting_heart_rate'].append(record['value'])
        
        # Обрабатываем агрегированные данные
        processed_daily = {}
        for date_key, day_data in daily_data.items():
            processed_day = {'date': date_key}
            
            if 'weight' in day_data:
                processed_day['weight_avg'] = round(sum(day_data['weight']) / len(day_data['weight']), 1)
                processed_day['weight_measurements'] = len(day_data['weight'])
            
            if 'steps' in day_data:
                processed_day['steps_total'] = int(day_data['steps'])
            
            if 'active_energy' in day_data:
                processed_day['active_energy_total'] = round(day_data['active_energy'], 1)
            
            if 'resting_heart_rate' in day_data:
                processed_day['resting_heart_rate_avg'] = round(sum(day_data['resting_heart_rate']) / len(day_data['resting_heart_rate']), 1)
            
            processed_daily[date_key] = processed_day
        
        # Сохраняем дневные сводки
        summary_file = self.apple_health_path / "daily_summaries" / "health_metrics_daily.json"
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(processed_daily, f, indent=2, ensure_ascii=False, sort_keys=True)
        
        print(f"✅ Дневные сводки: {len(processed_daily)} дней → {summary_file}")
        
        return processed_daily
    
    def update_health_profile(self, daily_summaries):
        """Обновляет профиль здоровья актуальными данными"""
        print("\n🔄 Обновляем профиль здоровья...")
        
        # Находим последние данные
        latest_date = max(daily_summaries.keys())
        latest_data = daily_summaries[latest_date]
        
        # Находим данные за последние 30 дней для трендов
        recent_dates = sorted(daily_summaries.keys())[-30:]
        recent_weights = [daily_summaries[d].get('weight_avg') for d in recent_dates if daily_summaries[d].get('weight_avg')]
        recent_steps = [daily_summaries[d].get('steps_total') for d in recent_dates if daily_summaries[d].get('steps_total')]
        
        # Создаем summary
        health_summary = {
            'updated': datetime.now().isoformat(),
            'data_period': {
                'first_date': min(daily_summaries.keys()),
                'last_date': latest_date,
                'total_days': len(daily_summaries)
            },
            'current_metrics': {
                'weight': latest_data.get('weight_avg'),
                'last_weight_date': latest_date if latest_data.get('weight_avg') else None,
                'steps_latest': latest_data.get('steps_total'),
                'active_energy_latest': latest_data.get('active_energy_total'),
                'resting_hr_latest': latest_data.get('resting_heart_rate_avg')
            },
            'trends_30_days': {
                'avg_weight': round(sum(recent_weights) / len(recent_weights), 1) if recent_weights else None,
                'avg_steps': int(sum(recent_steps) / len(recent_steps)) if recent_steps else None,
                'weight_measurements': len(recent_weights),
                'active_days': len([s for s in recent_steps if s and s > 1000])
            }
        }
        
        # Сохраняем summary
        summary_file = self.apple_health_path / "health_profile_summary.json"
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(health_summary, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Обновлен профиль здоровья → {summary_file}")
        
        # Выводим ключевые метрики
        print("\n🎯 Ключевые метрики:")
        print(f"📊 Период данных: {health_summary['data_period']['first_date']} - {health_summary['data_period']['last_date']}")
        print(f"⚖️  Текущий вес: {health_summary['current_metrics']['weight']} кг ({health_summary['current_metrics']['last_weight_date']})")
        print(f"🚶 Средние шаги (30 дней): {health_summary['trends_30_days']['avg_steps']:,}")
        print(f"💗 Пульс в покое: {health_summary['current_metrics']['resting_hr_latest']} уд/мин")
        
        return health_summary

def main():
    # Путь к XML файлу
    xml_file = Path(__file__).parent.parent / "data/apple-health/export.xml"
    
    if not xml_file.exists():
        print(f"❌ Файл не найден: {xml_file}")
        return
    
    print(f"🍎 Apple Health Parser для HealthVault")
    print(f"📁 Исходный файл: {xml_file}")
    print(f"📊 Размер файла: {xml_file.stat().st_size / 1024 / 1024:.1f} МБ")
    print("-" * 60)
    
    # Создаем парсер и обрабатываем данные
    parser = AppleHealthParser(xml_file)
    
    # Парсим XML
    health_data = parser.parse_xml()
    
    # Сохраняем распарсенные данные
    parser.save_parsed_data(health_data)
    
    # Создаем дневные сводки
    daily_summaries = parser.create_daily_summaries(health_data)
    
    # Обновляем профиль здоровья
    health_summary = parser.update_health_profile(daily_summaries)
    
    print("\n🎉 Интеграция Apple Health данных завершена!")
    print("📁 Данные сохранены в: data/apple-health/")

if __name__ == "__main__":
    main()