#!/usr/bin/env python3
"""
server_backfill_postgres.py — серверный сборщик Garmin-данных в Postgres.

Запускается ВНУТРИ контейнера healthvault_bot (а не с мака!), вызывается из
scripts/server/sync_all.sh после garmin-импорта.

Закрывает «дыру третьего источника»: до 24.05.2026 эти таблицы наполнялись
только мак-скриптом scripts/backfill_to_postgres.py. Если мак не запускали —
бот в /recent_workouts и /recent_activity отвечал устаревшими данными даже
когда дашборд (читающий из workouts_log_<id>.json) показывал свежие. История
в DEV_LOG, AI_CHANGELOG 24.05.

Что синхронизируем:
  1. Тренировки (Garmin activities JSON)        → workouts
  2. Сон (Garmin sleep JSON)                    → activity_log.sleep_hours/raw_data
  3. HRV (Garmin HRV JSON)                      → activity_log.hrv

Что НЕ синхронизируем здесь:
  - Веса (Zepp CSV) — Zepp-токен живёт на маке, выгрузка тоже там; Apple Health
    HAE webhook пишет вес напрямую в weights с iPhone, так что веса покрыты.
  - Шаги/пульс/АД — приходят через /apple_health_v2 webhook реалтаймом.
  - Биомаркеры — 3-stage pipeline в generate_biomarkers_json.py.

Usage:
    python3 scripts/util/server_backfill_postgres.py
    python3 scripts/util/server_backfill_postgres.py --user-id 895655
    python3 scripts/util/server_backfill_postgres.py --since 2026-05-01
    python3 scripts/util/server_backfill_postgres.py --only workouts --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras

# Дефолт — Александр (единственный активный Garmin-пользователь на 24.05.2026).
# Когда подключатся другие — нужно будет:
#   1) разложить data/garmin/ на data/garmin/{user_id}/
#   2) sync_all.sh — вызывать скрипт по разу на каждого user_id
# (parse_workouts.py / build_workouts_log.py имеют такую же TODO-точку расширения)
DEFAULT_USER_ID = 895655

# По умолчанию синкаем только 2026 год — то что было раньше уже бэкфилл'нуто
# одноразово через мак. И ограничивает время работы каждой ночи.
DEFAULT_SINCE = "2026-01-01"

BASE = Path("/app")  # внутри контейнера
GARMIN_ACTS = BASE / "data" / "garmin" / "activities"
GARMIN_SLEEP = BASE / "data" / "garmin" / "sleep"
GARMIN_HRV = BASE / "data" / "garmin" / "hrv"
GARMIN_STRESS = BASE / "data" / "garmin" / "stress"

# Маппинг Garmin typeKey → workout_type в нашей БД.
# Совпадает с backfill_to_postgres.py — менять синхронно в обоих местах.
_TYPE_MAP = {
    "running": "running",
    "trail_running": "running",
    "cycling": "cycling",
    "indoor_cycling": "cycling",
    "swimming": "swimming",
    "open_water_swimming": "swimming",
    "strength_training": "strength_training",
    "fitness_equipment": "strength_training",
    "hiit": "hiit",
    "cardio_training": "cardio",
    "yoga": "yoga",
    "pilates": "yoga",
    "walking": "walking",
    "hiking": "walking",
    "elliptical": "elliptical",
}


# ── workouts ────────────────────────────────────────────────────────────────


def sync_workouts(conn, user_id: int, since: str, dry_run: bool) -> dict:
    """Заливает новые Garmin activities в таблицу workouts. Идемпотентно."""
    cur = conn.cursor()
    cur.execute(
        "SELECT date::text, distance_km FROM workouts WHERE user_id=%s AND date >= %s",
        (user_id, since),
    )
    existing: dict[str, float | None] = {row[0]: row[1] for row in cur.fetchall()}

    to_insert: list[tuple] = []
    to_update_dist: list[tuple[str, float]] = []

    if not GARMIN_ACTS.exists():
        return {"status": "no_source", "inserted": 0, "updated": 0}

    for f in sorted(GARMIN_ACTS.glob("*.json")):
        if "detail" in f.name:
            continue
        if f.name[:10] < since:
            continue
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue

        start_local = data.get("startTimeLocal", "")
        if not start_local or start_local[:10] < since:
            continue

        act_type_key = (data.get("activityType") or {}).get("typeKey", "other")
        workout_type = _TYPE_MAP.get(act_type_key, act_type_key)
        duration_sec = data.get("duration") or data.get("elapsedDuration") or 0
        duration_min = max(1, round(duration_sec / 60))
        distance_m = data.get("distance") or 0
        distance_km = round(distance_m / 1000, 3) if distance_m else None
        calories = int(data.get("calories") or 0) or None

        try:
            start_dt = datetime.strptime(start_local, "%Y-%m-%d %H:%M:%S")
            start_dt = start_dt.replace(tzinfo=timezone(timedelta(hours=3)))
            end_dt = start_dt + timedelta(minutes=duration_min)
        except Exception:
            continue

        work_date = start_local[:10]
        src_id = data.get("activityId", "")

        if work_date in existing:
            # Уже есть запись — обновляем дистанцию если её раньше не было
            if distance_km and existing[work_date] is None:
                to_update_dist.append((work_date, distance_km))
        else:
            to_insert.append(
                (
                    user_id,
                    work_date,
                    workout_type,
                    duration_min,
                    start_dt,
                    end_dt,
                    calories,
                    distance_km,
                    f"garmin_{src_id}",
                )
            )
            existing[work_date] = distance_km

    if dry_run:
        print(f"  [dry-run] workouts: вставить {len(to_insert)}, обновить дистанцию у {len(to_update_dist)}")
        return {"status": "dry", "inserted": len(to_insert), "updated": len(to_update_dist)}

    if to_insert:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO workouts
               (user_id, date, workout_type, duration_minutes, start_time,
                end_time, calories_burned, distance_km, source)
               VALUES %s
               ON CONFLICT DO NOTHING""",
            to_insert,
        )

    for work_date, dist_km in to_update_dist:
        cur.execute(
            "UPDATE workouts SET distance_km=%s WHERE user_id=%s AND date=%s AND distance_km IS NULL",
            (dist_km, user_id, work_date),
        )

    conn.commit()
    cur.close()
    return {"status": "ok", "inserted": len(to_insert), "updated": len(to_update_dist)}


