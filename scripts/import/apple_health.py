#!/usr/bin/env python3
"""
Импорт данных из Apple Health Export в HealthVault.

Импортирует:
  - Вес (BodyMass)                       → apple_health_weight.json + apple_health_weight_daily.json
  - АД (BloodPressureSystolic/Diastolic) → apple_health_blood_pressure.json
  - Пульс в покое (RestingHeartRate)     → apple_health_heart_rate.json
  - Шаги (StepCount, суточные суммы)     → apple_health_steps_daily.json     [НОВЫЙ]
  - Характеристики ходьбы               → apple_health_gait.json             [НОВЫЙ]
      WalkingSpeed (km/hr), WalkingStepLength (cm),
      WalkingDoubleSupportPercentage (%), WalkingAsymmetryPercentage (%)

Использование:
  python3 scripts/import_apple_health.py
  python3 scripts/import_apple_health.py --export_xml ~/Downloads/.../export.xml

Примечание: Apple Health export — ручная операция.
  Телефон: Health → Профиль → Экспорт данных → разархивировать zip.
  Скрипт сам найдёт export.xml в ~/Downloads/apple_health_export*/
"""

import xml.etree.ElementTree as ET
import json
import glob
import os
import argparse
from datetime import datetime
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"

# Типы, которые нас интересуют
TYPES_OF_INTEREST = {
    'HKQuantityTypeIdentifierBodyMass',
    'HKQuantityTypeIdentifierBloodPressureSystolic',
    'HKQuantityTypeIdentifierBloodPressureDiastolic',
    'HKQuantityTypeIdentifierRestingHeartRate',
    'HKQuantityTypeIdentifierStepCount',
    'HKQuantityTypeIdentifierWalkingSpeed',
    'HKQuantityTypeIdentifierWalkingStepLength',
    'HKQuantityTypeIdentifierWalkingDoubleSupportPercentage',
    'HKQuantityTypeIdentifierWalkingAsymmetryPercentage',
}

# Маппинг гайт-метрик → ключи в выходном JSON
GAIT_METRICS = {
    'HKQuantityTypeIdentifierWalkingSpeed':                 'speed_km_h',
    'HKQuantityTypeIdentifierWalkingStepLength':            'step_length_cm',
    'HKQuantityTypeIdentifierWalkingDoubleSupportPercentage': 'double_support_pct',
    'HKQuantityTypeIdentifierWalkingAsymmetryPercentage':   'asymmetry_pct',
}

# Эти типы хранятся как доли (0-1), а не проценты — умножаем на 100
FRACTION_METRICS = {
    'HKQuantityTypeIdentifierWalkingDoubleSupportPercentage',
    'HKQuantityTypeIdentifierWalkingAsymmetryPercentage',
}


def find_latest_export():
    """Ищет последний экспорт Apple Health в ~/Downloads/"""
    patterns = [
        os.path.expanduser("~/Downloads/apple_health_export*/apple_health_export/export.xml"),
        os.path.expanduser("~/Downloads/apple_health_export/apple_health_export/export.xml"),
    ]
    candidates = []
    for p in patterns:
        candidates.extend(glob.glob(p))
    if candidates:
        # Берём самый свежий (по имени директории, т.к. цифровой суффикс растёт)
        return sorted(candidates)[-1]
    return None


def parse_date(date_str):
    """Парсит дату Apple Health формата: '2026-01-06 10:30:00 +0300'"""
    try:
        # Убираем пробел перед timezone offset
        cleaned = date_str.strip()
        # "2026-01-06 10:30:00 +0300" → "2026-01-06T10:30:00+03:00"
        if ' +' in cleaned:
            parts = cleaned.rsplit(' +', 1)
            tz = parts[1]
            tz_fmt = f"+{tz[:2]}:{tz[2:]}" if len(tz) >= 4 else f"+{tz}"
            cleaned = parts[0].replace(' ', 'T') + tz_fmt
        elif ' -' in cleaned[10:]:
            # Редкий случай с отрицательным offset
            idx = cleaned.rfind(' -')
            parts = [cleaned[:idx], cleaned[idx+1:]]
            tz = parts[1]
            tz_fmt = f"-{tz[:2]}:{tz[2:]}" if len(tz) >= 4 else f"-{tz}"
            cleaned = parts[0].replace(' ', 'T') + tz_fmt
        return datetime.fromisoformat(cleaned)
    except Exception:
        return None


