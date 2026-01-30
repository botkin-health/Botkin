from aiogram import BaseMiddleware
from aiogram.types import Update
from collections import deque
import logging

class IdempotencyMiddleware(BaseMiddleware):
    """
    Middleware для фильтрации дублирующихся обновлений от Telegram.
    Хранит идентификаторы последних обработанных сообщений и отбрасывает повторы.
    """
    def __init__(self, capacity: int = 100):
        self.capacity = capacity
        # Храним ключи уникальности
        self.processed_keys = deque(maxlen=capacity)
        self.logger = logging.getLogger(__name__)

    async def __call__(self, handler, event, data):
        # Работаем только с объектами Update
        if not isinstance(event, Update):
            return await handler(event, data)

        key = None
        
        # Определяем ключ уникальности в зависимости от типа обновления
        try:
            if event.message:
                # Уникальность сообщения: чат + id сообщения
                key = f"msg_{event.message.chat.id}_{event.message.message_id}"
            elif event.callback_query:
                # Уникальность колбэка: его уникальный id
                key = f"cb_{event.callback_query.id}"
            elif event.edited_message:
                # Уникальность редактирования: чат + id сообщения + дата редактирования
                # (чтобы различать разные правки одного сообщения)
                edit_date = event.edited_message.edit_date or 0
                key = f"edit_{event.edited_message.chat.id}_{event.edited_message.message_id}_{edit_date}"
        except Exception as e:
            self.logger.error(f"Error generating idempotency key: {e}")
            # В случае ошибки лучше пропустить, чем блокировать
            return await handler(event, data)

        if key:
            if key in self.processed_keys:
                self.logger.warning(f"🔁 DETECTED DUPLICATE: Update {event.update_id} dropped (key={key})")
                # Прерываем обработку (не вызываем handler)
                return
            
            # Сохраняем ключ
            self.processed_keys.append(key)

        return await handler(event, data)
