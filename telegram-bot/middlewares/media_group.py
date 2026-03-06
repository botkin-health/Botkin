import asyncio
from typing import Any, Awaitable, Callable, Dict, List
from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

class MediaGroupMiddleware(BaseMiddleware):
    """
    Middleware для сбора медиагруппы (альбома) в один список.
    """
    ALBUM_DATA: Dict[str, List[Message]] = {}
    ALBUM_TIMEOUT = 1.0  # сек ожидания

    def __init__(self, latency: float | int = 0.5):
        self.latency = latency

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Работаем только с Message
        if not isinstance(event, Message):
            return await handler(event, data)

        # Если это не медиагруппа, просто отдаем дальше
        if not event.media_group_id:
            return await handler(event, data)

        try:
            self.ALBUM_DATA[event.media_group_id].append(event)
            return  # Прерываем обработку этого апдейта, ждем остальные
        except KeyError:
            self.ALBUM_DATA[event.media_group_id] = [event]
            await asyncio.sleep(self.latency)

            # Передаем весь накопленный альбом в handler через поле album (data["album"])
            message_list = self.ALBUM_DATA[event.media_group_id].copy()
            data["album"] = message_list
            del self.ALBUM_DATA[event.media_group_id]

            # Делаем "главным" сообщением первое (в нём обычно caption)
            return await handler(message_list[0], data)
