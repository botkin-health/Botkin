"""Welcome-сообщение новому family-юзеру через Telegram Bot API."""

from __future__ import annotations

import os
from typing import Literal

import requests

TELEGRAM_API_BASE = "https://api.telegram.org"
REQUEST_TIMEOUT = 15  # seconds


def build_welcome_text(
    *,
    name: str,
    style: Literal["ty", "vy"],
    inviter_name: str,
) -> str:
    """Текст welcome'а — короткий, тёплый, с privacy-блоком и подсказкой."""
    if style == "ty":
        return (
            f"Привет, {name}!\n\n"
            f"{inviter_name} подключил мне твою историю анализов и "
            f"медицинских записей. Теперь я знаю про твой витамин D, аллергии, "
            f"прививки и могу отвечать на вопросы про здоровье, а не только "
            f"логировать еду.\n\n"
            f"📦 Где данные: на сервере проекта Botkin в Германии (Hetzner). "
            f"Доступ только у тебя через @Botkin_md_bot. Папа видит общие "
            f"сводки по семье, но не твою личную переписку со мной.\n\n"
            f"Хочешь отключить расширенный режим — напиши папе или мне «удали мои "
            f"данные».\n\n"
            f"Попробуй спросить:\n"
            f"• «какой у меня был последний витамин D?»\n"
            f"• «на что у меня аллергия?»\n"
            f"• «когда последняя прививка от клещевого энцефалита?»"
        )
    return (
        f"Здравствуйте, {name}!\n\n"
        f"{inviter_name} подключил мне Вашу историю анализов и медицинских записей. "
        f"Теперь я могу отвечать на вопросы про Ваше здоровье, а не только "
        f"логировать питание.\n\n"
        f"📦 Где данные: на сервере проекта Botkin в Германии. Доступ только у Вас "
        f"через @Botkin_md_bot. {inviter_name} видит общие сводки по семье, но "
        f"не Вашу личную переписку со мной.\n\n"
        f"Хотите отключить расширенный режим — напишите «удали мои данные».\n\n"
        f"Попробуйте спросить:\n"
        f"• «какой у меня последний витамин D?»\n"
        f"• «покажи мои хронические диагнозы»"
    )


def send_welcome(*, chat_id: int, text: str) -> int:
    """Отправить через Bot API. Вернуть message_id.

    Raises:
        RuntimeError if TELEGRAM_BOT_TOKEN missing or Telegram API errored.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN env var not set")
    url = f"{TELEGRAM_API_BASE}/bot{token}/sendMessage"
    resp = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=REQUEST_TIMEOUT)
    body = resp.json()
    if resp.status_code != 200 or not body.get("ok"):
        raise RuntimeError(f"Telegram API error: {body.get('description', resp.text)}")
    return body["result"]["message_id"]
