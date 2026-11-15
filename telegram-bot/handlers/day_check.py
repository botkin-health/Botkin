#!/usr/bin/env python3
"""Кнопки утреннего вопроса «вчера внёс всё?» (адаптивная цель, ADR-0015).

Вопрос шлёт scripts/server/send_reminders.py::dispatch_day_check сырым Bot API.
Здесь только запись ответа в nutrition_day_status: «нет» исключает день из
адаптивного TDEE, «да» оставляет даже лёгкий день в расчёте.
"""

import logging
from datetime import date as date_cls

from aiogram import Router
from aiogram.types import CallbackQuery

from database import SessionLocal
from database.crud import set_day_status
from handlers.callbacks import DayCheckCallback
from handlers.photo import safe_edit_text

from core.reminders.day_check import ANSWER_COMPLETE, ANSWER_INCOMPLETE

logger = logging.getLogger(__name__)

router = Router()


@router.callback_query(DayCheckCallback.filter())
async def handle_day_check(callback: CallbackQuery, callback_data: DayCheckCallback):
    user_id = callback.from_user.id
    try:
        await callback.answer()
        if callback_data.answer not in ("yes", "no"):
            return
        try:
            day = date_cls.fromisoformat(callback_data.date)
        except ValueError:
            logger.warning("DayCheckCallback: некорректная дата %r (user_id=%s)", callback_data.date, user_id)
            return

        complete = callback_data.answer == "yes"
        # БД до сетевого вызова, сессия закрыта до await (#347).
        db = SessionLocal()
        try:
            set_day_status(db, user_id, day, complete, source="morning_check")
        finally:
            db.close()

        label = f"{day:%d.%m}"
        text = (ANSWER_COMPLETE if complete else ANSWER_INCOMPLETE).format(day=label)
        await safe_edit_text(callback.message, text)
    except Exception:
        logger.exception("Ошибка обработки DayCheckCallback для user_id=%s", user_id)
        try:
            await callback.answer("⚠️ Не получилось сохранить ответ, попробуй позже.", show_alert=True)
        except Exception:  # noqa: BLE001 — callback мог уже быть отвечен
            pass
