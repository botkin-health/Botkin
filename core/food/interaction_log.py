"""Логирование пищевых взаимодействий для наблюдаемости pipeline (#193).

Пишет в таблицу ``food_interactions`` В ДОПОЛНЕНИЕ к ``nutrition_log``: сырое
сообщение пользователя, распознанный ботом состав (до подтверждения), ответ бота,
связь с итоговой записью еды и статус. Позволяет ретро-аудит
«что прислал → что распознал → что ответил → что записалось».

Запись безопасна: любая ошибка логируется и проглатывается, чтобы сбой
наблюдаемости НЕ ломал основной хендлер еды (тот же принцип, что в
``core.agent_chat.log_router_raw_text``). Использует ORM-модель (а не raw SQL с
``CAST … AS JSONB``), чтобы работать и на проде (PostgreSQL/JSONB), и в
in-memory SQLite тестах.

Read-side — ``scripts/review_food_interactions.py`` и аудит-читалка в админке.
"""

import logging
from typing import Any, Optional

from database import SessionLocal
from database.models import FoodInteraction

logger = logging.getLogger(__name__)

VALID_SOURCES = frozenset({"text", "photo", "voice"})
VALID_STATUSES = frozenset({"saved", "cancelled", "edited"})


def log_food_interaction(
    user_id: int,
    source: str,
    *,
    raw_text: Optional[str] = None,
    media_path: Optional[str] = None,
    recognized: Optional[Any] = None,
    bot_reply: Optional[str] = None,
    nutrition_log_id: Optional[int] = None,
    status: str = "saved",
) -> None:
    """Сохраняет одно пищевое взаимодействие в ``food_interactions``.

    Никогда не бросает исключение — наблюдаемость не должна ронять логирование еды.

    Args:
        user_id: telegram_id пользователя.
        source: канал сообщения — ``text`` / ``photo`` / ``voice``.
        raw_text: исходный текст пользователя (caption для фото, расшифровка для голоса).
        media_path: путь к медиафайлу в ``data/media`` (для фото/голоса).
        recognized: что бот распознал — состав/БЖУ/ккал до подтверждения (JSON-сериализуемое).
        bot_reply: текст ответа бота пользователю.
        nutrition_log_id: id итоговой записи в ``nutrition_log`` (если создана).
        status: ``saved`` (записано) / ``cancelled`` (отменено) / ``edited`` (отредактировано).
    """
    try:
        if source not in VALID_SOURCES:
            logger.warning("log_food_interaction: неизвестный source=%r (user %s), пропускаю", source, user_id)
            return
        if status not in VALID_STATUSES:
            logger.warning("log_food_interaction: неизвестный status=%r (user %s), пропускаю", status, user_id)
            return

        db = SessionLocal()
        try:
            db.add(
                FoodInteraction(
                    user_id=user_id,
                    source=source,
                    raw_text=raw_text,
                    media_path=media_path,
                    recognized=recognized,
                    bot_reply=bot_reply,
                    nutrition_log_id=nutrition_log_id,
                    status=status,
                )
            )
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning("log_food_interaction failed for user %s: %s", user_id, e)


def get_food_interactions(db, user_id: int, limit: int = 50) -> list[FoodInteraction]:
    """Возвращает пищевые взаимодействия пользователя, новые первыми (read-side аудита).

    Принимает готовую сессию ``db`` (не открывает свою) — для тестируемости и
    переиспользования из скрипта/админки. Восстанавливает цепочку
    «что прислал → что распознал → что ответил → что записалось».
    """
    return (
        db.query(FoodInteraction)
        .filter(FoodInteraction.user_id == user_id)
        .order_by(FoodInteraction.created_at.desc(), FoodInteraction.id.desc())
        .limit(limit)
        .all()
    )
