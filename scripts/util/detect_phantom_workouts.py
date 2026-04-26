#!/usr/bin/env python3
"""
Детектор «потерянных» тренировок по минутному пульсу Garmin.

Garmin хранит детальные данные ~последние 6 месяцев. Скрипт ищет дни
без залогированной тренировки, но с характерным паттерном повышенного
ЧСС вечером — CrossFit/силовая с интервальными подъёмами.

Результат → data/garmin/phantom_workouts.json  (is_synthesized=True)
Эти записи мёрджатся в workouts_log через parse_workouts.py.

Запуск:
    python3 scripts/util/detect_phantom_workouts.py          # dry-run
    python3 scripts/util/detect_phantom_workouts.py --save   # сохранить
    python3 scripts/util/detect_phantom_workouts.py --since 2025-11-01
"""

import argparse
import datetime
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
ACTIVITIES_DIR = BASE / "data/garmin/activities"
DAILY_DIR = BASE / "data/garmin/daily-summary"
OUTPUT = BASE / "data/garmin/phantom_workouts.json"
GARTH_HOME = BASE / "data/cache/garth_tokens"

MAX_HR_USER = 172  # Максимальный ЧСС Александра
TZ_OFFSET = 3  # Москва UTC+3


def load_garmin():
    try:
        import garth
    except ImportError:
        print("❌ pip install garth")
        sys.exit(1)
    if not GARTH_HOME.exists():
        print(f"❌ garth-кэш не найден: {GARTH_HOME}")
        sys.exit(1)
    garth.resume(str(GARTH_HOME))
    return garth


def get_hr_series(garth, date_str: str):
    """Загружает минутный ЧСС и конвертирует в московское время."""
    try:
        resp = garth.connectapi(f"/wellness-service/wellness/dailyHeartRate?date={date_str}")
        vals = resp.get("heartRateValues") or []
    except Exception as e:
        print(f"  ⚠️  {date_str}: ошибка API — {e}")
        return []

    series = []
    for ts_ms, hr in vals:
        if hr is None:
            continue
        dt = datetime.datetime.fromtimestamp(ts_ms / 1000) + datetime.timedelta(hours=TZ_OFFSET)
        series.append((dt, hr))
    return series


def find_workout_window(series):
    """
    Скользящее окно 65 мин — ищет лучший вечерний блок (15:00–23:59)
    с признаками интенсивной нагрузки:
      - ≥35% точек с ЧСС ≥ 90 bpm
      - max ЧСС ≥ 110 bpm
    CrossFit/силовая даёт именно такой паттерн: чередование подъёмов
    и пауз, поэтому не требуем непрерывного блока.
    """
    filtered = [(dt, hr) for dt, hr in series if 15 <= dt.hour <= 23]
    if not filtered:
        return None

    WINDOW_MIN = 65
    MIN_ELEVATED_PCT = 0.35
    MIN_MAX_HR = 110

    best = None
    best_score = 0

    for start_dt, _ in filtered:
        end_dt = start_dt + datetime.timedelta(minutes=WINDOW_MIN)
        window = [(dt, hr) for dt, hr in filtered if start_dt <= dt <= end_dt]
        if len(window) < 15:
            continue

        max_hr = max(hr for _, hr in window)
        avg_hr = sum(hr for _, hr in window) / len(window)
        elevated = [p for p in window if p[1] >= 90]
        pct = len(elevated) / len(window)

        if pct < MIN_ELEVATED_PCT or max_hr < MIN_MAX_HR:
            continue

        score = max_hr * pct
        if score > best_score:
            best_score = score
            # Реальное начало/конец по первой/последней точке ≥ 90
            first_e = next((dt for dt, hr in window if hr >= 90), start_dt)
            last_e = max((dt for dt, hr in window if hr >= 90), default=end_dt)
            dur = (last_e - first_e).total_seconds() / 60 + 4

            # Пропускаем слишком короткие (<40 мин) или длинные (>100 мин)
            if dur < 40 or dur > 100:
                # Пробуем взять полное окно если оно в норме
                dur_full = (window[-1][0] - window[0][0]).total_seconds() / 60 + 4
                if dur_full < 40 or dur_full > 100:
                    continue
                first_e = window[0][0]
                last_e = window[-1][0]
                dur = dur_full

            best = {
                "start_dt": first_e,
                "end_dt": last_e,
                "dur_min": round(dur),
                "avg_hr": round(avg_hr),
                "max_hr": max_hr,
                "window": window,
            }
    return best


