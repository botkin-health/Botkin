#!/usr/bin/env python3
"""
Миграция весов из data/weights/*.json в PostgreSQL.
Использует database.crud.create_weight (та же схема, что и бот).
Запуск из корня проекта: python scripts/migrate_weights_to_db.py
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime

# Корень проекта
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Загрузка .env для DATABASE_URL
from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from database import SessionLocal
from database.crud import create_weight
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

# Кого мигрируем (можно вынести в env)
USER_ID = int(os.getenv("HEALTHVAULT_USER_ID", "895655"))
WEIGHTS_DIR = project_root / "data" / "weights"

SKIP_FILES = {"body_measurements.json", "zepp_reminders.json"}


def parse_measured_at(date_val, time_val=None):
    """Парсит дату/время в datetime (naive или с tz — БД примет)."""
    if isinstance(date_val, datetime):
        return date_val
    s = str(date_val).strip()
    if time_val:
        s = f"{date_val} {time_val}"
    # Упрощаем таймзону для strptime
    s = s.replace(" +0300", "").replace("+0300", "").replace(" +03:00", "").strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(s[:19].replace("T", " "), fmt)
        except (ValueError, TypeError):
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")[:19])
    except (ValueError, TypeError):
        return datetime.strptime(s[:10], "%Y-%m-%d")


def record_from_date_file(obj):
    """Один объект из файла вида 2026-01-29.json."""
    weight = obj.get("weight")
    if weight is None:
        return None
    date_val = obj.get("date")
    if not date_val:
        return None
    measured_at = parse_measured_at(date_val)
    return {
        "measured_at": measured_at,
        "weight": float(weight),
        "body_fat": obj.get("body_fat"),
        "muscle_mass": obj.get("muscle") or obj.get("muscle_mass"),
        "water": obj.get("water"),
        "bmi": obj.get("bmi"),
        "visceral_fat": obj.get("visceral_fat"),
        "bone_mass": obj.get("bone_mass"),
        "source": obj.get("source") or "json_import",
    }


def record_from_apple_health(entry):
    """Одна запись из apple_health_weights.json."""
    weight = entry.get("weight_kg")
    if weight is None:
        return None
    time_str = entry.get("time") or entry.get("date")
    if not time_str:
        return None
    measured_at = parse_measured_at(time_str)
    body_fat = entry.get("body_fat_percent")
    lean = entry.get("lean_body_mass_kg")
    return {
        "measured_at": measured_at,
        "weight": float(weight),
        "body_fat": body_fat,
        "muscle_mass": lean,  # упрощённо
        "water": None,
        "bmi": None,
        "visceral_fat": None,
        "bone_mass": None,
        "source": entry.get("source") or "apple_health",
    }


def insert_record(db, user_id: int, r: dict) -> str:
    """Вставка одной записи. Возвращает 'ok', 'duplicate' или 'error'."""
    try:
        create_weight(
            db,
            user_id=user_id,
            measured_at=r["measured_at"],
            weight=r["weight"],
            body_fat=r.get("body_fat"),
            muscle_mass=r.get("muscle_mass"),
            water=r.get("water"),
            bmi=r.get("bmi"),
            visceral_fat=int(r["visceral_fat"]) if r.get("visceral_fat") is not None else None,
            bone_mass=r.get("bone_mass"),
            source=r.get("source") or "json_import",
        )
        return "ok"
    except IntegrityError:
        db.rollback()
        return "duplicate"
    except Exception as e:
        db.rollback()
        return "error"


def main():
    if not WEIGHTS_DIR.is_dir():
        print(f"❌ Папка не найдена: {WEIGHTS_DIR}")
        sys.exit(1)

    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))  # проверка подключения
    except Exception as e:
        print(f"❌ Не удаётся подключиться к БД: {e}")
        print("   Запустите PostgreSQL или проверьте DATABASE_URL в .env")
        sys.exit(1)
    total_migrated = 0
    total_skipped = 0
    errors = 0

    # 1) apple_health_weights.json
    ah_file = WEIGHTS_DIR / "apple_health_weights.json"
    if ah_file.exists():
        try:
            data = json.loads(ah_file.read_text(encoding="utf-8"))
            entries = data.get("entries") or []
            m, s, err = 0, 0, 0
            for entry in entries:
                r = record_from_apple_health(entry)
                if not r:
                    continue
                res = insert_record(db, USER_ID, r)
                if res == "ok":
                    m += 1
                elif res == "duplicate":
                    s += 1
                else:
                    err += 1
            total_migrated += m
            total_skipped += s
            errors += err
            if entries:
                print(f"✅ apple_health_weights.json: записей {len(entries)}, добавлено {m}, пропущено {s}")
        except Exception as e:
            print(f"❌ apple_health_weights.json: {e}")
            errors += 1

    # 2) Остальные JSON (по одному файлу — массив или один объект)
    for json_file in sorted(WEIGHTS_DIR.glob("*.json")):
        if json_file.name in SKIP_FILES or json_file.name == "apple_health_weights.json":
            continue
        try:
            raw = json.loads(json_file.read_text(encoding="utf-8"))
            records = raw if isinstance(raw, list) else [raw]
            m, s, err = 0, 0, 0
            for obj in records:
                r = record_from_date_file(obj)
                if not r:
                    continue
                res = insert_record(db, USER_ID, r)
                if res == "ok":
                    m += 1
                elif res == "duplicate":
                    s += 1
                else:
                    err += 1
            total_migrated += m
            total_skipped += s
            errors += err
            if records:
                print(f"✅ {json_file.name}: записей {len(records)}, добавлено {m}, пропущено {s}")
        except Exception as e:
            print(f"❌ {json_file.name}: {e}")
            errors += 1

    db.close()
    print(f"\nИтого: добавлено в БД {total_migrated}, дубликатов пропущено {total_skipped}, ошибок {errors}")


if __name__ == "__main__":
    main()