def parse_export(xml_path):
    """
    Парсит XML одним проходом, собирает все нужные типы.
    Возвращает dict с обработанными данными.
    """
    print(f"📂 Парсинг: {xml_path}")
    print("   (735 MB файл, займёт ~2-3 минуты...)")

    weight_data = []
    systolic_by_ts = {}
    diastolic_by_ts = {}
    hr_resting = []
    steps_by_day = defaultdict(float)         # date → steps (только выбранный источник)
    steps_src_by_day = {}                     # date → 'garmin' | 'iphone' (для приоритизации)
    gait_by_day = defaultdict(lambda: defaultdict(list))  # date → {metric → [values]}

    relevant = 0
    total = 0

    for event, elem in ET.iterparse(xml_path, events=('end',)):
        if elem.tag != 'Record':
            elem.clear()
            continue

        total += 1
        rtype = elem.get('type', '')

        if rtype not in TYPES_OF_INTEREST:
            elem.clear()
            continue

        relevant += 1
        date_str = elem.get('startDate', '')
        value_str = elem.get('value', '')
        source = elem.get('sourceName', 'Unknown')

        dt = parse_date(date_str)
        if not dt or not value_str:
            elem.clear()
            continue

        date_key = dt.strftime('%Y-%m-%d')
        ts_key = dt.strftime('%Y-%m-%d %H:%M:%S')

        try:
            value = float(value_str)
        except ValueError:
            elem.clear()
            continue

        # --- Вес ---
        if rtype == 'HKQuantityTypeIdentifierBodyMass':
            weight_data.append({
                'date': date_key,
                'time': dt.strftime('%H:%M:%S'),
                'weight_kg': value,
                'source': source,
            })

        # --- Артериальное давление ---
        elif rtype == 'HKQuantityTypeIdentifierBloodPressureSystolic':
            systolic_by_ts[ts_key] = value
        elif rtype == 'HKQuantityTypeIdentifierBloodPressureDiastolic':
            diastolic_by_ts[ts_key] = value

        # --- Пульс в покое ---
        elif rtype == 'HKQuantityTypeIdentifierRestingHeartRate':
            hr_resting.append({
                'date': date_key,
                'time': dt.strftime('%H:%M:%S'),
                'bpm': int(value),
                'type': 'resting',
                'source': source,
            })

        # --- Шаги (только Garmin Watch — единственный достоверный источник) ---
        # Apple Health НЕ дедуплицирует: Garmin Watch + iPhone + Zepp Life все суммировались бы.
        # Решение: приоритет Garmin (Connect), fallback на iPhone если Garmin нет.
        # Zepp Life (весы) — игнорируем (дублируют и не точные).
        elif rtype == 'HKQuantityTypeIdentifierStepCount':
            if 'Connect' in source:
                # Garmin — суммируем за день (Garmin пишет интервалами, не одной записью)
                if steps_src_by_day.get(date_key) != 'garmin':
                    # Первая запись от Garmin — сбрасываем данные от других источников
                    steps_by_day[date_key] = 0
                    steps_src_by_day[date_key] = 'garmin'
                steps_by_day[date_key] += value
            elif 'iPhone' in source or 'Lyskovsky' in source or 'Alex' in source:
                # iPhone — только если Garmin не дал данных за этот день
                if steps_src_by_day.get(date_key) != 'garmin':
                    steps_src_by_day[date_key] = 'iphone'
                    steps_by_day[date_key] += value
            # Zepp Life и прочие — игнорируем

        # --- Характеристики ходьбы ---
        elif rtype in GAIT_METRICS:
            metric_key = GAIT_METRICS[rtype]
            # Доли → проценты
            if rtype in FRACTION_METRICS:
                value = value * 100
            gait_by_day[date_key][metric_key].append(value)

        if relevant % 50000 == 0:
            print(f"   ... релевантных записей: {relevant:,}")

        elem.clear()

    print(f"   Всего записей: {total:,}, релевантных: {relevant:,}")

    # Объединяем АД (пары систолическое + диастолическое)
    bp_data = []
    for ts in sorted(systolic_by_ts):
        if ts in diastolic_by_ts:
            d = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
            bp_data.append({
                'date': d.strftime('%Y-%m-%d'),
                'time': d.strftime('%H:%M:%S'),
                'systolic': int(systolic_by_ts[ts]),
                'diastolic': int(diastolic_by_ts[ts]),
            })

    # Суточные шаги
    steps_daily = [
        {'date': d, 'steps': int(v)}
        for d, v in sorted(steps_by_day.items())
    ]

    # Суточные гайт-метрики (усредняем несколько измерений за день)
    gait_daily = []
    for date_key in sorted(gait_by_day.keys()):
        entry = {'date': date_key}
        m = gait_by_day[date_key]
        for metric_key in ('speed_km_h', 'step_length_cm', 'double_support_pct', 'asymmetry_pct'):
            if metric_key in m and m[metric_key]:
                entry[metric_key] = round(sum(m[metric_key]) / len(m[metric_key]), 2)
        gait_daily.append(entry)

    # Сортировка
    weight_data.sort(key=lambda x: (x['date'], x['time']))
    bp_data.sort(key=lambda x: (x['date'], x['time']))
    hr_resting.sort(key=lambda x: (x['date'], x['time']))

    return {
        'weight': weight_data,
        'blood_pressure': bp_data,
        'heart_rate': hr_resting,
        'steps_daily': steps_daily,
        'gait_daily': gait_daily,
    }


def get_daily_weight_averages(weight_data):
    """Суточные средние значения веса."""
    daily = defaultdict(list)
    for e in weight_data:
        daily[e['date']].append(e['weight_kg'])
    return [
        {'date': d, 'weight_kg': round(sum(v) / len(v), 2), 'measurements_count': len(v)}
        for d, v in sorted(daily.items())
    ]


