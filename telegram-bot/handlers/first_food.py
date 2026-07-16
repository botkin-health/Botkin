"""Одноразовая празднующая приписка при первом логировании еды + событие E5.

Замыкает демо-петлю онбординга (PR1 ставит onboarding_data["first_food_pending"]
в конце мастера). E5 first_food_logged — событие активации; пишется всегда с
once=True (partial-unique-индекс дедупит до первого в жизни лога). Празднующая
строка — только если стоит флаг демо.
"""

import logging

from database import SessionLocal
from database.models import User, log_event

logger = logging.getLogger(__name__)

_CELEBRATION = (
    "🎉 Видишь — я посчитал сам, безо всяких команд. Так можно всегда: "
    "пиши текстом, шли фото или голосовое."
)


async def record_first_food(telegram_user_id: int, message) -> None:
    """После успешного сохранения приёма пищи: логируем E5 (once) и, если юзер
    в демо-этапе онбординга, шлём празднующую строку и снимаем флаг.

    `message` — aiogram Message (для .answer). Ошибки не пробрасываем: это
    необязательный «украшающий» слой, он не должен ломать сохранение еды."""
    db = SessionLocal()
    try:
        log_event(db, user_id=telegram_user_id, event="first_food_logged", once=True)
        user = db.query(User).filter_by(telegram_id=telegram_user_id).first()
        pending = bool((user.onboarding_data or {}).get("first_food_pending")) if user else False
        if pending:
            data = dict(user.onboarding_data or {})
            data.pop("first_food_pending", None)
            user.onboarding_data = data
        db.commit()
        if pending:
            await message.answer(_CELEBRATION)
    except Exception:
        logger.exception("record_first_food failed for %s", telegram_user_id)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()