def calc_zones(window_pts, max_hr=MAX_HR_USER):
    """HR-зоны (минуты): каждая точка ≈ 2 мин."""
    z = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    bounds = [0.6 * max_hr, 0.7 * max_hr, 0.8 * max_hr, 0.9 * max_hr]
    for _, hr in window_pts:
        if hr < bounds[0]:
            z[1] += 1
        elif hr < bounds[1]:
            z[2] += 1
        elif hr < bounds[2]:
            z[3] += 1
        elif hr < bounds[3]:
            z[4] += 1
        else:
            z[5] += 1
    return {f"z{k}_min": round(v * 2) for k, v in z.items()}


def get_existing_activity_dates():
    """Даты дней, где есть залогированные тренировки."""
    dates = set()
    for f in ACTIVITIES_DIR.glob("*.json"):
        if "detail" in f.name:
            continue
        try:
            d = json.loads(f.read_text())
            start = d.get("startTimeLocal", "")
            if start:
                dates.add(start[:10])
        except Exception:
            pass
    return dates


def build_phantom(date_str: str, workout: dict) -> dict:
    """Строит запись в формате workouts_log.json."""
    start_hour = workout["start_dt"].hour
    evening = start_hour >= 18
    zones = calc_zones(workout["window"])
    total_z = sum(zones.values()) or 1
    high_pct = (zones["z4_min"] + zones["z5_min"]) / total_z * 100

    # Training load оценка (≈ Garmin TRIMP/Acute Load, шкала 50-300)
    # Зависит от длительности и интенсивности (avgHR vs maxHR пользователя)
    hr_pct = workout["avg_hr"] / MAX_HR_USER  # 0.54–0.70 типично для Z2-Z3
    # Линейная аппроксимация: 50 мин в Z2 (avgHR~100) ≈ load 100
    estimated_load = round(workout["dur_min"] * hr_pct * 2.8)
    # Calories: ~5 ккал/мин при avgHR 100+ bpm, минус базовый обмен
    calories = round(workout["dur_min"] * 5.2)
    bmr_min = 1.2  # ~70 ккал/ч базовый обмен
    active_cal = round(calories - workout["dur_min"] * bmr_min)

    intensity = "heavy" if estimated_load >= 150 else ("moderate" if estimated_load >= 80 else "light")
    confidence = "high" if workout["max_hr"] >= 130 else ("medium" if workout["max_hr"] >= 115 else "low")

    return {
        "date": date_str,
        "time": workout["start_dt"].strftime("%H:%M"),
        "start_hour": start_hour,
        "activity_id": None,
        "activity_name": "Силовая (восстановлено)",
        "type": "strength_training",
        "type_label": "Силовая",
        "classification": "strength_training",
        "is_misnamed": False,
        "suggested_type": None,
        "high_zone_pct": round(high_pct, 1),
        # Нагрузка
        "duration_min": workout["dur_min"],
        "calories_total": calories,
        "calories_active": active_cal,
        "training_load": estimated_load,
        "intensity": intensity,
        # ЧСС
        "avg_hr": workout["avg_hr"],
        "max_hr": workout["max_hr"],
        "hr_zones": zones,
        "vigorous_min": zones["z4_min"] + zones["z5_min"],
        "moderate_min": zones["z3_min"],
        # Тренировочный эффект
        "aerobic_te": 0,
        "anaerobic_te": 0,
        "te_label": "",
        # Восстановление
        "body_battery_drain": None,
        "water_ml": 0,
        # Контекст
        "evening_workout": evening,
        # Метаданные синтеза
        "is_synthesized": True,
        "synthesis_confidence": confidence,
        "raw_messages": {
            "aerobic": "",
            "anaerobic": f"Восстановлено из минутного ЧСС (confidence={confidence})",
        },
    }


