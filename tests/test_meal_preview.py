"""Единый рендер превью еды (#427) — handlers/meal_preview.py.

Раньше карточка собиралась вручную в трёх местах (photo.py, две ветки
text.py) и успела разъехаться (разные макросы, разное отображение даты,
битая клавиатура в ветке добавки+еда). Эти тесты фиксируют контракт
единой функции рендера, чтобы разъезд не повторился.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOT_ROOT = PROJECT_ROOT / "telegram-bot"
for p in [str(PROJECT_ROOT), str(BOT_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from handlers.callbacks import MealConfirmationCallback
from handlers.meal_preview import (
    CONFIRM_HINT,
    format_header,
    format_items,
    label_hint,
    meal_confirm_keyboard,
    render_meal_preview,
    render_multi_meal_summary,
)


# ── format_header ─────────────────────────────────────────────────────────


def test_header_plain_food():
    assert format_header("Овсянка") == "🍽️ <b>Овсянка</b>\n\n"


def test_header_plan_variant():
    assert format_header("Овсянка", is_plan=True) == "📋 <b>План: Овсянка</b>\n\n"


def test_header_weekday_date_style():
    header = format_header("Ужин", custom_date="2026-09-10", date_style="weekday")
    assert header == "🍽️ <b>Ужин в четверг 10.09.2026</b>\n\n"


def test_header_weekday_date_style_fallback_on_bad_date():
    header = format_header("Ужин", custom_date="не-дата", date_style="weekday")
    assert header == "🍽️ <b>Ужин (не-дата)</b>\n\n"


def test_header_line_date_style():
    header = format_header("Ужин", custom_date="2026-09-10", date_style="line")
    assert header == "🍽️ <b>Ужин</b>\n📅 на 2026-09-10\n"


def test_header_line_date_style_without_date():
    header = format_header("Ужин", date_style="line")
    assert header == "🍽️ <b>Ужин</b>\n"


def test_header_none_date_style_ignores_custom_date():
    header = format_header("Ужин", custom_date="2026-09-10", date_style="none")
    assert header == "🍽️ <b>Ужин</b>\n\n"


def test_header_escapes_html_in_name():
    header = format_header("<b>злой</b> ужин")
    assert "<b>злой</b> ужин" not in header
    assert "&lt;b&gt;злой&lt;/b&gt; ужин" in header


# ── format_items ──────────────────────────────────────────────────────────


def test_items_without_macros():
    items = [{"product": "Банан", "weight_g": 120, "calories": 108}]
    text = format_items(items, with_macros=False)
    assert text == "• Банан (120г) — 108 ккал\n"


def test_items_with_macros():
    items = [{"product": "Банан", "weight_g": 120, "calories": 108, "protein": 1, "fats": 0, "carbs": 27}]
    text = format_items(items, with_macros=True)
    assert text == "• Банан (120г) — 108 ккал (Б:1 Ж:0 У:27)\n"


def test_items_unknown_weight_shows_question_mark():
    items = [{"product": "Суп", "calories": 200}]
    text = format_items(items, with_macros=False)
    assert "(?)" in text


def test_items_escape_product_name():
    items = [{"product": "<b>злой</b>", "weight_g": 10, "calories": 5}]
    text = format_items(items, with_macros=False)
    assert "<b>злой</b>" not in text
    assert "&lt;b&gt;злой&lt;/b&gt;" in text


# ── label_hint ────────────────────────────────────────────────────────────


def test_label_hint_present_for_single_item_with_per100g_label():
    items = [{"product": "Йогурт", "weight_g": 150, "calories": 90}]
    label = {"calories_per_100g": 60}
    hint = label_hint(items, label)
    assert "этикетка: 60 ккал/100 г" in hint
    assert "за 150 г = 90 ккал" in hint


def test_label_hint_absent_without_label():
    items = [{"product": "Йогурт", "weight_g": 150, "calories": 90}]
    assert label_hint(items, None) == ""


def test_label_hint_absent_for_multiple_items():
    items = [
        {"product": "Йогурт", "weight_g": 150, "calories": 90},
        {"product": "Мёд", "weight_g": 20, "calories": 60},
    ]
    label = {"calories_per_100g": 60}
    assert label_hint(items, label) == ""


def test_label_hint_absent_without_weight():
    items = [{"product": "Йогурт", "calories": 90}]
    label = {"calories_per_100g": 60}
    assert label_hint(items, label) == ""


# ── render_meal_preview ───────────────────────────────────────────────────


def test_render_meal_preview_basic_with_macros():
    items = [{"product": "Банан", "weight_g": 120, "calories": 108, "protein": 1, "fats": 0, "carbs": 27}]
    totals = {"calories": 108, "protein": 1, "fats": 0, "carbs": 27}
    text = render_meal_preview("Завтрак", items, totals, with_macros=True)
    assert text.startswith("🍽️ <b>Завтрак</b>\n\n")
    assert "(Б:1 Ж:0 У:27)" in text
    assert "📊 <b>Итого: 108 ккал</b>" in text
    assert "Б: 1 | Ж: 0 | У: 27" in text


def test_render_meal_preview_without_macros_suffix():
    items = [{"product": "Банан", "weight_g": 120, "calories": 108, "protein": 1, "fats": 0, "carbs": 27}]
    totals = {"calories": 108, "protein": 1, "fats": 0, "carbs": 27}
    text = render_meal_preview("Завтрак", items, totals, with_macros=False)
    assert "(Б:" not in text


def test_render_meal_preview_applied_note_before_itogo():
    items = [{"product": "Банан", "weight_g": 120, "calories": 108}]
    totals = {"calories": 108}
    text = render_meal_preview("Завтрак", items, totals, applied_note="вес уменьшен до 120г")
    note_pos = text.index("<i>вес уменьшен до 120г</i>")
    itogo_pos = text.index("📊 <b>Итого")
    assert note_pos < itogo_pos


def test_render_meal_preview_prefix_html_goes_first():
    items = [{"product": "Банан", "weight_g": 120, "calories": 108}]
    totals = {"calories": 108}
    prefix = "💊 ✅ <b>Добавки:</b>\n• Магний\n\n"
    text = render_meal_preview("Завтрак", items, totals, prefix_html=prefix)
    assert text.startswith(prefix)


def test_render_meal_preview_never_raises_on_missing_totals_keys():
    items = [{"product": "Банан", "weight_g": 120, "calories": 108}]
    text = render_meal_preview("Завтрак", items, {})
    assert "📊 <b>Итого: 0 ккал</b>" in text
    assert "Б: 0 | Ж: 0 | У: 0" in text


def test_render_meal_preview_never_raises_on_none_totals():
    items = [{"product": "Банан", "weight_g": 120, "calories": 108}]
    text = render_meal_preview("Завтрак", items, None)
    assert "📊 <b>Итого: 0 ккал</b>" in text


def test_render_meal_preview_plan_header():
    items = [{"product": "Банан", "weight_g": 120, "calories": 108}]
    text = render_meal_preview("Ужин", items, {"calories": 108}, is_plan=True)
    assert text.startswith("📋 <b>План: Ужин</b>\n\n")


# ── #436: подсказка про обязательное подтверждение ─────────────────────────


def test_render_meal_preview_includes_confirm_hint():
    """Прецедент #436: юзер прислал 30 фото еды за 3 недели, ни одного не
    сохранил — не понял, что превью нужно подтвердить кнопкой. Подсказка
    должна быть в каждой собранной карточке."""
    items = [{"product": "Банан", "weight_g": 120, "calories": 108}]
    text = render_meal_preview("Завтрак", items, {"calories": 108})
    assert CONFIRM_HINT in text
    assert "Сохранить" in CONFIRM_HINT


def test_render_meal_preview_confirm_hint_after_totals():
    items = [{"product": "Банан", "weight_g": 120, "calories": 108}]
    text = render_meal_preview("Завтрак", items, {"calories": 108})
    itogo_pos = text.index("📊 <b>Итого")
    hint_pos = text.index(CONFIRM_HINT)
    assert itogo_pos < hint_pos


def test_render_meal_preview_confirm_hint_present_for_plan_too():
    items = [{"product": "Банан", "weight_g": 120, "calories": 108}]
    text = render_meal_preview("Ужин", items, {"calories": 108}, is_plan=True)
    assert CONFIRM_HINT in text


# ── render_multi_meal_summary (text.py: несколько приёмов в одном сообщении) ─


def test_multi_meal_summary_basic():
    multi_meals = [
        {
            "meal_name": "Завтрак",
            "meal_totals": {"calories": 300},
            "meal_items": [{"product": "Овсянка", "weight_g": 200, "calories": 300}],
        },
        {
            "meal_name": "Обед",
            "meal_totals": {"calories": 500},
            "meal_items": [{"product": "Суп", "weight_g": 300, "calories": 500}],
        },
    ]
    text = render_multi_meal_summary(multi_meals)
    assert "Завтрак" in text
    assert "Обед" in text
    assert "📊 <b>Итого: 800 ккал</b>" in text


def test_multi_meal_summary_includes_confirm_hint():
    """#436: сводная карточка нескольких приёмов тоже висит за кнопкой
    «Сохранить всё» — подсказка обязана быть."""
    multi_meals = [
        {
            "meal_name": "Завтрак",
            "meal_totals": {"calories": 300},
            "meal_items": [{"product": "Овсянка", "weight_g": 200, "calories": 300}],
        }
    ]
    text = render_multi_meal_summary(multi_meals)
    assert CONFIRM_HINT in text
    # подсказка должна идти после «Итого», а не потеряться где-то в середине
    assert text.index("📊 <b>Итого") < text.index(CONFIRM_HINT)


def test_multi_meal_summary_skipped_and_date():
    multi_meals = [
        {
            "meal_name": "Завтрак",
            "meal_totals": {"calories": 300},
            "meal_items": [{"product": "Овсянка", "weight_g": 200, "calories": 300}],
        }
    ]
    text = render_multi_meal_summary(multi_meals, skipped=["непонятная еда"], custom_date="2026-09-10")
    assert "непонятная еда" in text
    assert "10.09.2026" in text
    assert CONFIRM_HINT in text


def test_multi_meal_summary_bad_date_falls_back_to_raw_string():
    multi_meals = [
        {
            "meal_name": "Завтрак",
            "meal_totals": {"calories": 300},
            "meal_items": [{"product": "Овсянка", "weight_g": 200, "calories": 300}],
        }
    ]
    text = render_multi_meal_summary(multi_meals, custom_date="не-дата")
    assert "не-дата" in text


# ── meal_confirm_keyboard ─────────────────────────────────────────────────


def test_keyboard_has_two_buttons_with_expected_callback_data():
    markup = meal_confirm_keyboard()
    buttons = [b for row in markup.inline_keyboard for b in row]
    assert len(buttons) == 2

    save_cb = MealConfirmationCallback(action="save", meal_type="regular").pack()
    cancel_cb = MealConfirmationCallback(action="cancel", meal_type="regular").pack()

    assert buttons[0].text == "✅ Сохранить"
    assert buttons[0].callback_data == save_cb
    assert buttons[1].text == "❌ Отмена"
    assert buttons[1].callback_data == cancel_cb


def test_keyboard_plan_variant_text():
    markup = meal_confirm_keyboard(is_plan=True)
    buttons = [b for row in markup.inline_keyboard for b in row]
    assert buttons[0].text == "✅ Сохранить план"
    # callback_data остаётся тем же (action="save") — план отличается только текстом кнопки
    assert buttons[0].callback_data == MealConfirmationCallback(action="save", meal_type="regular").pack()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
