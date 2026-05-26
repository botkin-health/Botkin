#!/usr/bin/env python3
"""Инкрементный batch-push Garmin daily-summary + HRV → activity_log на сервере.

Заменяет старый push_garmin_to_db.sh (per-day SSH × 131 = 225 сек).
Новая логика: один batch SQL за один SSH → ~2-5 сек.

Архитектура «hot window + state delta»:
  - HOT (последние 7 дней) — всегда перепушиваем (данные корректируются задним числом:
    HAE присылает сон поздно ночью, Garmin пересчитывает калории через сутки, etc.)
  - COLD (старше 7 дней) — только если file.mtime > last_sync_unix (state-based delta)

State: data/cache/.garmin_push_state.json — атомарно обновляется на успешном выполнении.
Если файл удалить — следующий запуск перепушит всё.

Использование:
  python3 scripts/push_garmin_to_db.py           # инкрементно
  python3 scripts/push_garmin_to_db.py --full    # игнорировать state, пушить всё
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
SUMMARY_DIR = BASE / "data/garmin/daily-summary"
HRV_DIR = BASE / "data/garmin/hrv"
STATE_FILE = BASE / "data/cache/.garmin_push_state.json"
USER_ID = 895655
HOT_WINDOW_DAYS = 7
MIN_TOTAL_KCAL = 1500  # неполные дни (час на зарядке, ранний sync) — пропускаем

SSH_HOST = "root@116.203.213.137"
SSH_OPTS = ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10"]

# Garth-токены для бот-контейнера
GARTH_LOCAL = BASE / "data/cache/garth_tokens"
GARTH_REMOTE = f"/opt/healthvault/data/garth/{USER_ID}"


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_state(d: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(d, indent=2, ensure_ascii=False))


def parse_day(json_file: Path) -> dict | None:
    """Распарсить daily-summary + HRV для одной даты. None если день неполный."""
    try:
        d = json.loads(json_file.read_text())
    except Exception:
        return None
    s = d.get("stats") or {}
    date_str = json_file.stem

    total = s.get("totalKilocalories") or 0
    if total < MIN_TOTAL_KCAL:
        return None  # неполный день

    hrv = None
    hrv_path = HRV_DIR / f"{date_str}.json"
    if hrv_path.exists():
        try:
            v = json.loads(hrv_path.read_text()).get("hrvSummary", {}).get("lastNightAvg")
            if v is not None:
                hrv = int(v)
        except Exception:
            pass

    sleep_sec = s.get("sleepingSeconds") or s.get("measurableAsleepDuration")
    sleep_h = round(sleep_sec / 3600.0, 2) if sleep_sec else None

    return {
        "date": date_str,
        "active": int(s["activeKilocalories"]) if s.get("activeKilocalories") is not None else None,
        "bmr": int(s["bmrKilocalories"]) if s.get("bmrKilocalories") is not None else None,
        "total": int(total),
        "steps": s.get("totalSteps"),
        "dist": round((s.get("totalDistanceMeters") or 0) / 1000.0, 3) if s.get("totalDistanceMeters") else None,
        "hr": s.get("restingHeartRate"),
        "stress": s.get("averageStressLevel"),
        "hrv": hrv,
        "sleep_h": sleep_h,
    }


def sql_fmt(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, str):
        # Дата YYYY-MM-DD — валидно, не нужно экранировать
        return f"'{v}'"
    return str(v)


def build_batch_sql(rows: list[dict]) -> str:
    """Один многострочный INSERT ... ON CONFLICT в транзакции."""
    if not rows:
        return ""

    values_lines = []
    for r in rows:
        values_lines.append(
            f"  ({USER_ID}, {sql_fmt(r['date'])}, "
            f"{sql_fmt(r['active'])}, {sql_fmt(r['bmr'])}, {sql_fmt(r['total'])}, "
            f"{sql_fmt(r['steps'])}, {sql_fmt(r['dist'])}, "
            f"{sql_fmt(r['hr'])}, {sql_fmt(r['stress'])}, {sql_fmt(r['hrv'])}, "
            f"{sql_fmt(r['sleep_h'])}, 'garmin_json')"
        )

    values_str = ",\n".join(values_lines)
    return f"""BEGIN;
INSERT INTO activity_log (
  user_id, date, active_calories, bmr_calories, total_calories,
  steps, distance_km, heart_rate_avg, stress_level, hrv,
  sleep_hours, source
) VALUES
{values_str}
ON CONFLICT (user_id, date) DO UPDATE SET
  active_calories  = COALESCE(EXCLUDED.active_calories,  activity_log.active_calories),
  bmr_calories     = COALESCE(EXCLUDED.bmr_calories,     activity_log.bmr_calories),
  total_calories   = COALESCE(EXCLUDED.total_calories,   activity_log.total_calories),
  steps            = COALESCE(EXCLUDED.steps,            activity_log.steps),
  distance_km      = COALESCE(EXCLUDED.distance_km,      activity_log.distance_km),
  heart_rate_avg   = COALESCE(EXCLUDED.heart_rate_avg,   activity_log.heart_rate_avg),
  stress_level     = COALESCE(EXCLUDED.stress_level,     activity_log.stress_level),
  hrv              = COALESCE(EXCLUDED.hrv,              activity_log.hrv),
  sleep_hours      = COALESCE(EXCLUDED.sleep_hours,      activity_log.sleep_hours),
  source           = 'garmin_json'
