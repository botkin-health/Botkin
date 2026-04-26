#!/usr/bin/env python3
"""
Пакетно переименовывает неправильно затегированные тренировки в Garmin Connect.

Логика:
  1. Читает data/garmin/workouts_log.json
  2. Берёт записи где is_misnamed=True (HIIT-тег при <10% времени в Z4+Z5)
  3. Показывает таблицу: дата, текущий тег, предложение, % высоких зон
  4. Спрашивает подтверждение
  5. Через Garmin Connect API меняет activityTypeDTO на suggested_type

Использование:
  python3 scripts/util/rename_garmin_activities.py            # dry-run, только показать
  python3 scripts/util/rename_garmin_activities.py --apply    # реально переименовать
  python3 scripts/util/rename_garmin_activities.py --apply --since 2026-01-01
"""

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
WORKOUTS_LOG = BASE / "data/garmin/workouts_log.json"
GARTH_HOME = BASE / "data/cache/garth_tokens"

# Garmin activity typeId → typeKey mapping (нужны оба для PUT)
# Источник: GET /activity-service/activity/activityTypes
TYPE_MAP = {
    "strength_training": {"typeId": 13, "typeKey": "strength_training", "parentTypeId": 9},
    "cardio": {"typeId": 26, "typeKey": "cardio", "parentTypeId": 26},
    "fitness_equipment": {"typeId": 9, "typeKey": "fitness_equipment", "parentTypeId": 9},
    "running": {"typeId": 1, "typeKey": "running", "parentTypeId": 1},
    "yoga": {"typeId": 95, "typeKey": "yoga", "parentTypeId": 95},
    "hiit": {"typeId": 169, "typeKey": "hiit", "parentTypeId": 9},
}


def load_garmin_client():
    try:
        from garminconnect import Garmin
        import garth
    except ImportError:
        print("❌ Установи: pip install garminconnect garth")
        sys.exit(1)

    if not GARTH_HOME.exists():
        print(f"❌ Нет кэша garth в {GARTH_HOME}. Залогинься через scripts/garmin/download_garmin_data.py")
        sys.exit(1)

    try:
        garth.resume(str(GARTH_HOME))
        client = Garmin()
        client.garth = garth.client
        client.username = garth.client.username
        return client
    except Exception as e:
        print(f"❌ Ошибка авторизации: {e}")
        sys.exit(1)


def rename_activity(client, activity_id: int, new_type_key: str) -> bool:
    """PUT /activity-service/activity/{id} с обновлённым activityTypeDTO."""
    if new_type_key not in TYPE_MAP:
        print(f"   ⚠️  Неизвестный typeKey: {new_type_key}")
        return False

    type_info = TYPE_MAP[new_type_key]
    payload = {
        "activityId": activity_id,
        "activityTypeDTO": {
            "typeKey": type_info["typeKey"],
            "typeId": type_info["typeId"],
            "parentTypeId": type_info["parentTypeId"],
        },
    }

    try:
        # garminconnect клиент использует connectapi() для произвольных запросов
        client.garth.put(
            "connectapi",
            f"/activity-service/activity/{activity_id}",
            json=payload,
            api=True,
        )
        return True
    except Exception as e:
        print(f"   ❌ Ошибка для activity {activity_id}: {e}")
        return False


def main():
    ap = argparse.ArgumentParser(description="Переименовать неправильно затегированные тренировки Garmin")
    ap.add_argument("--apply", action="store_true", help="Реально применить (без флага — dry-run)")
    ap.add_argument("--since", default="2026-01-01", help="С какой даты обрабатывать (YYYY-MM-DD)")
    ap.add_argument("--limit", type=int, default=0, help="Максимум записей (0 = все)")
    args = ap.parse_args()

    if not WORKOUTS_LOG.exists():
        print(f"❌ Нет файла {WORKOUTS_LOG}. Запусти scripts/util/parse_workouts.py")
        sys.exit(1)

    data = json.loads(WORKOUTS_LOG.read_text())
    workouts = data.get("workouts", [])

    seen_ids = set()
    misnamed = []
    for w in workouts:
        if not w.get("is_misnamed"):
            continue
        if w.get("date", "") < args.since:
            continue
        if not w.get("suggested_type"):
            continue
        aid = w.get("activity_id")
        if aid in seen_ids:
            continue
        seen_ids.add(aid)
        misnamed.append(w)
    misnamed.sort(key=lambda x: x["date"], reverse=True)

    if args.limit:
        misnamed = misnamed[: args.limit]

    if not misnamed:
        print(f"✅ Нет неправильно затегированных тренировок с {args.since}")
        return

    # Превью
    print(f"\n📋 Найдено {len(misnamed)} тренировок для переименования (с {args.since}):\n")
    print(f"{'Дата':<12} {'ID':<14} {'Текущий':<8} {'→':<3} {'Предложение':<20} {'Z4+Z5%':<7} {'avgHR':<6}")
    print("─" * 80)
    for w in misnamed:
        print(
            f"{w['date']:<12} {w['activity_id']:<14} {w['type']:<8} → "
            f"{w['suggested_type']:<20} {w['high_zone_pct']:<7} {round(w.get('avg_hr') or 0):<6}"
        )

    if not args.apply:
        print("\n💡 Это dry-run. Запусти с --apply чтобы реально переименовать.")
        return

    # Подтверждение
    confirm = input(f"\n❓ Переименовать {len(misnamed)} тренировок в Garmin? (yes/no): ").strip().lower()
    if confirm not in ("yes", "y", "да", "д"):
        print("⏭  Отмена.")
        return

    # Логин и применение
    print("\n🔑 Подключаюсь к Garmin...")
    client = load_garmin_client()
    print("✅ Подключено\n")

    ok = 0
    for w in misnamed:
        result = rename_activity(client, w["activity_id"], w["suggested_type"])
        status = "✅" if result else "❌"
        print(f"  {status} {w['date']} {w['type']} → {w['suggested_type']} (id={w['activity_id']})")
        if result:
            ok += 1

    print(f"\n📊 Итог: {ok}/{len(misnamed)} переименовано успешно")
    if ok > 0:
        print("💡 Запусти scripts/garmin/download_garmin_data.py чтобы обновить локальные JSON")
        print("   и потом scripts/util/parse_workouts.py чтобы пересчитать workouts_log")


if __name__ == "__main__":
    main()
