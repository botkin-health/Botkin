#!/usr/bin/env python3
"""Синтетические данные для дев-стенда вместо копии прода (ADR-0013).

Дев-стенд не получает ни одной строки из прод-БД и ни одного файла из прод-каталога
data. Чтобы дашборд, агент и отчёты было на чём проверять, этот
скрипт создаёт выдуманных пользователей с правдоподобными данными: еда, вес,
активность и сон, БАДы, давление, два анализа крови.

Секреты (jwt_secret, health_token, share_token) генерируются заново, на деве.

Запуск на сервере, внутри дев-контейнера (BOTKIN_ENV=dev задан в compose):
    docker exec botkin_dev_bot python scripts/dev/seed_synthetic.py --users 3 --days 60
    docker exec botkin_dev_bot python scripts/dev/seed_synthetic.py --attach <свой дев telegram_id>
    docker exec botkin_dev_bot python scripts/dev/seed_synthetic.py --reset

--attach заливает синтетику в уже существующий дев-аккаунт разработчика (тот,
что создал онбординг в @botkin_dev_bot), чтобы смотреть дашборд под собой.
--reset удаляет всех синтетических пользователей и их данные.

Скрипт отказывается работать, если BOTKIN_ENV не dev и не local.
"""

from __future__ import annotations

import argparse
import random
import secrets
import sys
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import delete, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from core.env import botkin_env  # noqa: E402
from core.food.fiber_table import enrich_items_with_fiber  # noqa: E402
from database.models import (  # noqa: E402
    ActivityLog,
    BloodTest,
    NutritionLog,
    SupplementLog,
    User,
    UserSettings,
    Weight,
)

ALLOWED_ENVS = ("dev", "local")

# Синтетические telegram_id: заведомо вне диапазона реальных аккаунтов Telegram
# (сейчас они меньше 10^10). По этому диапазону --reset находит своих.
SYNTHETIC_ID_BASE = 900_000_000_000
SYNTHETIC_ID_MAX = SYNTHETIC_ID_BASE + 1_000_000

# (название, граммы, ккал, белки, жиры, углеводы)
_MENU = {
    "Завтрак": [
        ("Овсянка на молоке", 250, 260, 9, 7, 40),
        ("Омлет из двух яиц", 150, 230, 15, 18, 2),
        ("Творог 5%", 200, 240, 34, 10, 6),
        ("Кофе с молоком", 200, 60, 3, 3, 5),
    ],
    "Обед": [
        ("Борщ", 300, 150, 6, 6, 18),
        ("Куриная грудка на гриле", 150, 250, 45, 6, 0),
        ("Гречка отварная", 200, 220, 8, 2, 42),
        ("Салат из огурцов и помидоров", 200, 60, 2, 3, 7),
    ],
    "Ужин": [
        ("Лосось запечённый", 150, 300, 30, 20, 0),
        ("Рис отварной", 180, 210, 4, 1, 46),
        ("Тушёные овощи", 250, 120, 4, 5, 15),
        ("Кефир 1%", 250, 100, 8, 3, 10),
    ],
}
_MEAL_TIMES = {"Завтрак": time(8, 30), "Обед": time(13, 30), "Ужин": time(19, 30)}
_SUPPLEMENTS = [("Витамин D3", "2000 МЕ"), ("Омега-3", "1 г"), ("Магний", "400 мг")]


def ensure_allowed_env() -> str:
    env = botkin_env()
    if env not in ALLOWED_ENVS:
        raise SystemExit(f"seed_synthetic: BOTKIN_ENV={env!r}, разрешено только {ALLOWED_ENVS}. Прод не трогаем.")
    return env


def is_synthetic_id(telegram_id: int) -> bool:
    return SYNTHETIC_ID_BASE <= telegram_id < SYNTHETIC_ID_MAX


def _create_user(db: Session, telegram_id: int, n: int, rng: random.Random) -> User:
    sex = "female" if n % 2 == 0 else "male"
    user = User(
        telegram_id=telegram_id,
        username=f"synthetic_{n}",
        first_name=f"Синтетик {n}",
        last_name="Тестовый",
        cohort="external",
        sex=sex,
        birth_date=date(1975 + rng.randint(0, 25), rng.randint(1, 12), rng.randint(1, 28)),
        height_cm=rng.randint(158, 192),
        timezone="Europe/Moscow",
        jwt_secret=secrets.token_hex(32),
        health_token=f"hvt_{telegram_id}_{secrets.token_hex(16)}",
        share_token=str(uuid.uuid4()),
    )
    db.add(user)
    db.add(UserSettings(user_id=telegram_id, calorie_goal_pct=-10, activity_level="moderate"))
    db.flush()
    return user


