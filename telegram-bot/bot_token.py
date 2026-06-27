"""Единый резолвер токена бота из окружения (#201).

Исторически токен читался по-разному: `bot.py` (поллинг) — только
`TELEGRAM_BOT_TOKEN`, а webhook-модули предпочитали `BOT_TOKEN` (fallback на
`TELEGRAM_BOT_TOKEN`). При половинчатом `.env`, где `BOT_TOKEN` и
`TELEGRAM_BOT_TOKEN` указывают на РАЗНЫХ ботов, это давало молчаливое
рассогласование: поллинг шёл на один токен, валидация WebApp-initData — на
другой → `403 initData HMAC mismatch` на дев-стенде.

Все модули резолвят токен через эту функцию с единым приоритетом
`TELEGRAM_BOT_TOKEN`-first. Менять приоритет на обратный нельзя: тогда `bot.py`
начнёт читать `BOT_TOKEN` и дев-бот подключится к прод-боту.
"""

import os


def resolve_bot_token() -> str:
    """Токен бота: `TELEGRAM_BOT_TOKEN`, иначе `BOT_TOKEN`. Пусто → ``""``."""
    return os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN", "")
