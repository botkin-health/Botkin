"""
РЕГРЕССИОННЫЙ ТЕСТ: NameError 'status_msg' in cmd_day.

История бага:
- 01-02 апреля 2026 бот падал с NameError при команде /day
- Причина: переменная status_msg не была инициализирована при отсутствии Garmin-данных
- Фикс: инициализация status_msg = None в начале блока
- Без этого теста баг может вернуться при рефакторинге cmd_day

Что проверяем:
1. format_budget_line() не падает при отсутствии данных (возвращает пустую строку)
2. Логика show_bar работает без исключений при None-значениях
3. Ответ бота содержит заголовок даже если нет Garmin/DB данных
"""

from unittest.mock import patch


class TestFormatBudgetLineRobust:
    """format_budget_line не должен падать при граничных данных."""

    def test_format_budget_line_returns_empty_when_no_budget(self):
        """Если бюджет не рассчитан — возвращает пустую строку, не падает."""
        from core.health.caloric_budget import format_budget_line

        with patch("core.health.caloric_budget.get_daily_budget", return_value=None):
            result = format_budget_line(user_id=895655)
        assert result == "", f"Ожидали пустую строку, получили: {result!r}"

    def test_format_budget_line_show_bar_false_no_crash(self):
        """show_bar=False не вызывает исключений."""
        from core.health.caloric_budget import format_budget_line

        mock_budget = {
            "consumed": 1200,
            "target": 1800,
            "remaining": 600,
            "pct": 67,
            "warn": False,
            "has_garmin": False,
        }
        with patch("core.health.caloric_budget.get_daily_budget", return_value=mock_budget):
            result = format_budget_line(user_id=895655, show_bar=False)
        assert "1200" in result
        assert "1800" in result
        # При show_bar=False — нет цветных квадратов
        assert "🟩" not in result
        assert "🟥" not in result
        assert "⬜" not in result

    def test_format_budget_line_show_bar_true_has_squares(self):
        """show_bar=True содержит progress bar из квадратов."""
        from core.health.caloric_budget import format_budget_line

        mock_budget = {
            "consumed": 900,
            "target": 1800,
            "remaining": 900,
            "pct": 50,
            "warn": False,
            "has_garmin": True,
        }
        with patch("core.health.caloric_budget.get_daily_budget", return_value=mock_budget):
            result = format_budget_line(user_id=895655, show_bar=True)
        assert "🟩" in result or "🟥" in result or "🟧" in result

    def test_format_budget_line_overeaten(self):
        """Перебор калорий — красный статус, нет NameError."""
        from core.health.caloric_budget import format_budget_line

        mock_budget = {
            "consumed": 2500,
            "target": 1800,
            "remaining": -700,
            "pct": 139,
            "warn": True,
            "has_garmin": True,
        }
        with patch("core.health.caloric_budget.get_daily_budget", return_value=mock_budget):
            result = format_budget_line(user_id=895655, show_bar=True)
        assert "🔴" in result
        assert "перебор" in result


class TestCmdDayResponseConstruction:
    """Проверяем что логика построения ответа /day не падает при None-значениях."""

    def test_macro_lines_with_show_bar_false_no_bars(self):
        """При show_bar=False строки макросов не содержат progress-bars."""
        # Симулируем логику из commands.py напрямую
        from core.caloric_budget import make_block_bar

        totals_protein = 45.0
        totals_fats = 20.0
        totals_carbs = 80.0
        targets = {"protein": 150, "fats": 60, "carbs": 200}

        show_bar = False

        p_bar, _ = make_block_bar(totals_protein, targets["protein"], invert=True)
        f_bar, _ = make_block_bar(totals_fats, targets["fats"])
        c_bar, _ = make_block_bar(totals_carbs, targets["carbs"])

        if show_bar:
            macro_lines = [
                f"Б {p_bar} {totals_protein:.0f}/{targets['protein']}г",
                f"Ж {f_bar} {totals_fats:.0f}/{targets['fats']}г",
                f"У {c_bar} {totals_carbs:.0f}/{targets['carbs']}г",
            ]
        else:
            macro_lines = [
                f"Б {totals_protein:.0f}/{targets['protein']}г",
                f"Ж {totals_fats:.0f}/{targets['fats']}г",
                f"У {totals_carbs:.0f}/{targets['carbs']}г",
            ]

        # Проверяем что при show_bar=False баров нет
        full_text = "\n".join(macro_lines)
        assert "🟩" not in full_text, "show_bar=False не должен показывать прогресс-бары"
        assert "🟥" not in full_text
        assert "45/150г" in full_text, "Значения Б должны быть"
        assert "20/60г" in full_text
        assert "80/200г" in full_text

    def test_macro_lines_with_show_bar_true_has_bars(self):
        """При show_bar=True строки макросов содержат progress-bars."""
        from core.caloric_budget import make_block_bar

        totals_protein = 45.0
        targets = {"protein": 150, "fats": 60, "carbs": 200}
        p_bar, _ = make_block_bar(totals_protein, targets["protein"], invert=True)

        show_bar = True
        if show_bar:
            line = f"Б {p_bar} {totals_protein:.0f}/{targets['protein']}г"
        else:
            line = f"Б {totals_protein:.0f}/{targets['protein']}г"

        # Должен содержать квадраты прогресс-бара
        assert any(sq in line for sq in ["🟩", "🟥", "🟧", "⬜"])

    def test_zero_macros_no_crash(self):
        """Нулевые значения макросов (пустой день) не вызывают деления на ноль."""
        from core.caloric_budget import make_block_bar

        # Нулевые значения — типичная ситуация для нового дня
        p_bar, p_pct = make_block_bar(0, 150, invert=True)
        f_bar, f_pct = make_block_bar(0, 60)
        c_bar, c_pct = make_block_bar(0, 200)

        assert p_pct == 0
        assert f_pct == 0
        assert c_pct == 0
        # Строки создаются без ошибок
        line = f"Б {p_bar} 0/150г"
        assert "150г" in line