WHERE activity_log.source != 'manual';
COMMIT;
"""


def run_ssh(cmd: list[str]) -> None:
    """Wrapper для запуска ssh/scp-команды (key auth) с проверкой возврата."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(f"❌ FAILED: {' '.join(cmd[:4])}...\nstderr: {result.stderr}\n")
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)


def push_garth_tokens() -> None:
    """Копирует garth-токены на сервер. Делается всегда — токены живут ~28 дней."""
    if not (GARTH_LOCAL / "oauth1_token.json").exists() or not (GARTH_LOCAL / "oauth2_token.json").exists():
        print("⚠️  garth-токены не найдены — пропущено")
        return
    run_ssh(["ssh", *SSH_OPTS, SSH_HOST, f"mkdir -p {GARTH_REMOTE}"])
    run_ssh(
        [
            "scp",
            *SSH_OPTS,
            str(GARTH_LOCAL / "oauth1_token.json"),
            str(GARTH_LOCAL / "oauth2_token.json"),
            f"{SSH_HOST}:{GARTH_REMOTE}/",
        ]
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="Игнорировать state и пушить ВСЁ")
    ap.add_argument("--dry-run", action="store_true", help="Только показать что бы пушилось")
    args = ap.parse_args()

    if not SUMMARY_DIR.exists():
        print(f"⚠️  {SUMMARY_DIR} не найдена")
        sys.exit(1)

    state = load_state()
    last_push_unix = 0 if args.full else state.get("last_push_unix", 0)
    today = date.today()
    hot_cutoff = today - timedelta(days=HOT_WINDOW_DAYS)

    rows_to_push: list[dict] = []
    files_hot = 0
    files_cold_modified = 0

    for f in sorted(SUMMARY_DIR.glob("*.json")):
        try:
            file_date = date.fromisoformat(f.stem)
        except ValueError:
            continue

        is_hot = file_date >= hot_cutoff
        is_modified = f.stat().st_mtime > last_push_unix

        if not (is_hot or is_modified):
            continue

        row = parse_day(f)
        if not row:
            continue

        rows_to_push.append(row)
        if is_hot:
            files_hot += 1
        else:
            files_cold_modified += 1

    if not rows_to_push:
        print("⏭  Garmin → DB: всё актуально (0 файлов для пуша)")
        return

    if args.dry_run:
        print(f"DRY-RUN: пушилось бы {len(rows_to_push)} дней (hot={files_hot}, cold-modified={files_cold_modified})")
        for r in rows_to_push:
            print(f"  {r['date']}: kcal={r['total']} steps={r['steps']} sleep={r['sleep_h']}ч")
        return

    sql = build_batch_sql(rows_to_push)
    sql_path = Path("/tmp/garmin_batch.sql")
    sql_path.write_text(sql)

    print(f"📤 Garmin → DB: {len(rows_to_push)} дней одним batch (hot={files_hot}, delta={files_cold_modified})")

    # SCP файла на сервер, копия в контейнер postgres, выполнение, очистка
    run_ssh(["scp", *SSH_OPTS, str(sql_path), f"{SSH_HOST}:/tmp/garmin_batch.sql"])
    run_ssh(
        [
            "ssh",
            *SSH_OPTS,
            SSH_HOST,
            "docker cp /tmp/garmin_batch.sql healthvault_postgres:/tmp/garmin_batch.sql && "
            "docker exec healthvault_postgres psql -U healthvault -d healthvault -q -f /tmp/garmin_batch.sql > /dev/null && "
            "rm /tmp/garmin_batch.sql && "
            "docker exec healthvault_postgres rm /tmp/garmin_batch.sql",
        ]
    )

    # State обновляется ПОСЛЕ успешного SSH — на ошибке state остаётся прежним
    # (следующий запуск повторит)
    state["last_push_unix"] = int(datetime.now().timestamp())
    state["last_push_at"] = datetime.now().isoformat()
    state["last_push_count"] = len(rows_to_push)
    save_state(state)

    # Garth-токены — отдельная операция, не блокирует основной flow
    try:
        push_garth_tokens()
        print("🔑 Garth-токены обновлены")
    except Exception as e:
        print(f"⚠️  Garth-токены не обновлены: {e}")

    print(f"✅ Garmin → DB: {len(rows_to_push)} дней обновлено за один batch")
    sql_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