# ── sleep ───────────────────────────────────────────────────────────────────


def sync_sleep(conn, user_id: int, since: str, dry_run: bool) -> dict:
    """Заливает sleep_hours / sleep_score / deep_h / rem_h в activity_log."""
    cur = conn.cursor()
    cur.execute(
        "SELECT date::text FROM activity_log WHERE user_id=%s AND date >= %s AND sleep_hours IS NOT NULL",
        (user_id, since),
    )
    existing = {row[0] for row in cur.fetchall()}

    sleep_data: dict[str, dict] = {}
    if not GARMIN_SLEEP.exists():
        return {"status": "no_source", "inserted": 0, "updated": 0}

    for f in sorted(GARMIN_SLEEP.glob("*.json")):
        # имена файлов вида 2026-05-22.json или 20260522.json — оба отсекаем по since
        if f.name[:4] not in {"2024", "2025", "2026", "2027", "2028"}:
            continue
        try:
            raw = json.loads(f.read_text())
        except Exception:
            continue
        dto = (raw or {}).get("dailySleepDTO") or {}
        cal_date = dto.get("calendarDate", "")
        if not cal_date or cal_date < since:
            continue

        sleep_sec = dto.get("sleepTimeSeconds") or 0
        if sleep_sec <= 0:
            continue
        scores = dto.get("sleepScores") or {}
        sleep_score = (scores.get("overall") or {}).get("value")

        sleep_data[cal_date] = {
            "sleep_h": round(sleep_sec / 3600, 2),
            "deep_h": round((dto.get("deepSleepSeconds") or 0) / 3600, 2),
            "rem_h": round((dto.get("remSleepSeconds") or 0) / 3600, 2),
            "sleep_score": int(sleep_score) if sleep_score else None,
        }

    new_dates = {d: v for d, v in sleep_data.items() if d not in existing}

    if dry_run:
        print(f"  [dry-run] sleep: добавить/обновить {len(new_dates)} дней")
        return {"status": "dry", "inserted": len(new_dates), "updated": 0}

    for cal_date, sv in sorted(new_dates.items()):
        raw_upd = json.dumps({"sleep_score": sv["sleep_score"], "deep_h": sv["deep_h"], "rem_h": sv["rem_h"]})
        cur.execute(
            """INSERT INTO activity_log (user_id, date, sleep_hours, raw_data, source)
               VALUES (%s, %s, %s, %s::jsonb, %s)
               ON CONFLICT (user_id, date) DO UPDATE
                 SET sleep_hours = EXCLUDED.sleep_hours,
                     raw_data = COALESCE(activity_log.raw_data, '{}'::jsonb) || EXCLUDED.raw_data""",
            (user_id, cal_date, sv["sleep_h"], raw_upd, "garmin_sleep"),
        )

    conn.commit()
    cur.close()
    return {"status": "ok", "inserted": len(new_dates), "updated": 0}


