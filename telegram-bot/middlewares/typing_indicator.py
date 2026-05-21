"""Middleware: показывать нативный 'печатает...' в Telegram пока handler работает.

Telegram гасит chat_action через ~5 сек, а LLM-ответы у нас часто 10-30 сек,
поэтому шлём typing в фоне каждые 4 сек.

Срабатывает только для сообщений с пользовательским контентом (text/voice/photo/
document/video_note). Команды (/start, /menu и т.п.) пропускаем — они быстрые,
индикатор просто моргнёт впустую.
"""

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

logger = logging.getLogger(__name__)


def _needs_typing(event: Message) -> bool:
    if event.text and event.text.startswith("/"):
        return False
    return bool(event.text or event.voice or event.photo or event.document or event.video_note)


class TypingMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not _needs_typing(event):
            return await handler(event, data)

        bot = event.bot
        chat_id = event.chat.id

        async def _loop():
            while True:
                try:
                    await bot.send_chat_action(chat_id=chat_id, action="typing")
                except Exception as e:
                    logger.debug(f"send_chat_action failed: {e}")
                await asyncio.sleep(4.0)

        task = asyncio.create_task(_loop())
        try:
            return await handler(event, data)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.debug(f"typing task cleanup: {e}")