def save_results(data):
    """Сохраняет все данные в JSON файлы."""
    saved = []

    # Вес — все замеры
    f = DATA_DIR / 'apple_health_weight.json'
    f.write_text(json.dumps({'measurements': data['weight']}, ensure_ascii=False, indent=2))
    saved.append(f"✅ Вес (замеры): {len(data['weight'])} → apple_health_weight.json")

    # Вес — суточные средние
    daily_w = get_daily_weight_averages(data['weight'])
    f = DATA_DIR / 'apple_health_weight_daily.json'
    f.write_text(json.dumps({'daily_averages': daily_w}, ensure_ascii=False, indent=2))
    saved.append(f"✅ Вес (дни): {len(daily_w)} дней → apple_health_weight_daily.json")

    # АД
    f = DATA_DIR / 'apple_health_blood_pressure.json'
    f.write_text(json.dumps({'measurements': data['blood_pressure']}, ensure_ascii=False, indent=2))
    saved.append(f"✅ АД: {len(data['blood_pressure'])} измерений → apple_health_blood_pressure.json")

    # Пульс в покое
    f = DATA_DIR / 'apple_health_heart_rate.json'
    f.write_text(json.dumps({'measurements': data['heart_rate']}, ensure_ascii=False, indent=2))
    saved.append(f"✅ Пульс покоя: {len(data['heart_rate'])} записей → apple_health_heart_rate.json")

    # Шаги (суточные суммы)
    f = DATA_DIR / 'apple_health_steps_daily.json'
    f.write_text(json.dumps({'steps_by_day': data['steps_daily']}, ensure_ascii=False, indent=2))
    saved.append(f"✅ Шаги: {len(data['steps_daily'])} дней → apple_health_steps_daily.json")

    # Характеристики ходьбы
    f = DATA_DIR / 'apple_health_gait.json'
    f.write_text(json.dumps({'gait_by_day': data['gait_daily']}, ensure_ascii=False, indent=2))
    saved.append(f"✅ Ходьба: {len(data['gait_daily'])} дней → apple_health_gait.json")

    return saved


def print_summary(data):
    """Выводит краткую сводку по последним данным."""
    print("\n📊 Последние значения:")

    if data['weight']:
        w = data['weight'][-1]
        print(f"   Вес:         {w['weight_kg']} кг ({w['date']})")

    if data['blood_pressure']:
        bp = data['blood_pressure'][-1]
        print(f"   АД:          {bp['systolic']}/{bp['diastolic']} ({bp['date']} {bp['time']})")

    if data['heart_rate']:
        hr = data['heart_rate'][-1]
        print(f"   Пульс покоя: {hr['bpm']} уд/мин ({hr['date']})")

    if data['steps_daily']:
        # Последние 7 дней
        last7 = data['steps_daily'][-7:]
        avg = round(sum(d['steps'] for d in last7) / len(last7))
        s = data['steps_daily'][-1]
        print(f"   Шаги:        {s['steps']:,} ({s['date']}), ср. 7 дней: {avg:,}")

    if data['gait_daily']:
        g = data['gait_daily'][-1]
        speed = g.get('speed_km_h', '?')
        ds = g.get('double_support_pct', '?')
        asym = g.get('asymmetry_pct', '?')
        print(f"   Ходьба:      {speed} км/ч, двойн.опора {ds}%, асимм. {asym}% ({g['date']})")

    # Период данных
    print("\n📅 Периоды:")
    for label, field, key in [
        ("Вес", 'weight', 'date'),
        ("АД", 'blood_pressure', 'date'),
        ("Шаги", 'steps_daily', 'date'),
        ("Ходьба", 'gait_daily', 'date'),
    ]:
        arr = data[field]
        if arr:
            first = arr[0][key]
            last = arr[-1][key]
            print(f"   {label}: {first} → {last} ({len(arr)} записей)")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Импорт данных из Apple Health Export')
    parser.add_argument(
        '--export_xml', type=str, default=None,
        help='Путь к export.xml (по умолчанию — автопоиск в ~/Downloads/apple_health_export*/)'
    )
    args = parser.parse_args()

    xml_path = args.export_xml
    if not xml_path:
        xml_path = find_latest_export()
        if not xml_path:
            print("❌ Файл export.xml не найден в ~/Downloads/apple_health_export*/")
            print()
            print("Как экспортировать:")
            print("  1. iPhone: Health → Профиль (правый верхний угол) → Экспорт данных")
            print("  2. Разархивируйте полученный zip")
            print("  3. Повторите запуск или укажите путь через --export_xml")
            exit(1)

    print(f"\n🍎 Apple Health Import")
    print(f"{'='*55}")
    print(f"Источник: {xml_path}")
    print(f"Выход: {DATA_DIR}/")
    print()

    data = parse_export(xml_path)

    print(f"\n💾 Сохранение...")
    results = save_results(data)
    for r in results:
        print(f"   {r}")

    print_summary(data)
    print(f"\n✅ Импорт завершён!")
