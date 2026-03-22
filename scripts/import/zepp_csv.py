#!/usr/bin/env python3
"""
Импорт данных с умных весов (Zepp Life / Xiaomi) из CSV в PostgreSQL.

Что делает:
  - Читает data/zepp_export_latest.csv (генерируется SmartScaleConnect)
  - Для каждой даты находит zepp_life записи в БД с NULL body_fat
  - Обновляет их данными состава тела (жир, мышцы, висцеральный жир и т.д.)
  - Все UPDATE выполняются за один SSH-вызов (батч)

Запускается автоматически из sync_all_data.sh после SmartScaleConnect.
"""

import csv
import os
import subprocess
from pathlib import Path

BASE = Path(__file__).parent.parent
CSV_PATH = BASE / "data" / "zepp_export_latest.csv"
USER_ID = 895655
MIN_DATE = "2024-01-01"  # обрабатываем данные с 2024+


def main():
    if not CSV_PATH.exists():
        print("   ⚠️  Zepp CSV не найден, пропускаем")
        return

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    sql_statements = []
    for row in rows:
        date_str = row.get("Date", "")[:10]
        if date_str < MIN_DATE:
            continue

        try:
            body_fat = float(row["BodyFat"]) if row.get("BodyFat", "").strip() else None
            if body_fat is None:
                continue

            visceral_fat = int(float(row["VisceralFat"])) if row.get("VisceralFat", "").strip() else None
            muscle_mass = float(row["MuscleMass"]) if row.get("MuscleMass", "").strip() else None
            water = float(row["BodyWater"]) if row.get("BodyWater", "").strip() else None
            bmi = round(float(row["BMI"]), 1) if row.get("BMI", "").strip() else None
            bone_mass = float(row["BoneMass"]) if row.get("BoneMass", "").strip() else None
        except (ValueError, TypeError):
            continue

        set_parts = [f"body_fat={body_fat}"]
        if visceral_fat is not None:
            set_parts.append(f"visceral_fat={visceral_fat}")
        if muscle_mass is not None:
            set_parts.append(f"muscle_mass={muscle_mass}")
        if water is not None:
            set_parts.append(f"water={water}")
        if bmi is not None:
            set_parts.append(f"bmi={bmi}")
        if bone_mass is not None:
            set_parts.append(f"bone_mass={bone_mass}")

        sql = (
            f"UPDATE weights SET {', '.join(set_parts)} "
            f"WHERE user_id={USER_ID} AND source='zepp_life' AND body_fat IS NULL "
            f"AND (measured_at AT TIME ZONE 'UTC')::date='{date_str}';"
        )
        sql_statements.append(sql)

    if not sql_statements:
        print("   ✅ Zepp: нет новых данных для импорта")
        return

    # Всё одним SSH-вызовом через stdin — никаких проблем с экранированием
    batch_sql = "\n".join(sql_statements)
    env = {**os.environ, "SSHPASS": "W749a#j%37z8_138UBYA"}

    result = subprocess.run(
        [
            "sshpass", "-e", "ssh", "-o", "StrictHostKeyChecking=no",
            "root@116.203.213.137",
            "docker exec -i healthvault_postgres psql -U healthvault -d healthvault",
        ],
        input=batch_sql,
        capture_output=True,
        text=True,
        env=env,
    )

    if result.returncode != 0:
        print(f"   ⚠️  Zepp: ошибка SQL: {result.stderr[:300]}")
        return

    updated = sum(1 for line in result.stdout.splitlines() if line.strip().startswith("UPDATE") and line.strip() != "UPDATE 0")
    skipped = result.stdout.count("UPDATE 0")

    if updated > 0:
        print(f"   ✅ Zepp: обновлено {updated} дней с новыми данными состава тела")
    else:
        print(f"   ✅ Zepp: все данные актуальны (нет новых zepp_life записей без body_fat)")


if __name__ == "__main__":
    main()
