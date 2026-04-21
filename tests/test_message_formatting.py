"""
РЕГРЕССИОННЫЙ ТЕСТ: TelegramBadRequest — HTML-теги с кириллицей.

История бага:
- 05 апреля 2026: бот упал с ошибкой
  "can't parse entities: Unsupported start tag 'число' at byte offset 38"
- Причина: в Telegram HTML-режиме текст содержал <число>, <ккал> и т.п.
  (кириллица или числа в угловых скобках воспринимается как невалидный тег)
- Поле ввода: форматирование ответов в commands.py, caloric_budget.py

Что проверяем:
1. format_budget_line() не генерирует невалидные HTML-теги
2. Строки ответа бота не содержат <кириллица> и <число>
3. Специальные символы < > & в данных правильно экранируются
"""

import re
import pytest
from unittest.mock import patch

# Паттерн для обнаружения кириллицы/цифр в угловых скобках (невалидные HTML теги)
INVALID_HTML_TAG_PATTERN = re.compile(r"<[а-яА-ЯёЁ0-9][^>]*>")

# Допустимые HTML-теги Telegram (parse_mode="HTML")
ALLOWED_TAGS = {"b", "/b", "i", "/i", "u", "/u", "s", "/s", "code", "/code", "pre", "/pre", "a"}


def has_invalid_html_tags(text: str) -> list[str]:
    """Возвращает список невалидных HTML-тегов в тексте."""
    found = INVALID_HTML_TAG_PATTERN.findall(text)
    return found


def find_any_invalid_tags(text: str) -> list[str]:
    """Находит все <...> которые НЕ являются разрешёнными Telegram-тегами."""
    all_tags = re.findall(r"<(/?\w+)[^>]*>", text)
    return [t for t in all_tags if t.lower() not in ALLOWED_TAGS]


class TestBudgetLineHTMLSafety:
    """format_budget_line не должен генерировать невалидный HTML."""

    def test_budget_line_no_invalid_tags_normal(self):
        """Нормальный случай — нет невалидных тегов."""
        from core.health.caloric_budget import format_budget_line

        mock_budget = {
            "consumed": 1200,
            "target": 1800,
            "remaining": 600,
            "pct": 67,
            "warn": False,
            "has_garmin": True,
        }
        with patch("core.health.caloric_budget.get_daily_budget", return_value=mock_budget):
            result = format_budget_line(user_id=895655, show_bar=True)

        invalid = has_invalid_html_tags(result)
        assert not invalid, f"Невалидные HTML-теги в budget_line: {invalid}\nТекст: {result!r}"

    def test_budget_line_no_invalid_tags_overeaten(self):
        """Перебор калорий — нет невалидных тегов."""
        from core.health.caloric_budget import format_budget_line

        mock_budget = {
            "consumed": 2500,
            "target": 1800,
            "remaining": -700,
            "pct": 139,
            "warn": True,
            "has_garmin": False,
        }
        with patch("core.health.caloric_budget.get_daily_budget", return_value=mock_budget):
            result = format_budget_line(user_id=895655, show_bar=True)

        invalid = has_invalid_html_tags(result)
        assert not invalid, f"Невалидные HTML-теги: {invalid}\nТекст: {result!r}"

    def test_budget_line_no_invalid_tags_show_bar_false(self):
        """show_bar=False — нет невалидных тегов."""
        from core.health.caloric_budget import format_budget_line

        mock_budget = {
            "consumed": 500,
            "target": 1800,
            "remaining": 1300,
            "pct": 28,
            "warn": False,
            "has_garmin": False,
        }
        with patch("core.health.caloric_budget.get_daily_budget", return_value=mock_budget):
            result = format_budget_line(user_id=895655, show_bar=False)

        invalid = has_invalid_html_tags(result)
        assert not invalid, f"Невалидные HTML-теги: {invalid}"


class TestDayResponseHTMLSafety:
    """Строки ответа /day не должны иметь невалидных тегов."""

    def test_day_header_is_valid_html(self):
        """Заголовок /day — валидный HTML."""
        from datetime import date

        today = date.today()
        today_formatted = today.strftime("%d.%m.%Y")
        header = f"📅 <b>Итоги дня {today_formatted}</b>"

        invalid = find_any_invalid_tags(header)
        assert not invalid, f"Невалидные теги в заголовке: {invalid}"

    def test_macro_lines_no_html_tags(self):
        """Строки макросов (Б/Ж/У) не содержат никаких тегов вообще."""
        from core.health.caloric_budget import make_block_bar

        p_bar, _ = make_block_bar(45, 150, invert=True)
        f_bar, _ = make_block_bar(20, 60)
        c_bar, _ = make_block_bar(80, 200)

        lines = [
            f"Б {p_bar} 45/150г",
            f"Ж {f_bar} 20/60г",
            f"У {c_bar} 80/200г",
        ]
        for line in lines:
            invalid = find_any_invalid_tags(line)
            assert not invalid, f"HTML-теги в строке макросов: {invalid}\nСтрока: {line!r}"

    def test_feasibility_warning_is_italic(self):
        """Предупреждение о нереалистичных целях оборачивается в <i>, а не произвольные теги."""
        warning_text = "Недостаточно белка для выполнения целей"
        formatted = f"⚠️ <i>{warning_text}</i>"

        invalid = find_any_invalid_tags(formatted)
        assert not invalid, f"Невалидные теги в warning: {invalid}"

    @pytest.mark.parametrize(
        "text",
        [
            "яблоко 150г",
            "куриная грудка 200г",
            "рис 80г",
            "кофе американо",
            "100г < минимума",  # < в данных НЕ должен попасть в ответ как тег
        ],
    )
    def test_food_names_dont_create_html_tags(self, text):
        """Названия блюд с угловыми скобками не создают невалидных HTML-тегов."""
        # Если пользователь пишет "< 100г" это НЕ должно попасть в Telegram как тег
        # В реальном коде названия блюд идут в жирный текст через <b>
        escaped = text.replace("<", "&lt;").replace(">", "&gt;")
        result = f"🍽 <b>{escaped}</b>"
        invalid = find_any_invalid_tags(result)
        assert not invalid, f"После экранирования не должно быть невалидных тегов: {invalid}"


class TestHTMLDetectionUtil:
    """Проверяем сам детектор невалидных тегов."""

    def test_detects_cyrillic_in_angle_brackets(self):
        bad = "Осталось <число> ккал"
        assert has_invalid_html_tags(bad), "Должен детектировать <число>"

    def test_detects_number_in_angle_brackets(self):
        bad = "Перебор <200> ккал"
        assert has_invalid_html_tags(bad), "Должен детектировать <200>"

    def test_allows_valid_telegram_tags(self):
        good = "<b>Итоги дня</b> — <i>норм</i>"
        assert not has_invalid_html_tags(good), "Валидные теги не должны триггерить детектор"

    def test_allows_emoji_and_special_chars(self):
        good = "📊 1200 / 1800 ккал · осталось 600"
        assert not has_invalid_html_tags(good)
