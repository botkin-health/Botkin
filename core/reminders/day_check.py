"""Утренний вопрос «вчера внёс всё?» — защита адаптивной цели от недолога.

Частично внесённый день (забыл ресторан, пиво) занижает адаптивный TDEE и с ним
цель на недели вперёд (core/health/adaptive_tdee.py, ADR-0015). Утром, если
вчерашний лог заметно меньше обычного, спрашиваем один раз двумя кнопками;
ответ пишется в nutrition_day_status и главнее эвристики порога.

Как plan_close: диспетчер (scripts/server/send_reminders.py) поставляет факты из
БД, а решение «пора ли спрашивать», тексты и клавиатура — здесь, чисто и тестируемо.
"""

from __future__ import annotations

from datetime import date, datetime, time
from statistics import median
from typing import Mapping, Optional

DAY_CHECK_KEY = "__day_check__"
DAY_CHECK_WINDOW: tuple[time, time] = (time(9, 0), time(11, 59))
# Спрашиваем, если вчера внесено меньше этой доли обычного дня.
SUSPICIOUS_RATIO = 0.85
# История для «обычного дня» и минимум внесённых дней — тем, кто ведёт дневник
# от случая к случаю, вопрос каждое утро был бы спамом.
HISTORY_DAYS = 28
MIN_HISTORY_DAYS = 10


def in_window(now_local: datetime, last_sent: Mapping, today_iso: str) -> bool:
    """Утреннее окно и сегодня ещё не спрашивали."""
    if (last_sent or {}).get(DAY_CHECK_KEY) == today_iso:
        return False
    start, end = DAY_CHECK_WINDOW
    return start <= now_local.time() <= end


def typical_day_kcal(
    intake_by_day: Mapping[date, float], statuses: Mapping[date, bool], before: date
) -> Optional[float]:
    """Медиана внесённых дней до `before` (без отмеченных неполными). None — истории мало."""
    days = [k for d, k in intake_by_day.items() if d < before and k > 0 and statuses.get(d) is not False]
    if len(days) < MIN_HISTORY_DAYS:
        return None
    return median(days)


def should_ask_about(yesterday_kcal: float, typical: Optional[float], already_marked: bool) -> bool:
    """Вчера что-то внесено, но заметно меньше обычного, и отметки ещё нет.

    Совсем пустой день вопроса не требует: в расчёт он и так не попадает.
    """
    if already_marked or not typical or yesterday_kcal <= 0:
        return False
    return yesterday_kcal < SUSPICIOUS_RATIO * typical


def build_question(day: date, kcal: float, typical: float) -> str:
    return (
        f"📒 За вчера ({day:%d.%m}) записано {kcal:.0f} ккал, обычно у тебя около {typical:.0f}.\nЭто всё, что ты съел?"
    )


def build_keyboard(date_iso: str) -> dict:
    """reply_markup для Bot API. Формат callback_data — как у aiogram CallbackData
    с prefix='daychk' (handlers/callbacks.py::DayCheckCallback); эквивалентность
    проверяет тест, общего кода у core/ и telegram-bot/ нет."""
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Да, всё", "callback_data": f"daychk:yes:{date_iso}"},
                {"text": "➕ Что-то пропустил", "callback_data": f"daychk:no:{date_iso}"},
            ]
        ]
    }


ANSWER_COMPLETE = "✅ Принял: {day} внесён полностью."
ANSWER_INCOMPLETE = (
    "Понял, {day} не пойдёт в расчёт твоей нормы — так она не будет зря снижаться.\n"
    "Вспомнишь, что ещё ел, — напиши «вчера ещё …» или пришли фото, внесу задним числом."
)
