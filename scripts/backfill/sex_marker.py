#!/usr/bin/env python3
"""Бэкфилл маркера «пол задан явно» (`onboarding_data["sex"]`) — #591.

Ставит маркер ТОЛЬКО тем, у кого `users.sex = 'female'` и маркера нет: дефолт
server_default — 'male', значит 'female' мог появиться лишь по явному выбору.
Для `sex = 'male'` без маркера маркер НЕ ставится (не отличить от дефолта) —
таких пользователей нужно спросить в боте.

Dry-run по умолчанию; печатает только счётчики (без имён и ID).
Запуск на сервере: docker exec healthvault_bot python scripts/backfill/sex_marker.py [--apply]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.health.ref_ranges import explicit_sex, set_user_sex  # noqa: E402
from database import SessionLocal  # noqa: E402
from database.models import User  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        users = db.query(User).filter(User.is_active.is_(True)).all()
        to_mark = [u for u in users if explicit_sex(u.onboarding_data) is None and (u.sex or "").lower() == "female"]
        to_ask = [u for u in users if explicit_sex(u.onboarding_data) is None and (u.sex or "").lower() == "male"]
        print(f"active={len(users)} to_mark(female, no marker)={len(to_mark)} to_ask(male, no marker)={len(to_ask)}")
        if not args.apply:
            print("dry-run: ничего не записано (--apply для записи)")
            return
        for u in to_mark:
            set_user_sex(u, u.sex)
        db.commit()
        print(f"marked={len(to_mark)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
