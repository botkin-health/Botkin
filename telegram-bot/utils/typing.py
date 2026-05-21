"""Хелпер: держать индикатор 'печатает...' в Telegram пока идёт долгая операция.

Telegram гасит chat_action через ~5 сек, а LLM-ответы у нас часто 10-30 сек.
Этот context-manager шлёт typing в фоне каждые `interval` сек, пока тело блока
работает.
"""

import asyncio
from contextlib import asynccontextmanager

from aiogram import Bot


@asynccontextmanager
async def keep_typing(bot: Bot, chat_id: int, interval: float = 4.0):
    async def _loop():
        while True:
            try:
                await bot.send_chat_action(chat_id=chat_id, action="typing")
            except Exception:
                pass
            await asyncio.sleep(interval)

    task = asyncio.create_task(_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
