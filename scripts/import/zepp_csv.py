#!/usr/bin/env python3
"""
Импорт данных с умных весов (Zepp Life / Xiaomi) из CSV в PostgreSQL.

Что делает:
  - Читает data/zepp_export_latest.csv (генерируется zepp_api.py)
  - Для каждой записи:
      * INSERT ... WHERE NOT EXISTS — вставляет вес + состав, если дня ещё нет
      * UPDATE ... WHERE body_fat IS NULL — дописывает состав тела к уже существующей строке
  - Все операции выполняются за один SSH-вызов (батч)

Запускается автоматически из sync_all_data.sh после zepp_api.py.
"""

import csv
import subprocess
from pathlib import Path

BASE = Path(__file__).parent.parent.parent
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
        date_raw = row.get("Date", "")
        date_str = date_raw[:10]
        time_str = date_raw[11:19] if len(date_raw) > 10 else "07:00:00"
        measured_at = f"{date_str} {time_str}"

        if date_str < MIN_DATE:
            continue

        try:
            weight = float(row["Weight"]) if row.get("Weight", "").strip() else None
            if weight is None:
                continue

            body_fat = float(row["BodyFat"]) if row.get("BodyFat", "").strip() else None
            visceral_fat = int(float(row["VisceralFat"])) if row.get("VisceralFat", "").strip() else None
            muscle_mass = float(row["MuscleMass"]) if row.get("MuscleMass", "").strip() else None
            water = float(row["BodyWater"]) if row.get("BodyWater", "").strip() else None
            bmi = round(float(row["BMI"]), 1) if row.get("BMI", "").strip() else None
            bone_mass = float(row["BoneMass"]) if row.get("BoneMass", "").strip() else None
        except (ValueError, TypeError):
            continue

        # 1. INSERT если нет записи за эту дату от zepp_life
        cols = ["user_id", "measured_at", "weight", "source"]
        vals = [str(USER_ID), f"'{measured_at}'", str(weight), "'zepp_life'"]
        if body_fat is not None:
            cols.append("body_fat")
            vals.append(str(body_fat))
        if visceral_fat is not None:
            cols.append("visceral_fat")
            vals.append(str(visceral_fat))
        if muscle_mass is not None:
            cols.append("muscle_mass")
            vals.append(str(muscle_mass))
        if water is not None:
            cols.append("water")
            vals.append(str(water))
        if bmi is not None:
            cols.append("bmi")
            vals.append(str(bmi))
        if bone_mass is not None:
            cols.append("bone_mass")
            vals.append(str(bone_mass))

        insert_sql = (
            f"INSERT INTO weights ({', '.join(cols)}) "
            f"SELECT {', '.join(vals)} "
            f"WHERE NOT EXISTS ("
            f"  SELECT 1 FROM weights "
            f"  WHERE user_id={USER_ID} AND source='zepp_life' "
            f"  AND (measured_at AT TIME ZONE 'UTC')::date='{date_str}'"
            f");"
        )
        sql_statements.append(insert_sql)

        # 2. UPDATE если запись есть, но без состава тела
        if body_fat is not None:
            update_parts = [f"body_fat={body_fat}"]
            if visceral_fat is not None:
                update_parts.append(f"visceral_fat={visceral_fat}")
            if muscle_mass is not None:
                update_parts.append(f"muscle_mass={muscle_mass}")
            if water is not None:
                update_parts.append(f"water={water}")
            if bmi is not None:
                update_parts.append(f"bmi={bmi}")
            if bone_mass is not None:
                update_parts.append(f"bone_mass={bone_mass}")

            update_sql = (
                f"UPDATE weights SET {', '.join(update_parts)} "
                f"WHERE user_id={USER_ID} AND source='zepp_life' AND body_fat IS NULL "
                f"AND (measured_at AT TIME ZONE 'UTC')::date='{date_str}';"
            )
            sql_statements.append(update_sql)

    if not sql_statements:
        print("   ✅ Zepp: нет данных в CSV")
        return

    batch_sql = "\n".join(sql_statements)

    result = subprocess.run(
        [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "root@116.203.213.137",
            "docker exec -i healthvault_postgres psql -U healthvault -d healthvault",
        ],
        input=batch_sql,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"   ⚠️  Zepp: ошибка SQL: {result.stderr[:300]}")
        return

    inserted = sum(1 for line in result.stdout.splitlines() if line.strip() == "INSERT 0 1")
    updated = sum(
        1 for line in result.stdout.splitlines() if line.strip().startswith("UPDATE") and line.strip() != "UPDATE 0"
    )

    if inserted > 0 or updated > 0:
        parts = []
        if inserted:
            parts.append(f"вставлено {inserted} новых дней")
        if updated:
            parts.append(f"обновлено {updated} дней (состав тела)")
        print(f"   ✅ Zepp: {', '.join(parts)}")
    else:
        print("   ✅ Zepp: все данные актуальны")


if __name__ == "__main__":
    main()
