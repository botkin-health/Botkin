#!/usr/bin/env python3
"""
Бэкфилл исторических данных из локальных файлов в PostgreSQL на сервере.

Синхронизирует:
  1. Весы (Zepp CSV) → таблица weights
  2. Тренировки (Garmin JSON) → таблица workouts
  3. Сон (Garmin sleep JSON) → таблица activity_log (обновляет sleep_score / deep_h / rem_h)

Запуск:
    python3 scripts/backfill_to_postgres.py [--dry-run]
"""

import argparse
import csv
import json
import subprocess
import sys
import tempfile
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── пути ─────────────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent
ZEPP_CSV = BASE / "data" / "zepp_export_latest.csv"
GARMIN_ACTS = BASE / "data" / "garmin" / "activities"
GARMIN_SLEEP = BASE / "data" / "garmin" / "sleep"

USER_ID = 895655
SERVER = "root@116.203.213.137"
SSHPASS = "/opt/homebrew/bin/sshpass"
SSH_PASS = "SERVER_PASSWORD_REDACTED"
CONTAINER = "healthvault_postgres"
DB_USER = "healthvault"
DB_NAME = "healthvault"

START_DATE = "2026-01-01"  # только данные с начала 2026


def run_sql(sql: str, dry_run: bool = False) -> str:
    """Выполняет SQL на сервере через SSH + docker exec psql."""
    if dry_run:
        print("[DRY RUN] SQL:", sql[:120], "...")
        return ""
    result = subprocess.run(
        [
            SSHPASS,
            "-p",
            SSH_PASS,
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            SERVER,
            f"docker exec {CONTAINER} psql -U {DB_USER} -d {DB_NAME} -t -c {json.dumps(sql)}",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"psql error: {result.stderr[:300]}")
    return result.stdout.strip()


def run_sql_file(sql: str, dry_run: bool = False) -> str:
    """Выполняет большой SQL-файл через stdin (для множественных INSERT)."""
    if dry_run:
        lines = sql.count("\n")
        print(f"[DRY RUN] SQL file: {lines} строк")
        return ""
    # Пишем SQL во временный файл на сервере через stdin
    result = subprocess.run(
        [
            SSHPASS,
            "-p",
            SSH_PASS,
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            SERVER,
            f"docker exec -i {CONTAINER} psql -U {DB_USER} -d {DB_NAME}",
        ],
        input=sql,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"psql error: {result.stderr[:400]}")
    return result.stdout.strip()


# ── 1. Весы (Zepp CSV) ────────────────────────────────────────────────────────


def backfill_weights(dry_run: bool):
    print("\n=== 1. ВЕСА (Zepp CSV) ===")

    # Получаем уже существующие даты из БД
    existing_raw = run_sql(
        f"SELECT DATE(measured_at) FROM weights WHERE user_id={USER_ID} AND measured_at >= '{START_DATE}'",
        dry_run=False,  # всегда читаем реальное состояние
    )
    existing_dates = set(line.strip() for line in existing_raw.splitlines() if line.strip())
    print(f"Уже в БД: {len(existing_dates)} дат")

    rows_to_insert = []
    with open(ZEPP_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            dt_str = row["Date"][:10]  # YYYY-MM-DD
            if dt_str < START_DATE:
                continue
            # Zepp может дать несколько измерений в день — берём первое
            if dt_str in existing_dates:
                continue
            if not row.get("Weight"):
                continue

            weight = float(row["Weight"])
            body_fat = float(row["BodyFat"]) if row.get("BodyFat") else None
            muscle_mass = float(row["MuscleMass"]) if row.get("MuscleMass") else None
            water = float(row["BodyWater"]) if row.get("BodyWater") else None
            bone_mass = float(row["BoneMass"]) if row.get("BoneMass") else None
            bmi = float(row["BMI"]) if row.get("BMI") else None
            visceral = int(float(row["VisceralFat"])) if row.get("VisceralFat") else None

            # Время измерения из CSV или ставим 07:00 MSK (UTC+3)
            try:
                measured_at = datetime.strptime(row["Date"], "%Y-%m-%d %H:%M:%S")
                measured_at = measured_at.replace(tzinfo=timezone(timedelta(hours=3)))
            except Exception:
                measured_at = datetime.strptime(dt_str, "%Y-%m-%d").replace(hour=7, tzinfo=timezone(timedelta(hours=3)))

            rows_to_insert.append(
                (
                    dt_str,
                    measured_at.isoformat(),
                    weight,
                    body_fat,
                    muscle_mass,
                    water,
                    bone_mass,
                    bmi,
                    visceral,
                )
            )
            existing_dates.add(dt_str)  # чтобы не добавлять дважды один день

    print(f"Новых записей для вставки: {len(rows_to_insert)}")
    if not rows_to_insert:
        print("Ничего нового — пропускаем")
        return

    # Строим один большой INSERT
    vals = []
    for _, ts, w, bf, mm, wa, bm, bmi_v, visc in rows_to_insert:

        def sq(v):
            return "NULL" if v is None else str(v)

        vals.append(
            f"({USER_ID}, '{ts}', {w}, {sq(bf)}, {sq(mm)}, {sq(wa)}, {sq(bm)}, {sq(bmi_v)}, {sq(visc)}, 'zepp_life')"
        )

    sql = (
        "INSERT INTO weights (user_id, measured_at, weight, body_fat, muscle_mass, water, bone_mass, bmi, visceral_fat, source) VALUES\n"
        + ",\n".join(vals)
        + "\nON CONFLICT DO NOTHING;"
    )
    out = run_sql_file(sql, dry_run)
    if not dry_run:
        print(f"✅ Вставлено весов: {len(rows_to_insert)}")
        print(f"   Ответ psql: {out[:80]}")


# ── 2. Тренировки (Garmin activities JSON) ────────────────────────────────────

# Маппинг Garmin typeKey → наш тип
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


def backfill_workouts(dry_run: bool):
    print("\n=== 2. ТРЕНИРОВКИ (Garmin JSON) ===")

    # Существующие в БД
    existing_raw = run_sql(
        f"SELECT date::text FROM workouts WHERE user_id={USER_ID} AND date >= '{START_DATE}'",
        dry_run=False,
    )
    existing_dates = set(line.strip() for line in existing_raw.splitlines() if line.strip())
    print(f"Уже в БД: {len(existing_dates)} записей (по датам)")

    rows_to_insert = []
    files = sorted([f for f in GARMIN_ACTS.glob("*.json") if "detail" not in f.name])
    for f in files:
        dt_prefix = f.name[:10]  # YYYY-MM-DD
        if dt_prefix < START_DATE:
            continue
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue

        start_local = data.get("startTimeLocal", "")
        if not start_local or start_local[:10] < START_DATE:
            continue

        act_type_key = (data.get("activityType") or {}).get("typeKey", "other")
        workout_type = _TYPE_MAP.get(act_type_key, act_type_key)
        duration_sec = data.get("duration") or data.get("elapsedDuration") or 0
        duration_min = max(1, round(duration_sec / 60))
        distance_m = data.get("distance") or 0
        calories = int(data.get("calories") or 0)

        try:
            start_dt = datetime.strptime(start_local, "%Y-%m-%d %H:%M:%S")
            start_dt = start_dt.replace(tzinfo=timezone(timedelta(hours=3)))
            end_dt = start_dt + timedelta(minutes=duration_min)
        except Exception:
            continue

        work_date = start_local[:10]

        rows_to_insert.append(
            (
                work_date,
                workout_type,
                duration_min,
                start_dt.isoformat(),
                end_dt.isoformat(),
                calories,
                data.get("activityId", ""),
            )
        )

    print(f"Файлов активностей (2026+): {len(rows_to_insert)}")
    if not rows_to_insert:
        print("Нечего вставлять")
        return

    vals = []
    for work_date, wtype, dur_min, sdt, edt, cal, src_id in rows_to_insert:
        vals.append(
            f"({USER_ID}, '{work_date}', '{wtype}', {dur_min}, "
            f"'{sdt}', '{edt}', {cal if cal else 'NULL'}, 'garmin_{src_id}')"
        )

    sql = (
        "INSERT INTO workouts (user_id, date, workout_type, duration_minutes, start_time, end_time, calories_burned, source) VALUES\n"
        + ",\n".join(vals)
        + "\nON CONFLICT DO NOTHING;"
    )
    out = run_sql_file(sql, dry_run)
    if not dry_run:
        print(f"✅ Вставлено тренировок: {len(rows_to_insert)}")
        print(f"   Ответ psql: {out[:80]}")


# ── 3. Сон: sleep_score, deep, rem → activity_log ─────────────────────────────


def backfill_sleep(dry_run: bool):
    print("\n=== 3. СОН (Garmin sleep JSON) ===")

    # Уже заполненные строки в activity_log
    existing_raw = run_sql(
        f"SELECT date::text, sleep_hours FROM activity_log WHERE user_id={USER_ID} AND date >= '{START_DATE}' AND sleep_hours IS NOT NULL",
        dry_run=False,
    )
    existing_dates: dict[str, float] = {}
    for line in existing_raw.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 2 and parts[0]:
            try:
                existing_dates[parts[0]] = float(parts[1])
            except Exception:
                pass
    print(f"Уже есть sleep_hours в activity_log: {len(existing_dates)} дней")

    # Данные из Garmin JSON
    sleep_data: dict[str, dict] = {}  # date → {sleep_h, sleep_score, deep_h, rem_h}
    files = sorted(GARMIN_SLEEP.glob("2026*.json"))
    for f in files:
        try:
            raw = json.loads(f.read_text())
        except Exception:
            continue
        dto = (raw or {}).get("dailySleepDTO") or {}
        cal_date = dto.get("calendarDate", "")
        if not cal_date or cal_date < START_DATE:
            continue

        sleep_sec = dto.get("sleepTimeSeconds") or 0
        deep_sec = dto.get("deepSleepSeconds") or 0
        rem_sec = dto.get("remSleepSeconds") or 0
        scores = dto.get("sleepScores") or {}
        sleep_score = (scores.get("overall") or {}).get("value")

        if sleep_sec > 0:
            sleep_data[cal_date] = {
                "sleep_h": round(sleep_sec / 3600, 2),
                "deep_h": round(deep_sec / 3600, 2),
                "rem_h": round(rem_sec / 3600, 2),
                "sleep_score": int(sleep_score) if sleep_score else None,
            }

    print(f"Garmin sleep файлов с данными: {len(sleep_data)}")
    new_dates = {d: v for d, v in sleep_data.items() if d not in existing_dates}
    print(f"Новых дней сна для загрузки: {len(new_dates)}")

    if not new_dates:
        print("Нечего обновлять")
        return

    # UPSERT: обновляем sleep_hours в activity_log, вставляем если нет строки
    sqls = []
    for cal_date, sv in sorted(new_dates.items()):
        sh = sv["sleep_h"]
        dh = sv["deep_h"]
        rh = sv["rem_h"]
        sc = sv["sleep_score"]

        raw_upd = json.dumps({"sleep_score": sc, "deep_h": dh, "rem_h": rh})
        sqls.append(
            f"""INSERT INTO activity_log (user_id, date, sleep_hours, raw_data, source)
VALUES ({USER_ID}, '{cal_date}', {sh}, '{raw_upd}'::jsonb, 'garmin_sleep')
ON CONFLICT (user_id, date) DO UPDATE
  SET sleep_hours = EXCLUDED.sleep_hours,
      raw_data = activity_log.raw_data || EXCLUDED.raw_data;"""
        )

    full_sql = "\n".join(sqls)
    out = run_sql_file(full_sql, dry_run)
    if not dry_run:
        print(f"✅ Обновлено/вставлено дней сна: {len(new_dates)}")
        print(f"   Ответ psql (первые 150 символов): {out[:150]}")


# ── 4. Итоговый отчёт ─────────────────────────────────────────────────────────


def print_report():
    print("\n=== ИТОГОВОЕ СОСТОЯНИЕ БД ===")
    queries = [
        (
            "Веса (2026)",
            f"SELECT COUNT(*), MIN(DATE(measured_at))::text, MAX(DATE(measured_at))::text FROM weights WHERE user_id={USER_ID} AND measured_at >= '{START_DATE}'",
        ),
        (
            "Тренировки (2026)",
            f"SELECT COUNT(*), MIN(date)::text, MAX(date)::text FROM workouts WHERE user_id={USER_ID} AND date >= '{START_DATE}'",
        ),
        (
            "activity_log со сном (2026)",
            f"SELECT COUNT(*) FROM activity_log WHERE user_id={USER_ID} AND date >= '{START_DATE}' AND sleep_hours IS NOT NULL",
        ),
        (
            "activity_log с шагами (2026)",
            f"SELECT COUNT(*) FROM activity_log WHERE user_id={USER_ID} AND date >= '{START_DATE}' AND steps IS NOT NULL",
        ),
        ("Питание (2026)", f"SELECT COUNT(*) FROM nutrition_log WHERE user_id={USER_ID} AND date >= '{START_DATE}'"),
    ]
    for label, q in queries:
        out = run_sql(q)
        print(f"  {label}: {out.strip()}")


# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Не пишем в БД, только показываем что будет")
    parser.add_argument("--only", choices=["weights", "workouts", "sleep"], help="Синхронизировать только один тип")
    args = parser.parse_args()

    if args.dry_run:
        print("⚠️  DRY RUN MODE — БД не меняется\n")

    try:
        if not args.only or args.only == "weights":
            backfill_weights(args.dry_run)
        if not args.only or args.only == "workouts":
            backfill_workouts(args.dry_run)
        if not args.only or args.only == "sleep":
            backfill_sleep(args.dry_run)

        if not args.dry_run:
            print_report()
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