# ── hrv ─────────────────────────────────────────────────────────────────────


def sync_hrv(conn, user_id: int, since: str, dry_run: bool) -> dict:
    """Заливает lastNightAvg HRV в activity_log.hrv."""
    cur = conn.cursor()
    cur.execute(
        "SELECT date::text FROM activity_log WHERE user_id=%s AND date >= %s AND hrv IS NOT NULL",
        (user_id, since),
    )
    existing = {row[0] for row in cur.fetchall()}

    if not GARMIN_HRV.exists():
        return {"status": "no_source", "inserted": 0, "updated": 0}

    hrv_data: dict[str, int] = {}
    for f in sorted(GARMIN_HRV.glob("*.json")):
        if f.name[:4] not in {"2024", "2025", "2026", "2027", "2028"}:
            continue
        try:
            raw = json.loads(f.read_text())
        except Exception:
            continue
        if raw is None:
            continue
        summ = raw.get("hrvSummary") or {}
        cal_date = summ.get("calendarDate", "")
        if not cal_date or cal_date < since:
            continue
        hrv_val = summ.get("lastNightAvg")
        if hrv_val and int(hrv_val) > 0:
            hrv_data[cal_date] = int(hrv_val)

    new_dates = {d: v for d, v in hrv_data.items() if d not in existing}

    if dry_run:
        print(f"  [dry-run] hrv: добавить {len(new_dates)} дней")
        return {"status": "dry", "inserted": len(new_dates), "updated": 0}

    for cal_date, hrv_val in sorted(new_dates.items()):
        cur.execute(
            """INSERT INTO activity_log (user_id, date, hrv, source)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (user_id, date) DO UPDATE
                 SET hrv = EXCLUDED.hrv""",
            (user_id, cal_date, hrv_val, "garmin_hrv"),
        )

    conn.commit()
    cur.close()
    return {"status": "ok", "inserted": len(new_dates), "updated": 0}


# ── stress + body battery ────────────────────────────────────────────────────