def _seed_user_data(db: Session, telegram_id: int, days: int, rng: random.Random, today: date) -> dict:
    counts = {"nutrition_log": 0, "weights": 0, "activity_log": 0, "supplements_log": 0, "blood_pressure_logs": 0}
    weight = rng.uniform(65, 95)
    for offset in range(days, 0, -1):
        day = today - timedelta(days=offset)

        for meal_name, options in _MENU.items():
            picked = rng.sample(options, k=2)
            items = [
                {
                    "food": name,
                    "amount": f"{grams} г",
                    "weight_g": grams,
                    "calories": kcal,
                    "protein": p,
                    "fats": f,
                    "carbs": c,
                }
                for name, grams, kcal, p, f, c in picked
            ]
            enrich_items_with_fiber(items)
            totals = {
                key: round(sum(float(it.get(key) or 0) for it in items), 1)
                for key in ("calories", "protein", "fats", "carbs", "fiber")
            }
            db.add(
                NutritionLog(
                    user_id=telegram_id,
                    date=day,
                    meal_time=_MEAL_TIMES[meal_name],
                    meal_name=meal_name,
                    items=items,
                    totals=totals,
                )
            )
            counts["nutrition_log"] += 1

        weight += rng.uniform(-0.35, 0.25)
        db.add(
            Weight(
                user_id=telegram_id,
                measured_at=datetime.combine(day, time(7, 30), tzinfo=timezone.utc),
                weight=round(weight, 1),
                body_fat=round(rng.uniform(18, 30), 1),
                source="synthetic",
            )
        )
        counts["weights"] += 1

        db.add(
            ActivityLog(
                user_id=telegram_id,
                date=day,
                steps=rng.randint(3000, 16000),
                active_calories=round(rng.uniform(200, 800)),
                sleep_hours=round(rng.uniform(5.5, 8.5), 1),
                heart_rate_avg=rng.randint(58, 78),
                hrv=rng.randint(25, 70),
                source="synthetic",
            )
        )
        counts["activity_log"] += 1

        for name, dosage in _SUPPLEMENTS:
            if rng.random() < 0.85:
                db.add(
                    SupplementLog(user_id=telegram_id, date=day, time=time(9, 0), supplement_name=name, dosage=dosage)
                )
                counts["supplements_log"] += 1

        if offset % 3 == 0:
            # blood_pressure_logs пишется raw-SQL (CLAUDE.md: не через ORM).
            db.execute(
                text(
                    "INSERT INTO blood_pressure_logs (user_id, measured_at, systolic, diastolic, heart_rate, source) "
                    "VALUES (:u, :m, :s, :d, :hr, 'synthetic')"
                ),
                {
                    "u": telegram_id,
                    "m": datetime.combine(day, time(8, 0), tzinfo=timezone.utc),
                    "s": rng.randint(112, 138),
                    "d": rng.randint(70, 88),
                    "hr": rng.randint(58, 80),
                },
            )
            counts["blood_pressure_logs"] += 1

    for test_day in (today - timedelta(days=days), today - timedelta(days=max(days // 4, 1))):
        db.add(
            BloodTest(
                user_id=telegram_id,
                test_date=test_day,
                test_type="Биохимия",
                values={
                    "cholesterol": round(rng.uniform(4.0, 6.5), 2),
                    "LDL": round(rng.uniform(2.0, 4.2), 2),
                    "HDL": round(rng.uniform(1.0, 1.9), 2),
                    "triglycerides": round(rng.uniform(0.7, 2.2), 2),
                    "glucose": round(rng.uniform(4.3, 6.0), 2),
                    "HbA1c": round(rng.uniform(4.8, 6.0), 1),
                    "ferritin": round(rng.uniform(30, 250)),
                    "vitamin_d": round(rng.uniform(15, 70)),
                },
                status="current",
            )
        )
    counts["blood_tests"] = 2
    return counts


def seed(
    db: Session,
    *,
    users: int = 3,
    days: int = 60,
    attach: int | None = None,
    rng_seed: int = 42,
    today: date | None = None,
) -> dict:
    """Создать синтетику. Возвращает {telegram_id: {таблица: число строк}}."""
    ensure_allowed_env()
    rng = random.Random(rng_seed)
    today = today or date.today()
    report: dict = {}

    if attach is not None:
        if not db.get(User, attach):
            raise SystemExit(
                f"seed_synthetic: дев-пользователь {attach} не найден — сначала пройди онбординг в дев-боте"
            )
        report[attach] = _seed_user_data(db, attach, days, rng, today)
    else:
        existing = {
            uid
            for (uid,) in db.query(User.telegram_id).filter(
                User.telegram_id >= SYNTHETIC_ID_BASE, User.telegram_id < SYNTHETIC_ID_MAX
            )
        }
        n = 0
        while len(report) < users:
            n += 1
            tg_id = SYNTHETIC_ID_BASE + n
            if tg_id in existing:
                continue
            _create_user(db, tg_id, n, rng)
            report[tg_id] = _seed_user_data(db, tg_id, days, rng, today)

    db.commit()
    return report


def reset(db: Session) -> int:
    """Удалить синтетических пользователей и все их строки. Возвращает число удалённых."""
    ensure_allowed_env()
    ids = [
        uid
        for (uid,) in db.query(User.telegram_id).filter(
            User.telegram_id >= SYNTHETIC_ID_BASE, User.telegram_id < SYNTHETIC_ID_MAX
        )
    ]
    if not ids:
        return 0
    # Дети явно: ON DELETE CASCADE есть в Postgres, но не в SQLite-тестах.
    for model in (NutritionLog, Weight, ActivityLog, SupplementLog, BloodTest, UserSettings):
        db.execute(delete(model).where(model.user_id.in_(ids)))
    db.execute(
        text("DELETE FROM blood_pressure_logs WHERE user_id >= :lo AND user_id < :hi"),
        {"lo": SYNTHETIC_ID_BASE, "hi": SYNTHETIC_ID_MAX},
    )
    db.execute(delete(User).where(User.telegram_id.in_(ids)))
    db.commit()
    return len(ids)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--users", type=int, default=3, help="сколько синтетических пользователей создать")
    parser.add_argument("--days", type=int, default=60, help="за сколько дней назад генерировать данные")
    parser.add_argument("--attach", type=int, help="залить синтетику в существующий дев-аккаунт (telegram_id)")
    parser.add_argument("--reset", action="store_true", help="удалить всех синтетических пользователей")
    args = parser.parse_args(argv)

    env = ensure_allowed_env()
    from database import SessionLocal

    db = SessionLocal()
    try:
        if args.reset:
            print(f"[{env}] удалено синтетических пользователей: {reset(db)}")
            return 0
        report = seed(db, users=args.users, days=args.days, attach=args.attach)
        for tg_id, counts in report.items():
            print(f"[{env}] {tg_id}: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
