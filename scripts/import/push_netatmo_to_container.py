#!/usr/bin/env python3
"""
Формирует env_data_895655.json из локального netatmo_history.json
и копирует его в Docker-контейнер healthvault_bot на сервере.

Формат выходного файла (читается dashboard_generator.py):
{
  "co2":      {"2026-04-22": 615, ...},
  "temp_home": {"2026-04-22": 21.1, ...},
  "humidity":  {"2026-04-22": 31, ...}
}

Порядок полей в netatmo_history.json: [Temperature, CO2, Humidity, Noise]
(соответствует "type": "Temperature,CO2,Humidity,Noise" в getmeasure API)

Запускается из sync_all_data.sh после scripts/import/netatmo.py.
"""

import json
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
NETATMO_JSON = BASE / "data/environment/netatmo_history.json"
USER_ID = 895655
SERVER = "root@116.203.213.137"
SERVER_PASS = "SERVER_PASSWORD_REDACTED"
CONTAINER = "healthvault_bot"
# dashboard_generator.py читает env_data из /app/telegram-bot/env_data_{user_id}.json
# (Path(__file__).parent), поэтому копируем именно туда. Старый путь /app/env_data_*.json
# оставлен как fallback для обратной совместимости.
CONTAINER_PATH = f"/app/telegram-bot/env_data_{USER_ID}.json"
CONTAINER_PATH_LEGACY = f"/app/env_data_{USER_ID}.json"


def build_env_data(netatmo_path: Path) -> dict:
    """Convert netatmo_history.json → env_data dict keyed by date."""
    raw = json.loads(netatmo_path.read_text())

    co2: dict[str, int] = {}
    temp_home: dict[str, float] = {}
    humidity: dict[str, int] = {}

    # netatmo_history has one key per station (e.g. "Большевик")
    for station_data in raw.values():
        if not isinstance(station_data, dict):
            continue
        for ts_str, values in station_data.items():
            try:
                ts = int(ts_str)
                date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
                # values: [Temperature, CO2, Humidity, Noise]
                if isinstance(values, (list, tuple)) and len(values) >= 3:
                    t, c, h = values[0], values[1], values[2]
                    if t is not None:
                        temp_home[date_str] = round(float(t), 1)
                    if c is not None:
                        co2[date_str] = int(c)
                    if h is not None:
                        humidity[date_str] = int(h)
            except (ValueError, TypeError):
                continue

    return {"co2": co2, "temp_home": temp_home, "humidity": humidity}


def push_to_container(data: dict) -> bool:
    """Write JSON to temp file, scp to server, docker cp into container."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
        tmp_path = f.name

    try:
        server_tmp = f"/tmp/env_data_{USER_ID}.json"
        env = {**os.environ, "SSHPASS": SERVER_PASS}

        # 1. SCP to server /tmp/
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
            print(f"   ❌ SCP ошибка: {scp.stderr[:200]}")
            return False

        # 2. docker cp from server /tmp/ → container /app/
        cp = subprocess.run(
            [
                "/opt/homebrew/bin/sshpass",
                "-e",
                "ssh",
                "-o",
                "StrictHostKeyChecking=no",
                SERVER,
                f"docker cp {server_tmp} {CONTAINER}:{CONTAINER_PATH} && "
                f"docker cp {server_tmp} {CONTAINER}:{CONTAINER_PATH_LEGACY} && "
                f"rm -f {server_tmp}",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        if cp.returncode != 0:
            print(f"   ❌ docker cp ошибка: {cp.stderr[:200]}")
            return False

        return True
    finally:
        os.unlink(tmp_path)


def main():
    if not NETATMO_JSON.exists():
        print("   ⚠️  Netatmo: файл не найден, пропускаем")
        return

    data = build_env_data(NETATMO_JSON)
    n_co2 = len(data["co2"])
    n_temp = len(data["temp_home"])

    if n_co2 == 0:
        print("   ⚠️  Netatmo: нет данных CO2 в файле")
        return

    last_date = max(data["co2"].keys()) if data["co2"] else "—"
    ok = push_to_container(data)

    if ok:
        print(f"   ✅ Netatmo → контейнер: {n_co2} дней CO2, {n_temp} дней темп, последний {last_date}")
    else:
        print("   ❌ Netatmo: не удалось обновить контейнер")


if __name__ == "__main__":
    main()
