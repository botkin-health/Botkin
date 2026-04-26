#!/usr/bin/env python3
"""
Копирует data/garmin/workouts_log.json в Docker-контейнер healthvault_bot,
чтобы dashboard_generator.py мог построить блок «Спорт и тренировки».

Файл попадает в /app/telegram-bot/workouts_log_895655.json (рядом с biomarkers и env_data).
Берём только последние 90 дней — больше дашборду не нужно.

Запускается из sync_all_data.sh после parse_workouts.py.
"""

import json
import os
import subprocess
import tempfile
from datetime import date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
SOURCE = BASE / "data/garmin/workouts_log.json"
USER_ID = 895655
SERVER = "root@116.203.213.137"
SERVER_PASS = "SERVER_PASSWORD_REDACTED"
CONTAINER = "healthvault_bot"
CONTAINER_PATH = f"/app/telegram-bot/workouts_log_{USER_ID}.json"
KEEP_DAYS = 90


def main():
    if not SOURCE.exists():
        print("   ⚠️  Workouts: файл не найден, пропускаем")
        return

    full = json.loads(SOURCE.read_text())
    cutoff = (date.today() - timedelta(days=KEEP_DAYS)).isoformat()
    workouts = [w for w in full.get("workouts", []) if w.get("date", "") >= cutoff]

    payload = {
        "generated_at": full.get("generated_at"),
        "workouts": workouts,
        "kept_days": KEEP_DAYS,
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
        tmp_path = f.name

    try:
        server_tmp = f"/tmp/workouts_log_{USER_ID}.json"
        env = {**os.environ, "SSHPASS": SERVER_PASS}

        scp = subprocess.run(
            [
                "/opt/homebrew/bin/sshpass",
                "-e",
                "scp",
                "-o",
                "StrictHostKeyChecking=no",
                tmp_path,
                f"{SERVER}:{server_tmp}",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        if scp.returncode != 0:
            print(f"   ❌ SCP: {scp.stderr[:200]}")
            return

        cp = subprocess.run(
            [
                "/opt/homebrew/bin/sshpass",
                "-e",
                "ssh",
                "-o",
                "StrictHostKeyChecking=no",
                SERVER,
                f"docker cp {server_tmp} {CONTAINER}:{CONTAINER_PATH} && rm -f {server_tmp}",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        if cp.returncode != 0:
            print(f"   ❌ docker cp: {cp.stderr[:200]}")
            return

        last = max((w["date"] for w in workouts), default="—")
        print(f"   ✅ Workouts → контейнер: {len(workouts)} тренировок за {KEEP_DAYS} дней, последняя {last}")
    finally:
        os.unlink(tmp_path)


if __name__ == "__main__":
    main()