def sync_stress(conn, user_id: int, since: str, dry_run: bool) -> dict:
    """avgStressLevel → колонка stress_level; bodyBattery high/low → raw_data.

    Файлы Garmin stress/ содержат и стресс, и bodyBatteryValuesArray. Раньше эти
    поля наполнялись лишь изредка через daily-summary → агентский recent_trends
    видел стресс/bodyBattery пустыми (тот же класс бага, что был со сном —
    reader читал raw_data-поле, которое надёжно никто не писал). Этот синк делает
    их надёжными из dedicated stress-файлов.
    """
    cur = conn.cursor()
    # Гейтим по наличию bodyBattery в raw_data (а не stress_level): так дата
    # переобработается, если stress_level уже есть, но BB ещё нет (бэкфилл BB на
    # уже обработанные даты). jsonb_exists вместо оператора ? — psycopg2-safe.
    cur.execute(
        "SELECT date::text FROM activity_log WHERE user_id=%s AND date >= %s "
        "AND jsonb_exists(raw_data, 'bodyBatteryHighestValue')",
        (user_id, since),
    )
    existing = {row[0] for row in cur.fetchall()}

    if not GARMIN_STRESS.exists():
        return {"status": "no_source", "inserted": 0, "updated": 0}

    data: dict[str, dict] = {}
    for f in sorted(GARMIN_STRESS.glob("*.json")):
        if f.name[:4] not in {"2024", "2025", "2026", "2027", "2028"}:
            continue
        try:
            raw = json.loads(f.read_text())
        except Exception:
            continue
        if not isinstance(raw, dict):
            continue
        cal_date = raw.get("calendarDate", "")
        if not cal_date or cal_date < since:
            continue
        avg_stress = raw.get("avgStressLevel")
        # Garmin: -1 = нет данных, -2 = слишком активен. Берём только валидное.
        stress_val = int(avg_stress) if isinstance(avg_stress, (int, float)) and avg_stress > 0 else None
        # Формат массива в stress-файле: [timestamp, bodyBatteryStatus("MEASURED"),
        # bodyBatteryLevel, ...] — уровень на индексе 2 (descriptors подтверждают).
        bb_arr = raw.get("bodyBatteryValuesArray") or []
        bb_vals = [pt[2] for pt in bb_arr if isinstance(pt, list) and len(pt) >= 3 and isinstance(pt[2], (int, float))]
        bb_high = max(bb_vals) if bb_vals else None
        bb_low = min(bb_vals) if bb_vals else None
        if stress_val is None and bb_high is None:
            continue
        data[cal_date] = {"stress": stress_val, "bb_high": bb_high, "bb_low": bb_low}

    new_dates = {d: v for d, v in data.items() if d not in existing}

    if dry_run:
        print(f"  [dry-run] stress: добавить/обновить {len(new_dates)} дней")
        return {"status": "dry", "inserted": len(new_dates), "updated": 0}

    for cal_date, v in sorted(new_dates.items()):
        raw_upd = json.dumps(
            {
                k: val
                for k, val in (("bodyBatteryHighestValue", v["bb_high"]), ("bodyBatteryLowestValue", v["bb_low"]))
                if val is not None
            }
        )
        cur.execute(
            """INSERT INTO activity_log (user_id, date, stress_level, raw_data, source)
               VALUES (%s, %s, %s, %s::jsonb, %s)
               ON CONFLICT (user_id, date) DO UPDATE
                 SET stress_level = COALESCE(EXCLUDED.stress_level, activity_log.stress_level),
                     raw_data = COALESCE(activity_log.raw_data, '{}'::jsonb) || EXCLUDED.raw_data""",
            (user_id, cal_date, v["stress"], raw_upd, "garmin_stress"),
        )

    conn.commit()
    cur.close()
    return {"status": "ok", "inserted": len(new_dates), "updated": 0}


# ── main ────────────────────────────────────────────────────────────────────


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--user-id", type=int, default=DEFAULT_USER_ID)
    p.add_argument("--since", default=DEFAULT_SINCE, help="YYYY-MM-DD (default 2026-01-01)")
    p.add_argument("--only", choices=["workouts", "sleep", "hrv", "stress"], help="Только один тип")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("❌ DATABASE_URL не задан — этот скрипт должен запускаться внутри контейнера", file=sys.stderr)
        return 2

    try:
        conn = psycopg2.connect(db_url)
    except Exception as e:
        print(f"❌ Не удалось подключиться к Postgres: {e}", file=sys.stderr)
        return 2

    print(
        f"🔄 server_backfill_postgres: user_id={args.user_id} since={args.since}"
        + (" [DRY RUN]" if args.dry_run else "")
    )

    summary: dict[str, dict] = {}
    try:
        if not args.only or args.only == "workouts":
            print("→ workouts")
            summary["workouts"] = sync_workouts(conn, args.user_id, args.since, args.dry_run)
        if not args.only or args.only == "sleep":
            print("→ sleep")
            summary["sleep"] = sync_sleep(conn, args.user_id, args.since, args.dry_run)
        if not args.only or args.only == "hrv":
            print("→ hrv")
            summary["hrv"] = sync_hrv(conn, args.user_id, args.since, args.dry_run)
        if not args.only or args.only == "stress":
            print("→ stress")
            summary["stress"] = sync_stress(conn, args.user_id, args.since, args.dry_run)
    finally:
        conn.close()

    print("\n📊 Итог:")
    for kind, info in summary.items():
        ins = info.get("inserted", 0)
        upd = info.get("updated", 0)
        print(f"  {kind:10s} вставлено: {ins:3d}  обновлено: {upd:3d}  ({info.get('status')})")

    # Marker для /sync status — handlers/sync_cmd.py показывает mtime этого
    # файла как «когда последний раз PG-бэкфилл крутился». Не пишем при dry-run.
    if not args.dry_run:
        marker = BASE / "data" / "cache" / "pg_sync_last_run.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps(
                {
                    "ran_at": datetime.now(timezone.utc).isoformat(),
                    "user_id": args.user_id,
                    "since": args.since,
                    "summary": summary,
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
