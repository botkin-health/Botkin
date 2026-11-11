"""
LlmGuardMiddleware — частота и дневной бюджет LLM на пользователя (пентест F15).

Стоит после AuthMiddleware (нужны user_id и cohort) и после MediaGroupMiddleware,
чтобы альбом считался одним сообщением. Логика лимитов — core/llm_budget.py.

Колбэки (кнопки подтверждения) не трогаем: в LLM они не ходят. Короткие служебные
команды пропускаем всегда — пользователь под лимитом должен иметь возможность
открыть /start или /help.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

logger = logging.getLogger(__name__)

# Команды, которые точно не вызывают LLM.
_FREE_COMMANDS = frozenset({"start", "help", "cancel", "stop", "menu", "settings", "privacy"})

_ADMIN_NOTIFY_EVERY_SEC = 24 * 3600
_admin_notified: dict[int, float] = {}


def _command_name(text: str | None) -> str | None:
    if not text or not text.startswith("/"):
        return None
    return text[1:].split(maxsplit=1)[0].split("@", 1)[0].lower()


class LlmGuardMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or event.from_user is None:
            return await handler(event, data)
        if _command_name(event.text) in _FREE_COMMANDS:
            return await handler(event, data)

        from core.llm_budget import check_llm_allowed

        user_id = data.get("user_id") or event.from_user.id
        verdict = check_llm_allowed(int(user_id), data.get("cohort"))
        if verdict.allowed:
            return await handler(event, data)

        logger.warning(
            "llm_guard: reject user=%s reason=%s retry=%ss", user_id, verdict.reason, verdict.retry_after_sec
        )
        try:
            await event.answer(verdict.user_message)
        except Exception:  # noqa: BLE001
            logger.exception("llm_guard: failed to send limit message")
        if verdict.reason in ("user_budget", "global_budget"):
            await _notify_admin(event, int(user_id), verdict.reason)
        return None


async def _notify_admin(event: Message, user_id: int, reason: str) -> None:
    """Раз в сутки на пользователя (и раз в сутки на глобальный стоп) — админу в личку."""
    key = 0 if reason == "global_budget" else user_id
    now = time.monotonic()
    if now - _admin_notified.get(key, -_ADMIN_NOTIFY_EVERY_SEC) < _ADMIN_NOTIFY_EVERY_SEC:
        return
    _admin_notified[key] = now
    try:
        from config.users import ADMIN_USER_ID

        if not ADMIN_USER_ID:
            return
        text = (
            "🚨 Глобальный дневной бюджет LLM исчерпан — AI отключён для всех, кроме owner/админов."
            if reason == "global_budget"
            else f"💸 Пользователь {user_id} упёрся в дневной бюджет LLM."
        )
        await event.bot.send_message(ADMIN_USER_ID, text)
    except Exception:  # noqa: BLE001
        logger.exception("llm_guard: admin notify failed")
