#!/usr/bin/env python3
"""
Комплексный анализ здоровья - сбор всех метрик и корреляций
"""

import json
import glob
from datetime import datetime, timedelta
from collections import defaultdict
import statistics

def load_json_safe(filepath):
    """Безопасная загрузка JSON"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️  Не удалось загрузить {filepath}: {e}")
        return None

def collect_weight_data():
    """Собирает данные о весе"""
    data = load_json_safe('/Users/alexlyskovsky/HealthVault/data/apple_health_weight_daily.json')
    if not data:
        return {}
    
    weight_by_date = {}
    for entry in data.get('daily_averages', []):
        weight_by_date[entry['date']] = entry['weight_kg']
    
    return weight_by_date

def collect_blood_pressure():
    """Собирает данные об артериальном давлении"""
    data = load_json_safe('/Users/alexlyskovsky/HealthVault/data/apple_health_blood_pressure.json')
    if not data:
        return {}
    
    bp_by_date = defaultdict(list)
    for entry in data.get('measurements', []):
        bp_by_date[entry['date']].append({
            'systolic': entry['systolic'],
            'diastolic': entry['diastolic'],
            'time': entry['time']
        })
    
    return bp_by_date

def collect_body_measurements():
    """Собирает замеры тела"""
    data = load_json_safe('/Users/alexlyskovsky/HealthVault/data/body_measurements.json')
    if not data:
        return {}
    
    measurements_by_date = {}
    for entry in data.get('measurements', []):
        measurements_by_date[entry['date']] = entry
    
    return measurements_by_date

def collect_nutrition_data():
    """Собирает данные о питании"""
    data = load_json_safe('/Users/alexlyskovsky/HealthVault/data/nutrition/nutrition_log.json')
    if not data:
        return {}
    
    nutrition_by_date = {}
    for entry in data.get('entries', []):
        nutrition_by_date[entry['date']] = {
            'calories': entry['totals'].get('calories', 0),
            'protein': entry['totals'].get('protein', 0),
            'fats': entry['totals'].get('fats', 0),
            'carbs': entry['totals'].get('carbs', 0),
            'had_workout': entry.get('had_workout', False)
        }
    
    return nutrition_by_date

def collect_garmin_data():
    """Собирает данные Garmin (сон, шаги, стресс)"""
    garmin_data = {}
    
    # Собираем daily summary (шаги, калории)
    daily_files = glob.glob('/Users/alexlyskovsky/HealthVault/data/garmin/daily-summary/*.json')
    for filepath in sorted(daily_files)[-60:]:  # Последние 60 дней
        date = filepath.split('/')[-1].replace('.json', '')
        data = load_json_safe(filepath)
        if data:
            garmin_data.setdefault(date, {}).update({
                'steps': data.get('totalSteps', 0),
                'active_calories': data.get('activeKilocalories', 0),
                'total_calories': data.get('totalKilocalories', 0),
                'distance_km': data.get('totalDistanceMeters', 0) / 1000 if data.get('totalDistanceMeters') else 0
            })
    
    # Собираем данные сна
    sleep_files = glob.glob('/Users/alexlyskovsky/HealthVault/data/garmin/sleep/*.json')
    for filepath in sorted(sleep_files)[-60:]:
        date = filepath.split('/')[-1].replace('.json', '')
        data = load_json_safe(filepath)
        if data:
            duration_seconds = data.get('sleepTimeSeconds', 0)
            garmin_data.setdefault(date, {}).update({
                'sleep_hours': round(duration_seconds / 3600, 1) if duration_seconds else 0,
                'deep_sleep_seconds': data.get('deepSleepSeconds', 0),
                'light_sleep_seconds': data.get('lightSleepSeconds', 0),
                'rem_sleep_seconds': data.get('remSleepSeconds', 0),
                'awake_seconds': data.get('awakeSleepSeconds', 0)
            })
    
    # Собираем данные стресса
    stress_files = glob.glob('/Users/alexlyskovsky/HealthVault/data/garmin/stress/*.json')
    for filepath in sorted(stress_files)[-60:]:
        date = filepath.split('/')[-1].replace('.json', '')
        data = load_json_safe(filepath)
        if data:
            avg_stress = data.get('avgStressLevel')
            max_stress = data.get('maxStressLevel')
            garmin_data.setdefault(date, {}).update({
                'avg_stress': avg_stress if avg_stress and avg_stress > 0 else None,
                'max_stress': max_stress if max_stress and max_stress > 0 else None
            })
    
    return garmin_data

def analyze_correlations(weight_data, nutrition_data, garmin_data, bp_data):
    """Анализирует корреляции между метриками"""
    
    print("\n" + "="*70)
    print("📊 КОМПЛЕКСНЫЙ АНАЛИЗ ЗДОРОВЬЯ")
    print("="*70)
    
    # Получаем общий период данных
    all_dates = set()
    all_dates.update(weight_data.keys())
    all_dates.update(nutrition_data.keys())
    all_dates.update(garmin_data.keys())
    all_dates = sorted([d for d in all_dates if d >= '2026-01-01'])
    
    if not all_dates:
        print("❌ Нет данных для анализа!")
        return
    
    print(f"\n📅 Период анализа: {all_dates[0]} — {all_dates[-1]} ({len(all_dates)} дней)")
    
    # === 1. ДИНАМИКА ВЕСА ===
    print("\n" + "-"*70)
    print("⚖️  ДИНАМИКА ВЕСА")
    print("-"*70)
    
    recent_weights = [weight_data[d] for d in all_dates if d in weight_data]
    if len(recent_weights) >= 2:
        weight_change = recent_weights[-1] - recent_weights[0]
        avg_weight = statistics.mean(recent_weights)
        print(f"📉 Начальный вес: {recent_weights[0]} кг ({all_dates[0]})")
        print(f"📉 Текущий вес: {recent_weights[-1]} кг ({[d for d in all_dates if d in weight_data][-1]})")
        print(f"📉 Изменение: {weight_change:+.2f} кг")
        print(f"📉 Средний вес: {avg_weight:.2f} кг")
    
    # === 2. ПИТАНИЕ И КАЛОРИИ ===
    print("\n" + "-"*70)
    print("🍽️  ПИТАНИЕ")
    print("-"*70)
    
    nutrition_days = [d for d in all_dates if d in nutrition_data]
    if nutrition_days:
        calories = [nutrition_data[d]['calories'] for d in nutrition_days]
        protein = [nutrition_data[d]['protein'] for d in nutrition_days]
        
        print(f"📝 Дней с записями: {len(nutrition_days)}")
        print(f"🔥 Средние калории: {statistics.mean(calories):.0f} ккал/день")
        print(f"🥩 Средний белок: {statistics.mean(protein):.1f} г/день")
        print(f"🔥 Диапазон калорий: {min(calories):.0f} - {max(calories):.0f} ккал")
    
    # === 3. АКТИВНОСТЬ (GARMIN) ===
    print("\n" + "-"*70)
    print("🏃 АКТИВНОСТЬ И СОН (GARMIN)")
    print("-"*70)
    
    garmin_days = [d for d in all_dates if d in garmin_data and garmin_data[d].get('steps', 0) > 0]
    steps = []
    sleep_hours = []
    
    if garmin_days:
        steps = [garmin_data[d]['steps'] for d in garmin_days]
        sleep_hours = [garmin_data[d].get('sleep_hours', 0) for d in garmin_days if garmin_data[d].get('sleep_hours', 0) > 0]
        
        print(f"👣 Средние шаги: {statistics.mean(steps):.0f} шагов/день")
        print(f"👣 Диапазон шагов: {min(steps)} - {max(steps)}")
        
        if sleep_hours:
            print(f"😴 Средний сон: {statistics.mean(sleep_hours):.1f} часов")
            print(f"😴 Диапазон сна: {min(sleep_hours):.1f} - {max(sleep_hours):.1f} часов")
    
    # Стресс
    stress_days = [d for d in all_dates if d in garmin_data and garmin_data[d].get('avg_stress')]
    avg_stress_values = []
    
    if stress_days:
        avg_stress_values = [garmin_data[d]['avg_stress'] for d in stress_days]
        print(f"🧘 Средний стресс: {statistics.mean(avg_stress_values):.1f}")
        print(f"🧘 Диапазон стресса: {min(avg_stress_values):.0f} - {max(avg_stress_values):.0f}")
    
    # === 4. ДАВЛЕНИЕ ===
    print("\n" + "-"*70)
    print("🩺 АРТЕРИАЛЬНОЕ ДАВЛЕНИЕ")
    print("-"*70)
    
    bp_days = sorted([d for d in bp_data.keys() if d in all_dates])
    if bp_days:
        all_systolic = []
        all_diastolic = []
        for d in bp_days:
            for measurement in bp_data[d]:
                all_systolic.append(measurement['systolic'])
                all_diastolic.append(measurement['diastolic'])
        
        print(f"📊 Замеров: {len(all_systolic)} за {len(bp_days)} дней")
        print(f"💓 Среднее систолическое: {statistics.mean(all_systolic):.0f} мм рт.ст.")
        print(f"💓 Среднее диастолическое: {statistics.mean(all_diastolic):.0f} мм рт.ст.")
        print(f"💓 Диапазон: {min(all_systolic)}/{min(all_diastolic)} - {max(all_systolic)}/{max(all_diastolic)}")
        
        high_bp_count = sum(1 for s in all_systolic if s >= 140)
        if high_bp_count > 0:
            print(f"⚠️  Повышенное давление (≥140): {high_bp_count} замеров ({high_bp_count/len(all_systolic)*100:.1f}%)")
    
    # === 5. КОРРЕЛЯЦИИ ===
    print("\n" + "="*70)
    print("🔍 КОРРЕЛЯЦИИ И ВЗАИМОСВЯЗИ")
    print("="*70)
    
    # Вес vs калории
    paired_weight_cal = []
    for d in all_dates:
        if d in weight_data and d in nutrition_data:
            paired_weight_cal.append((weight_data[d], nutrition_data[d]['calories']))
    
    if len(paired_weight_cal) >= 3:
        print(f"\n📉 ВЕС vs КАЛОРИИ ({len(paired_weight_cal)} дней с обеими метриками)")
        weights = [w for w, c in paired_weight_cal]
        cals = [c for w, c in paired_weight_cal]
        print(f"   Средний вес: {statistics.mean(weights):.2f} кг")
        print(f"   Средние калории: {statistics.mean(cals):.0f} ккал")
    
    # Вес vs сон
    paired_weight_sleep = []
    for d in all_dates:
        if d in weight_data and d in garmin_data and garmin_data[d].get('sleep_hours', 0) > 0:
            paired_weight_sleep.append((weight_data[d], garmin_data[d]['sleep_hours']))
    
    if len(paired_weight_sleep) >= 3:
        print(f"\n😴 ВЕС vs СОН ({len(paired_weight_sleep)} дней)")
        weights = [w for w, s in paired_weight_sleep]
        sleep_hrs = [s for w, s in paired_weight_sleep]
        print(f"   Средний сон: {statistics.mean(sleep_hrs):.1f} часов")
    
    # КЭкспорт результатов
    results = {
        'analysis_date': datetime.now().isoformat(),
        'period': {
            'start': all_dates[0] if all_dates else None,
            'end': all_dates[-1] if all_dates else None,
            'days': len(all_dates)
        },
        'weight': {
            'current': recent_weights[-1] if recent_weights else None,
            'average': statistics.mean(recent_weights) if recent_weights else None,
            'change': weight_change if len(recent_weights) >= 2 else None
        },
        'nutrition': {
            'days_logged': len(nutrition_days),
            'avg_calories': statistics.mean(calories) if nutrition_days else None,
            'avg_protein': statistics.mean(protein) if nutrition_days else None
        },
        'activity': {
            'avg_steps': statistics.mean(steps) if garmin_days else None,
            'avg_sleep': statistics.mean(sleep_hours) if sleep_hours else None,
            'avg_stress': statistics.mean(avg_stress_values) if stress_days else None
        },
        'blood_pressure': {
            'avg_systolic': statistics.mean(all_systolic) if bp_days else None,
            'avg_diastolic': statistics.mean(all_diastolic) if bp_days else None,
            'measurements_count': len(all_systolic) if bp_days else 0
        }
    }
    
    with open('/Users/alexlyskovsky/HealthVault/data/analysis/health_analysis_summary.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print("\n" + "="*70)
    print("✅ Анализ завершен!")
    print(f"📁 Результаты сохранены: data/analysis/health_analysis_summary.json")
    print("="*70 + "\n")
    
    return results

if __name__ == '__main__':
    print("🔄 Загрузка данных...")
    
    weight_data = collect_weight_data()
    bp_data = collect_blood_pressure()
    body_measurements = collect_body_measurements()
    nutrition_data = collect_nutrition_data()
    garmin_data = collect_garmin_data()
    
    print(f"✅ Загружено:")
    print(f"   • Вес: {len(weight_data)} дней")
    print(f"   • Давление: {len(bp_data)} дней")
    print(f"   • Замеры тела: {len(body_measurements)} записей")
    print(f"   • Питание: {len(nutrition_data)} дней")
    print(f"   • Garmin: {len(garmin_data)} дней")
    
    results = analyze_correlations(weight_data, nutrition_data, garmin_data, bp_data)
