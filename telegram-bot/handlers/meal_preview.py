#!/usr/bin/env python3
"""Единый рендер превью приёма пищи и клавиатуры «Сохранить/Отмена» (#427).

Раньше карточка (заголовок + список позиций + «Итого» + клавиатура)
собиралась вручную в трёх местах — photo.py::handle_description,
text.py (одиночная еда) и text.py (добавки+еда) — и успела разъехаться:
разный набор макросов в позициях, разное отображение даты, разная (и в
одном месте — битая) клавиатура. Этот модуль — единственный источник
правды для текста и клавиатуры карточки.
"""

import html
from datetime import datetime
from typing import Any, Dict, List, Optional

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.food.nutrition import format_kcal_warning
from handlers.callbacks import MealConfirmationCallback

WEEKDAYS_RU = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


def format_header(
    meal_name: str,
    *,
    is_plan: bool = False,
    custom_date: Optional[str] = None,
    date_style: str = "weekday",
) -> str:
    """Заголовок карточки: эмодзи + опц. «План: » + название + опц. дата.

    date_style:
      - "weekday" — дата приклеена к названию: «… в среду 10.09.2026»
        (fallback «(YYYY-MM-DD)», если не распарсилась); заголовок
        завершается пустой строкой (как в одиночной еде text.py).
      - "line" — дата отдельной строкой «📅 на YYYY-MM-DD» без пустой
        строки после заголовка (как в ветке добавки+еда text.py).
      - "none" — без даты вообще (как в photo.py).
    """
    emoji = "📋" if is_plan else "🍽️"
    label = "План: " if is_plan else ""
    safe_name = html.escape(str(meal_name))
    title = f"{emoji} <b>{label}{safe_name}</b>"

    if date_style == "weekday" and custom_date:
        try:
            date_obj = datetime.strptime(custom_date, "%Y-%m-%d")
            weekday = WEEKDAYS_RU[date_obj.weekday()]
            formatted_date = date_obj.strftime("%d.%m.%Y")
            title = f"{emoji} <b>{label}{safe_name} в {weekday} {formatted_date}</b>"
        except ValueError:
            title = f"{emoji} <b>{label}{safe_name} ({custom_date})</b>"
        return f"{title}\n\n"

    if date_style == "line":
        text = f"{title}\n"
        if custom_date:
            text += f"📅 на {custom_date}\n"
        return text

    # date_style == "none" (или "weekday" без custom_date)
    return f"{title}\n\n"


def format_items(items: List[Dict[str, Any]], *, with_macros: bool) -> str:
    """Список позиций: «• name (Xг) — Y ккал» + опц. « (Б:p Ж:f У:c)»."""
    lines = []
    for item in items:
        w_str = f"{item['weight_g']}г" if item.get("weight_g") else "?"
        cal = item.get("calories", 0) or 0
        safe_product = html.escape(str(item.get("product", "")))
        line = f"• {safe_product} ({w_str}) — {int(cal)} ккал"
        if with_macros:
            p = int(item.get("protein", 0) or 0)
            f_val = int(item.get("fats", 0) or 0)
            c = int(item.get("carbs", 0) or 0)
            line += f" (Б:{p} Ж:{f_val} У:{c})"
        lines.append(line + "\n")
    return "".join(lines)


def label_hint(items: List[Dict[str, Any]], product_label: Optional[dict]) -> str:
    """Подсказка «этикетка: N ккал/100 г · за M г = X ккал» (#409).

    Только когда есть calories_per_100g И ровно один item с известным весом —
    иначе непонятно к какой позиции относится этикетка.
    """
    label = product_label or {}
    if label.get("calories_per_100g") and len(items) == 1 and items[0].get("weight_g"):
        return (
            f"<i>этикетка: {int(label['calories_per_100g'])} ккал/100 г · "
            f"за {int(items[0]['weight_g'])} г = {int(items[0].get('calories', 0) or 0)} ккал</i>\n"
        )
    return ""


def render_meal_preview(
    meal_name: str,
    items: List[Dict[str, Any]],
    totals: Optional[Dict[str, Any]],
    *,
    is_plan: bool = False,
    custom_date: Optional[str] = None,
    date_style: str = "weekday",
    with_macros: bool = True,
    product_label: Optional[dict] = None,
    applied_note: Optional[str] = None,
    prefix_html: str = "",
) -> str:
    """Собрать полный текст карточки превью приёма пищи.

    prefix_html — блок, который печатается ДО заголовка (используется веткой
    «добавки+еда» в text.py для «💊 ✅ <b>Добавки:</b>\\n• …\\n\\n»).
    applied_note — что изменила правка пользователя (курсивом, перед «Итого»).
    Никогда не падает даже если totals — None или без нужных ключей.
    """
    totals = totals or {}

    text = prefix_html
    text += format_header(meal_name, is_plan=is_plan, custom_date=custom_date, date_style=date_style)
    text += format_items(items, with_macros=with_macros)
    text += label_hint(items, product_label)
    if applied_note:
        text += f"<i>{html.escape(str(applied_note))}</i>\n"

    calories = int(totals.get("calories", 0) or 0)
    protein = int(totals.get("protein", 0) or 0)
    fats = int(totals.get("fats", 0) or 0)
    carbs = int(totals.get("carbs", 0) or 0)
    text += f"\n📊 <b>Итого: {calories} ккал</b>\n"
    text += f"Б: {protein} | Ж: {fats} | У: {carbs}"
    text += format_kcal_warning(totals)

    return text


def meal_confirm_keyboard(*, is_plan: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура «✅ Сохранить(план)» / «❌ Отмена» — единая для всех трёх мест."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Сохранить план" if is_plan else "✅ Сохранить",
        callback_data=MealConfirmationCallback(action="save", meal_type="regular").pack(),
    )
    builder.button(
        text="❌ Отмена",
        callback_data=MealConfirmationCallback(action="cancel", meal_type="regular").pack(),
    )
    return builder.as_markup()