def main():
    ap = argparse.ArgumentParser(description="Детектор потерянных тренировок из ЧСС")
    ap.add_argument("--since", default="2025-12-01", help="Начало периода YYYY-MM-DD")
    ap.add_argument("--until", default="2025-12-31", help="Конец периода YYYY-MM-DD")
    ap.add_argument("--min-max-hr", type=int, default=115, help="Мин. max ЧСС для включения")
    ap.add_argument("--save", action="store_true", help="Сохранить в phantom_workouts.json")
    args = ap.parse_args()

    garth = load_garmin()
    existing = get_existing_activity_dates()

    start_date = datetime.date.fromisoformat(args.since)
    end_date = datetime.date.fromisoformat(args.until)

    print(f"\n🔍 Поиск потерянных тренировок: {args.since} — {args.until}")
    print(f"   Мин. max ЧСС: {args.min_max_hr} bpm\n")

    phantoms = []
    d = start_date
    while d <= end_date:
        ds = str(d)
        wday = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d.weekday()]

        if ds in existing:
            print(f"  [{ds} {wday}]: есть тренировка в Garmin")
            d += datetime.timedelta(days=1)
            continue

        series = get_hr_series(garth, ds)
        if not series:
            print(f"  [{ds} {wday}]: нет данных ЧСС (Garmin не хранит >6 мес)")
            d += datetime.timedelta(days=1)
            continue

        w = find_workout_window(series)
        if w and w["max_hr"] >= args.min_max_hr:
            phantom = build_phantom(ds, w)
            phantoms.append(phantom)
            conf_icon = "🔥" if w["max_hr"] >= 130 else "⚡"
            print(
                f"{conf_icon} {ds} {wday}: "
                f"{w['start_dt'].strftime('%H:%M')}–{w['end_dt'].strftime('%H:%M')} "
                f"({w['dur_min']} мин) "
                f"avgHR={w['avg_hr']} maxHR={w['max_hr']} "
                f"[{phantom['synthesis_confidence']}]"
            )
        else:
            max_day = max((hr for _, hr in series), default=0)
            print(f"   {ds} {wday}: нет паттерна тренировки (max ЧСС={max_day})")

        d += datetime.timedelta(days=1)

    print(f"\n{'=' * 60}")
    print(f"Найдено потерянных тренировок: {len(phantoms)}")
    if phantoms:
        high = sum(1 for p in phantoms if p["synthesis_confidence"] == "high")
        med = sum(1 for p in phantoms if p["synthesis_confidence"] == "medium")
        print(f"  🔥 High confidence: {high}")
        print(f"  ⚡ Medium confidence: {med}")
        print(f"  · Low confidence: {len(phantoms) - high - med}")

        print(f"\n{'Дата':<12} {'День':3} {'Время':6} {'Мин':5} {'avgHR':7} {'maxHR':7} {'Load':6}")
        print("-" * 60)
        for p in phantoms:
            d2 = datetime.date.fromisoformat(p["date"])
            wday = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][d2.weekday()]
            print(
                f"{p['date']:<12} {wday:3} {p['time']:6} "
                f"{p['duration_min']:<5} {p['avg_hr']:<7} {p['max_hr']:<7} {p['training_load']:<6}"
            )

    if args.save:
        output = {
            "generated_at": datetime.datetime.now().isoformat(),
            "source": "minute-level Garmin HR (daily wellness API)",
            "period": {"since": args.since, "until": args.until},
            "note": "Восстановленные тренировки — только для локальной аналитики",
            "total": len(phantoms),
            "workouts": phantoms,
        }
        OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2))
        print(f"\n✅ Сохранено: {OUTPUT}")
        print("   Следующий шаг: python3 scripts/util/parse_workouts.py")
    else:
        print("\n💡 Dry-run. Добавь --save для сохранения.")


if __name__ == "__main__":
    main()
