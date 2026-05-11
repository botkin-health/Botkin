#!/usr/bin/env python3
"""Вычисление aerobic_base_min для каждой тренировки из HR-сэмплов (1 секунда).

Заменяет грубое приближение «Garmin Z1 у cardio = aerobic base» на точный
HR-bin: считаем СЕКУНДЫ в коридоре 115-132 bpm (training-Z2 по Maffetone) для
ЛЮБОГО типа активности. Это правильно ловит CrossFit-метконы с греблей/бегом/велом
внутри — там реально 15-30 мин Z2-кардио, которое старая логика теряла.

Архитектура «hot window + cache»:
  - Garmin details для каждой активности кешируется в
    data/garmin/activities/{stamp}_{aid}_details.json
  - При наличии cache — API не дёргаем
  - HOT window (последние 14 дней) — всегда перепроверяем (могут добавиться новые)
  - Старые без cache — fetch один раз, потом forever cached

Использование:
  python3 scripts/util/compute_aerobic_base.py            # инкрементно (за 90 дней)
  python3 scripts/util/compute_aerobic_base.py --full     # пересчитать всё
  python3 scripts/util/compute_aerobic_base.py --days 14  # окно 14 дней
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
ACTIVITIES_DIR = BASE / "data/garmin/activities"
WORKOUTS_LOG = BASE / "data/garmin/workouts_log.json"

# Maffetone-based 5-zone system (longevity-community canon).
# Границы рассчитываются от user_age (мульти-юзерно):
#   Z1 (recovery)        <maf_floor       — ниже MAF floor, восстановление
#   Z2 (aerobic base)    maf_floor..maf_top — MAF zone (180-age = top)
#   Z3 (tempo · LT1+)    maf_top..lt2-1    — выше MAF, ниже anaerobic threshold
#   Z4 (порог · LT2)     lt2..max90%       — около anaerobic threshold
#   Z5 (VO2max)          >max90%           — для интервалов
#
# Формулы:
#   maf_top = 180 - age           # Maffetone (Z2 ceiling)
#   maf_floor = maf_top - 17      # Maffetone -17 (нижняя граница MAF zone)
#   max_hr = 220 - age            # standard maxHR estimate
#   z4_top = max_hr * 0.90        # LT2 / anaerobic threshold (~90% maxHR)


def compute_zone_boundaries(age: int) -> dict:
    """Вернуть HR-границы 5 Maffetone-зон для заданного возраста."""
    maf_top = 180 - age
    max_hr = 220 - age
    return {
        "z1_top": max(104, maf_top - 18),  # <= z1_top = recovery
        "z2_top": maf_top,  # <= z2_top = aerobic base
        "z3_top": maf_top + 13,  # <= z3_top = темп · LT1+
        "z4_top": round(max_hr * 0.90),  # <= z4_top = порог · LT2
        # Z5: > z4_top
    }


def classify_hr(hr: float, boundaries: dict) -> str:
    """Returns Maffetone zone label for HR value, given user-specific boundaries."""
    if hr <= boundaries["z1_top"]:
        return "z1"
    if hr <= boundaries["z2_top"]:
        return "z2"
    if hr <= boundaries["z3_top"]:
        return "z3"
    if hr <= boundaries["z4_top"]:
        return "z4"
    return "z5"


# Throttle API calls — у Garmin есть rate limit
API_DELAY_SEC = 0.5


def find_metric_index(descriptors: list[dict], key: str) -> int | None:
    """Найти metricsIndex по ключу (API возвращает их в произвольном порядке)."""
    for m in descriptors:
        if m.get("key") == key:
            return m.get("metricsIndex")
    return None


def compute_maf_zones(activity_details: dict, boundaries: dict) -> dict:
    """Распределение HR-сэмплов по 5 Maffetone-зонам.

    Returns: {
        "z1_min": float, "z2_min": float, "z3_min": float, "z4_min": float, "z5_min": float,
        "total_min": float, "avg_hr": float
    }
    """
    desc = activity_details.get("metricDescriptors") or []
    hr_idx = find_metric_index(desc, "directHeartRate")
    if hr_idx is None:
        return {"z1_min": 0, "z2_min": 0, "z3_min": 0, "z4_min": 0, "z5_min": 0, "total_min": 0, "avg_hr": 0}

    metrics = activity_details.get("activityDetailMetrics") or []
    counts = {"z1": 0, "z2": 0, "z3": 0, "z4": 0, "z5": 0}
    hr_sum = 0
    total = 0
    for m in metrics:
        vals = m.get("metrics") or []
        if len(vals) > hr_idx and vals[hr_idx] is not None and vals[hr_idx] > 0:
            hr = vals[hr_idx]
            counts[classify_hr(hr, boundaries)] += 1
            hr_sum += hr
            total += 1
    return {
        "z1_min": round(counts["z1"] / 60.0, 1),
        "z2_min": round(counts["z2"] / 60.0, 1),
        "z3_min": round(counts["z3"] / 60.0, 1),
        "z4_min": round(counts["z4"] / 60.0, 1),
        "z5_min": round(counts["z5"] / 60.0, 1),
        "total_min": round(total / 60.0, 1),
        "avg_hr": round(hr_sum / total, 1) if total else 0,
    }


def find_or_fetch_details(client, aid: int, date_str: str) -> dict | None:
    """Найти cached details file или скачать новый.

    Имя файла: {date}_{HHMM}_{aid}_details.json. Garmin даёт стабильный aid.
    """
    # Поиск любого *_aid_*.json в директории
    pattern = f"*_{aid}_details*.json"
    matches = list(ACTIVITIES_DIR.glob(pattern))
    if matches:
        try:
            return json.loads(matches[0].read_text())
        except Exception:
            pass

    # Cache miss — fetch from API
    print(f"  ↻ Fetching HR samples for {date_str} (aid={aid})...", flush=True)
    try:
        details = client.get_activity_details(aid)
    except Exception as e:
        print(f"    ⚠️  API error: {e}")
        return None

    # Save to cache. Имя совместимое с parse_workouts.py (отфильтрует через "detail in name")
    out_path = ACTIVITIES_DIR / f"{date_str}_{aid}_details.json"
    try:
        out_path.write_text(json.dumps(details, ensure_ascii=False))
    except Exception as e:
        print(f"    ⚠️  Save error: {e}")

    time.sleep(API_DELAY_SEC)
    return details


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90, help="Окно дней (default 90)")
    ap.add_argument("--full", action="store_true", help="Пересчитать все workouts")
    ap.add_argument("--no-fetch", action="store_true", help="Не дёргать API, только cached")
    ap.add_argument(
        "--age",
        type=int,
        default=None,
        help="Возраст для расчёта Maffetone-зон. По умолчанию читает из БД пользователя.",
    )
    ap.add_argument("--user-id", type=int, default=895655, help="Telegram ID пользователя (для чтения возраста из БД)")
    args = ap.parse_args()

    # Определить возраст: явный --age перебивает БД, БД перебивает дефолт 48
    user_age = args.age
    if user_age is None:
        try:
            # Импорт DB-сессии — может не сработать если БД на сервере (как сейчас)
            sys.path.insert(0, str(BASE))
            from database import SessionLocal
            from database.models import User
            from datetime import date as _date

            db = SessionLocal()
            user = db.query(User).filter_by(telegram_id=args.user_id).first()
            if user and user.birth_date:
                user_age = _date.today().year - user.birth_date.year
            db.close()
        except Exception:
            pass
    if user_age is None:
        user_age = 48  # safe default for Alex
        print("⚠️  Возраст не определён, использую default 48")

    boundaries = compute_zone_boundaries(user_age)
    print(f"🎯 Maffetone-зоны для возраста {user_age}:")
    print(f"   Z1 ≤{boundaries['z1_top']}  recovery")
    print(f"   Z2 {boundaries['z1_top'] + 1}-{boundaries['z2_top']}  aerobic base 🔥")
    print(f"   Z3 {boundaries['z2_top'] + 1}-{boundaries['z3_top']}  темп · LT1+")
    print(f"   Z4 {boundaries['z3_top'] + 1}-{boundaries['z4_top']}  порог · LT2")
    print(f"   Z5 ≥{boundaries['z4_top'] + 1}  VO2max")
    print()

    if not WORKOUTS_LOG.exists():
        print(f"❌ {WORKOUTS_LOG} не найден — запусти parse_workouts.py")
        sys.exit(1)

    wd = json.loads(WORKOUTS_LOG.read_text())
    workouts = wd.get("workouts", [])
    if not workouts:
        print("⚠️  Нет тренировок в workouts_log.json")
        return

    today = date.today()
    cutoff = (today - timedelta(days=args.days)).isoformat() if not args.full else "1970-01-01"

    # Init Garmin client only if we need to fetch
    client = None

    def get_client():
        nonlocal client
        if client is None:
            from garminconnect import Garmin

            client = Garmin(os.getenv("GARMIN_EMAIL"), os.getenv("GARMIN_PASSWORD"))
            client.garth.load(BASE / "data/cache/garth_tokens")
        return client

    updated = 0
    skipped = 0
    fetched = 0

    for w in workouts:
        d_str = w.get("date", "")
        if d_str < cutoff:
            continue

        # Если у workout уже есть aerobic_base_min И есть cache → skip (force через --full)
        aid = w.get("activity_id") or w.get("garmin_activity_id")
        if not aid:
            # Попробуем извлечь из source_file
            src = w.get("source_file", "")
            if "_" in src:
                try:
                    aid = int(src.split("_")[-1].replace(".json", ""))
                except (ValueError, IndexError):
                    pass
        if not aid:
            skipped += 1
            continue

        has_cache = bool(list(ACTIVITIES_DIR.glob(f"*_{aid}_details*.json")))
        has_field = "aerobic_base_min" in w

        if has_field and has_cache and not args.full:
            skipped += 1
            continue

        # Fetch / load details
        if args.no_fetch and not has_cache:
            skipped += 1
            continue

        details = find_or_fetch_details(get_client(), aid, d_str)
        if not details:
            skipped += 1
            continue
        if not has_cache:
            fetched += 1

        maf = compute_maf_zones(details, boundaries)
        w["aerobic_base_min"] = maf["z2_min"]
        w["hr_sample_minutes"] = maf["total_min"]
        w["maf_zones"] = {
            "z1_min": maf["z1_min"],
            "z2_min": maf["z2_min"],
            "z3_min": maf["z3_min"],
            "z4_min": maf["z4_min"],
            "z5_min": maf["z5_min"],
        }
        updated += 1

    # Save updated workouts_log
    WORKOUTS_LOG.write_text(json.dumps(wd, ensure_ascii=False, indent=2))

    print(f"\n✅ Обновлено: {updated} тренировок (fetched {fetched}, cached {updated - fetched}, skipped {skipped})")

    # Топ-10 по aerobic_base_min для проверки
    recent = sorted(
        [w for w in workouts if w.get("date", "") >= cutoff and w.get("aerobic_base_min", 0) > 0],
        key=lambda w: w["date"],
        reverse=True,
    )[:10]
    if recent:
        print("\nПоследние тренировки с aerobic_base (HR 115-132):")
        for w in recent:
            t = w.get("type_label", w.get("type", ""))[:20]
            print(
                f"  {w['date']} | {t:20} | {w['aerobic_base_min']:>5.1f} мин в base | "
                f"avg HR {w.get('avg_hr', '?')} | total {w.get('duration_min', '?')}мин"
            )


if __name__ == "__main__":
    main()
