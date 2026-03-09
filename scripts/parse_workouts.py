#!/usr/bin/env python3
"""
Агрегатор тренировок из Garmin activity summary файлов.
Читает все JSON из data/garmin/activities/ (без _details) и создаёт
data/garmin/workouts_log.json с ключевыми биохакерскими метриками.

Запуск: python3 scripts/parse_workouts.py
"""

import json
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent
ACTIVITIES_DIR = BASE_DIR / "data" / "garmin" / "activities"
OUTPUT_FILE = BASE_DIR / "data" / "garmin" / "workouts_log.json"

# Маппинг typeKey → читаемое название
ACTIVITY_LABELS = {
    "hiit": "ВИИТ",
    "strength_training": "Силовая",
    "running": "Бег",
    "yoga": "Йога",
    "walking": "Ходьба",
    "cycling": "Велосипед",
    "swimming": "Плавание",
    "elliptical": "Эллипс",
    "cardio": "Кардио",
    "fitness_equipment": "Тренажёр",
    "other": "Другое",
}

# Зоны ЧСС (по % от максимального ЧСС)
HR_ZONE_NAMES = {
    1: "Z1 лёгкая (< 60%)",
    2: "Z2 аэробная (60-70%)",
    3: "Z3 аэробная+ (70-80%)",
    4: "Z4 анаэробная (80-90%)",
    5: "Z5 максимум (> 90%)",
}

def parse_activity(filepath: Path):
    """Парсит один summary файл активности."""
    try:
        data = json.loads(filepath.read_text())
    except Exception:
        return None

    # Пропускаем если нет ключевых полей
    if not data.get("activityId"):
        return None

    # Время и дата
    start_local = data.get("startTimeLocal", "")
    end_gmt = data.get("endTimeGMT", "")
    date = start_local[:10] if start_local else "unknown"
    time_of_day = start_local[11:16] if len(start_local) > 10 else "unknown"  # "19:07"

    # Час начала — для анализа "вечерние тренировки"
    try:
        start_hour = int(time_of_day[:2])
    except:
        start_hour = None

    # Тип тренировки
    type_key = data.get("activityType", {}).get("typeKey", "other")
    type_label = ACTIVITY_LABELS.get(type_key, type_key)

    # Основные метрики
    duration_sec = data.get("duration") or data.get("elapsedDuration") or 0
    duration_min = round(duration_sec / 60, 1)

    calories = data.get("calories") or 0
    bmr_calories = data.get("bmrCalories") or 0
    active_calories = max(0, calories - bmr_calories)  # только активные, без базового обмена

    avg_hr = data.get("averageHR")
    max_hr = data.get("maxHR")

    # Тренировочный эффект (шкала 1.0–5.0)
    aerobic_te = round(data.get("aerobicTrainingEffect") or 0, 1)
    anaerobic_te = round(data.get("anaerobicTrainingEffect") or 0, 1)
    te_label = data.get("trainingEffectLabel", "")  # SPEED / AEROBIC_BASE / etc.

    # Training Load — ключевая метрика для восстановления (TRIMP-аналог)
    training_load = round(data.get("activityTrainingLoad") or 0)

    # Body Battery: сколько потратил
    bb_drain = data.get("differenceBodyBattery")  # отрицательное значение

    # Зоны ЧСС (секунды → минуты)
    hr_zones = {}
    for z in range(1, 6):
        secs = data.get(f"hrTimeInZone_{z}") or 0
        hr_zones[f"z{z}_min"] = round(secs / 60, 1)

    # Интенсивные минуты
    vigorous_min = data.get("vigorousIntensityMinutes") or 0
    moderate_min = data.get("moderateIntensityMinutes") or 0

    # Гидратация
    water_ml = round(data.get("waterEstimated") or 0)

    # Аэробные сообщения Garmin
    aerobic_msg = data.get("aerobicTrainingEffectMessage", "")
    anaerobic_msg = data.get("anaerobicTrainingEffectMessage", "")

    # Оценка интенсивности тренировки (для удобного анализа)
    intensity = "light"
    if training_load >= 150:
        intensity = "heavy"
    elif training_load >= 80:
        intensity = "moderate"

    # Флаг вечерней тренировки (после 18:00)
    evening_workout = start_hour is not None and start_hour >= 18

    return {
        "date": date,
        "time": time_of_day,
        "start_hour": start_hour,
        "activity_id": data.get("activityId"),
        "activity_name": data.get("activityName", type_label),
        "type": type_key,
        "type_label": type_label,

        # Нагрузка
        "duration_min": duration_min,
        "calories_total": round(calories),
        "calories_active": round(active_calories),
        "training_load": training_load,
        "intensity": intensity,

        # ЧСС
        "avg_hr": avg_hr,
        "max_hr": max_hr,
        "hr_zones": hr_zones,
        "vigorous_min": vigorous_min,
        "moderate_min": moderate_min,

        # Тренировочный эффект
        "aerobic_te": aerobic_te,
        "anaerobic_te": anaerobic_te,
        "te_label": te_label,

        # Восстановление
        "body_battery_drain": bb_drain,
        "water_ml": water_ml,

        # Контекст для корреляций
        "evening_workout": evening_workout,  # True если начало после 18:00

        # Метаданные
        "raw_messages": {
            "aerobic": aerobic_msg,
            "anaerobic": anaerobic_msg,
        }
    }


