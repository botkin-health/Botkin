#!/usr/bin/env python3
"""
Family-forward: пересылка фото еды + КБЖУ доверенным получателям.

Когда пользователь сохраняет приём пищи, бот пересылает КОПИЮ фото блюда
и распознанные КБЖУ заранее настроенным получателям (например, супруге и
лечащему врачу).

⚠️ ПЕРЕСЫЛАЕТСЯ ТОЛЬКО ЕДА: фото + калории/белки/жиры/углеводы.
Никакие медицинские данные (глюкоза/CGM, давление, диагнозы, анализы,
лекарства) НЕ пересылаются — это жёсткая граница приватности.

Получатели хранятся в UserSettings.food_forward_recipients (list[int] chat_id).
Предусловие Telegram: получатель должен сам нажать /start у бота (бот не может
писать первым). Если получатель не начинал диалог — ловим TelegramForbiddenError
и логируем, НЕ роняя основной поток сохранения еды.
"""
import logging
from pathlib import Path
from typing import Optional

from aiogram import Bot
from aiogram.types import FSInputFile
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from database import SessionLocal
from database.crud import get_user_settings

logger = logging.getLogger(__name__)


def _format_caption(sender_name: str, meal_name: str, totals: dict) -> str:
    return (
        f"🍽 {sender_name}: <b>{meal_name}</b>\n"
        f"{totals.get('calories', 0):.0f} ккал · "
        f"Б {totals.get('protein', 0):.0f}г · "
        f"Ж {totals.get('fats', 0):.0f}г · "
        f"У {totals.get('carbs', 0):.0f}г"
    )


def get_recipients(sender_id: int) -> list[int]:
    """Список chat_id получателей форварда для отправителя (из UserSettings)."""
    try:
        db = SessionLocal()
        try:
            settings = get_user_settings(db, sender_id)
            return [int(x) for x in (getattr(settings, "food_forward_recipients", None) or [])]
        finally:
            db.close()
    except Exception:
        logger.exception("family-forward: не удалось прочитать получателей для %s", sender_id)
        return []


async def forward_meal_to_recipients(
    bot: Bot,
    sender_id: int,
    meal_name: str,
    totals: dict,
    photo_path: Optional[str] = None,
    sender_name: str = "Андрей",
) -> int:
    """Переслать фото еды + КБЖУ всем настроенным получателям sender_id.

    Возвращает число успешных доставок. Никогда не бросает исключения наружу —
    это вспомогательный поток, он не должен ломать сохранение приёма пищи.
    """
    recipients = get_recipients(sender_id)
    if not recipients:
        return 0

    caption = _format_caption(sender_name, meal_name, totals)
    delivered = 0

    for rid in recipients:
        try:
            if photo_path and Path(photo_path).is_file():
                await bot.send_photo(rid, FSInputFile(photo_path), caption=caption, parse_mode="HTML")
            else:
                # фото нет (например, приём залогирован текстом) — шлём только КБЖУ
                await bot.send_message(rid, caption, parse_mode="HTML")
            delivered += 1
            logger.info("family-forward: отправлено получателю %s (%s)", rid, meal_name)
        except TelegramForbiddenError:
            logger.warning(
                "family-forward: получатель %s не нажимал /start у бота — пропуск", rid
            )
        except TelegramBadRequest as e:
            logger.warning("family-forward: BadRequest для %s: %s", rid, e)
        except Exception:
            logger.exception("family-forward: ошибка отправки получателю %s", rid)

    return delivered
