"""Backfill users.jwt_secret для активных пользователей без секрета.

Контекст: BotkinClaw подписывает агентский JWT персональным секретом
(core/agent_chat.py:_generate_jwt). Если jwt_secret=NULL — агент валится
с RuntimeError, а в Telegram виден текст «Разговорный агент временно
недоступен». Новые юзеры с 2026-05-21 получают секрет автоматически
(default в database.models.User.jwt_secret); этот скрипт чинит легаси.

Запуск на сервере:
    docker exec healthvault_bot python -m scripts.backfill_jwt_secret
    docker exec healthvault_bot python -m scripts.backfill_jwt_secret --all  # включая is_active=false
"""

from __future__ import annotations

import argparse
import secrets
import sys

from sqlalchemy import or_

from database import SessionLocal
from database.models import User


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all",
        action="store_true",
        help="Бэкфилл и для неактивных пользователей (по умолчанию только is_active=true).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Показать, кому нужен бэкфилл, без записи в БД.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        q = db.query(User).filter(or_(User.jwt_secret.is_(None), User.jwt_secret == ""))
        if not args.all:
            q = q.filter(User.is_active.is_(True))
        users = q.order_by(User.telegram_id).all()

        if not users:
            print("Все целевые пользователи уже имеют jwt_secret — ничего делать не нужно.")
            return 0

        print(f"Найдено {len(users)} пользователей без jwt_secret:")
        for u in users:
            print(f"  - {u.telegram_id}  {u.first_name or '?':<15}  cohort={u.cohort}  active={u.is_active}")

        if args.dry_run:
            print("\n--dry-run: запись пропущена.")
            return 0

        for u in users:
            u.jwt_secret = secrets.token_hex(32)
        db.commit()
        print(f"\n✅ Выдано {len(users)} новых jwt_secret.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
