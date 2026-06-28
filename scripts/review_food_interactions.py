"""Аудит пищевого pipeline: показать цепочку взаимодействий пользователя (#193).

Читает таблицу ``food_interactions`` (наблюдаемость): по user_id восстанавливает
«что прислал → что распознал → что ответил → что записалось». Дополняет
``/review-conversations`` (тот видит только агентные диалоги, не пищевые).

Запуск на сервере:
    docker exec healthvault_bot python -m scripts.review_food_interactions --user 303663179
    docker exec healthvault_bot python -m scripts.review_food_interactions --user 303663179 --limit 100
"""

from __future__ import annotations

import argparse
import json
import sys

from database import SessionLocal
from core.food.interaction_log import get_food_interactions


def _fmt(row) -> str:
    ts = row.created_at.strftime("%Y-%m-%d %H:%M") if row.created_at else "—"
    recognized = ""
    if row.recognized:
        try:
            recognized = json.dumps(row.recognized, ensure_ascii=False)[:200]
        except (TypeError, ValueError):
            recognized = str(row.recognized)[:200]
    nl = f" → nutrition_log #{row.nutrition_log_id}" if row.nutrition_log_id else ""
    lines = [
        f"[{ts}] {row.source} · {row.status}{nl}",
        f"  прислал:   {row.raw_text or '—'}",
    ]
    if row.media_path:
        lines.append(f"  медиа:     {row.media_path}")
    if recognized:
        lines.append(f"  распознал: {recognized}")
    lines.append(f"  ответ:     {(row.bot_reply or '—')[:300]}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", type=int, required=True, help="telegram_id пользователя")
    parser.add_argument("--limit", type=int, default=50, help="сколько последних взаимодействий (default 50)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        rows = get_food_interactions(db, args.user, limit=args.limit)
    finally:
        db.close()

    if not rows:
        print(f"Нет пищевых взаимодействий для user {args.user}.")
        return 0

    print(f"Пищевые взаимодействия user {args.user} (последние {len(rows)}, новые сверху):\n")
    for row in rows:
        print(_fmt(row))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