def main():
    if not ACTIVITIES_DIR.exists():
        print(f"❌ Папка не найдена: {ACTIVITIES_DIR}")
        return

    # Читаем все summary файлы (без _details)
    files = [f for f in ACTIVITIES_DIR.glob("*.json") if "detail" not in f.name]
    print(f"📂 Найдено {len(files)} файлов активностей")

    workouts = []
    skipped = 0
    for f in files:
        workout = parse_activity(f)
        if workout and workout["date"] != "unknown":
            workouts.append(workout)
        else:
            skipped += 1

    # Сортируем по дате
    workouts.sort(key=lambda x: x["date"])

    # Статистика
    total = len(workouts)
    by_type = {}
    for w in workouts:
        by_type[w["type_label"]] = by_type.get(w["type_label"], 0) + 1

    from_jan6 = [w for w in workouts if w["date"] >= "2026-01-06"]
    evening = [w for w in from_jan6 if w["evening_workout"]]
    heavy = [w for w in from_jan6 if w["intensity"] == "heavy"]
    avg_load = round(sum(w["training_load"] for w in from_jan6) / len(from_jan6)) if from_jan6 else 0
    avg_kcal = round(sum(w["calories_active"] for w in from_jan6) / len(from_jan6)) if from_jan6 else 0

    by_type = {}
    for w in from_jan6:
        by_type[w["type_label"]] = by_type.get(w["type_label"], 0) + 1

    output = {
        "generated_at": datetime.now().isoformat(),
        "total_workouts": total,
        "workouts_since_jan6": len(from_jan6),
        "date_range": {
            "first": workouts[0]["date"] if workouts else None,
            "last": workouts[-1]["date"] if workouts else None,
        },
        "stats_since_jan6": {
            "by_type": by_type,
            "evening_workouts": len(evening),
            "heavy_workouts_load_150plus": len(heavy),
            "avg_training_load": avg_load,
            "avg_active_kcal": avg_kcal,
        },
        "workouts": workouts
    }

    OUTPUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2))

    print(f"\n✅ Сохранено: {OUTPUT_FILE}")
    print(f"\n📊 Статистика с 6 января 2026:")
    print(f"   Всего тренировок:       {len(from_jan6)}")
    print(f"   По типам:               {by_type}")
    print(f"   Вечерние (после 18:00): {len(evening)} ({round(len(evening)/len(from_jan6)*100)}%)" if from_jan6 else "")
    print(f"   Тяжёлые (load ≥ 150):   {len(heavy)}")
    print(f"   Средний Training Load:  {avg_load}")
    print(f"   Средний расход ккал:    {avg_kcal}")
    print()
    print(f"{'Дата':<12} {'Тип':<12} {'Мин':<5} {'Ккал':<6} {'Load':<6} {'Инт.':<10} {'BB-':<5} {'Вечер'}")
    print("-" * 75)
    for w in from_jan6:
        eve = "🌙" if w["evening_workout"] else ""
        heavy_flag = "🔥" if w["intensity"] == "heavy" else ""
        bb = w["body_battery_drain"] or "-"
        print(f"{w['date']:<12} {w['type_label']:<12} {w['duration_min']:<5} {w['calories_active']:<6} {w['training_load']:<6} {w['intensity']:<10} {str(bb):<5} {eve}{heavy_flag}")


if __name__ == "__main__":
    main()
