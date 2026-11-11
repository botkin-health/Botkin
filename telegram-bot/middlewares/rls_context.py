"""RLS-контекст на каждый update (ADR-0014).

Outer-middleware уровня Update: берёт ``event_from_user`` (aiogram кладёт его
для message, callback_query, inline и пр.) и выставляет contextvar
``app.user_id`` на всё время обработки. Все ``SessionLocal()``, которые хендлеры
и хелперы откроют в этом update, работают от имени автора update.

Внимание: ``loop.run_in_executor`` контекст НЕ копирует — для синхронной
работы с БД из хендлера использовать ``asyncio.to_thread`` или
``core.infra.ctx.run_in_executor_ctx``.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from database.rls import user_context


class RLSContextMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        uid = getattr(user, "id", None)
        with user_context(uid):
            return await handler(event, data)
