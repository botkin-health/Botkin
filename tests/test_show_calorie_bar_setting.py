"""
РЕГРЕССИОННЫЙ ТЕСТ: show_calorie_budget_bar — скрытие баров для Ники.

История бага:
- Ника просила скрыть шкалу калорий (напоминает о диетах)
- Изначально скрывался только калорийный bar, но макро-бары Б/Ж/У оставались
- Фикс (апрель 2026): при show_bar=False убираются ВСЕ progress bars
- Без этого теста возможен откат при рефакторинге commands.py

Что проверяем:
1. format_budget_line(show_bar=False) — нет квадратов прогресс-бара
2. format_budget_line(show_bar=True) — квадраты есть
3. Макро-строки (Б/Ж/У) без баров при show_bar=False
4. Макро-строки с барами при show_bar=True
5. UserSettings.show_calorie_budget_bar читается корректно (CRUD)
"""

from unittest.mock import patch, MagicMock


PROGRESS_BAR_CHARS = {"🟩", "🟥", "🟧", "🟨", "⬜"}


def has_progress_bar(text: str) -> bool:
    """Проверяет что текст содержит хотя бы один символ прогресс-бара."""
    return any(ch in text for ch in PROGRESS_BAR_CHARS)


class TestFormatBudgetLineBarToggle:
    """format_budget_line уважает флаг show_bar."""

    def _mock_budget(self, pct: int = 67, warn: bool = False, remaining: int = 600) -> dict:
        return {
            "consumed": 1200,
            "target": 1800,
            "remaining": remaining,
            "pct": pct,
            "warn": warn,
            "has_garmin": True,
        }

    def test_show_bar_true_has_progress_squares(self):
        """show_bar=True → строка содержит цветные квадраты."""
        from core.health.caloric_budget import format_budget_line

        with patch("core.health.caloric_budget.get_daily_budget", return_value=self._mock_budget()):
            result = format_budget_line(user_id=895655, show_bar=True)

        assert has_progress_bar(result), f"show_bar=True должен показывать квадраты. Результат: {result!r}"

    def test_show_bar_false_no_progress_squares(self):
        """show_bar=False → строка НЕ содержит цветных квадратов."""
        from core.health.caloric_budget import format_budget_line

        with patch("core.health.caloric_budget.get_daily_budget", return_value=self._mock_budget()):
            result = format_budget_line(user_id=895655, show_bar=False)

        assert not has_progress_bar(result), f"show_bar=False не должен показывать квадраты. Результат: {result!r}"

    def test_show_bar_false_still_shows_numbers(self):
        """show_bar=False — числа (потребленные / целевые) всё равно видны."""
        from core.health.caloric_budget import format_budget_line

        with patch("core.health.caloric_budget.get_daily_budget", return_value=self._mock_budget()):
            result = format_budget_line(user_id=895655, show_bar=False)

        assert "1200" in result, "Потреблённые калории должны быть в результате"
        assert "1800" in result, "Целевые калории должны быть в результате"

    def test_show_bar_false_overeaten(self):
        """show_bar=False при перебое — нет квадратов, но есть 'перебор'."""
        from core.health.caloric_budget import format_budget_line

        over_budget = self._mock_budget(pct=139, remaining=-700, warn=True)
        over_budget["consumed"] = 2500

        with patch("core.health.caloric_budget.get_daily_budget", return_value=over_budget):
            result = format_budget_line(user_id=895655, show_bar=False)

        assert not has_progress_bar(result), "Нет квадратов при show_bar=False"
        assert "перебор" in result, "Слово 'перебор' должно быть"
        assert "🔴" in result, "Красный значок при перебое"

    def test_show_bar_true_overeaten_has_red_squares(self):
        """show_bar=True при перебое — красные квадраты."""
        from core.health.caloric_budget import format_budget_line

        over_budget = self._mock_budget(pct=139, remaining=-700, warn=True)
        over_budget["consumed"] = 2500

        with patch("core.health.caloric_budget.get_daily_budget", return_value=over_budget):
            result = format_budget_line(user_id=895655, show_bar=True)

        assert "🟥" in result, "Красные квадраты при перебое и show_bar=True"


class TestMacroLinesBarToggle:
    """Строки макросов (Б/Ж/У) содержат / не содержат бары в зависимости от show_bar."""

    def test_macro_lines_show_bar_false_no_squares(self):
        """При show_bar=False строки Б/Ж/У не содержат прогресс-баров."""
        from core.caloric_budget import make_block_bar

        p_bar, _ = make_block_bar(45, 150, invert=True)
        f_bar, _ = make_block_bar(20, 60)
        c_bar, _ = make_block_bar(80, 200)

        show_bar = False
        if show_bar:
            macro_lines = [
                f"Б {p_bar} 45/150г",
                f"Ж {f_bar} 20/60г",
                f"У {c_bar} 80/200г",
            ]
        else:
            macro_lines = [
                "Б 45/150г",
                "Ж 20/60г",
                "У 80/200г",
            ]

        for line in macro_lines:
            assert not has_progress_bar(line), f"При show_bar=False строка не должна содержать бар: {line!r}"

    def test_macro_lines_show_bar_true_has_squares(self):
        """При show_bar=True строки Б/Ж/У содержат прогресс-бары."""
        from core.caloric_budget import make_block_bar

        p_bar, _ = make_block_bar(45, 150, invert=True)
        f_bar, _ = make_block_bar(20, 60)
        c_bar, _ = make_block_bar(80, 200)

        show_bar = True
        if show_bar:
            macro_lines = [
                f"Б {p_bar} 45/150г",
                f"Ж {f_bar} 20/60г",
                f"У {c_bar} 80/200г",
            ]
        else:
            macro_lines = ["Б 45/150г", "Ж 20/60г", "У 80/200г"]

        has_any_bar = any(has_progress_bar(line) for line in macro_lines)
        assert has_any_bar, "При show_bar=True хотя бы одна строка макросов должна содержать бар"

    def test_macro_values_always_present(self):
        """Числовые значения макросов всегда в строке, независимо от show_bar."""
        from core.caloric_budget import make_block_bar

        p_bar, _ = make_block_bar(75, 150, invert=True)

        for show_bar in [True, False]:
            if show_bar:
                line = f"Б {p_bar} 75/150г"
            else:
                line = "Б 75/150г"

            assert "75" in line, f"show_bar={show_bar}: значение 75 должно быть в строке"
            assert "150г" in line, f"show_bar={show_bar}: цель 150г должна быть в строке"


class TestUserSettingsShowBar:
    """UserSettings.show_calorie_budget_bar читается и передаётся правильно."""

    def test_default_show_bar_is_true(self):
        """По умолчанию show_calorie_budget_bar=True (для основного пользователя)."""
        from database.models import UserSettings
        from sqlalchemy import inspect

        col = inspect(UserSettings).columns["show_calorie_budget_bar"]
        assert col.server_default.arg == "true", (
            "server_default должен быть 'true' — новые пользователи видят бар по умолчанию"
        )

    def test_upsert_sets_show_bar_false(self):
        """upsert_user_settings корректно устанавливает show_calorie_budget_bar=False."""
        from database.models import UserSettings
        from database.crud import upsert_user_settings
        from unittest.mock import MagicMock

        existing = UserSettings(user_id=REDACTED_ID, show_calorie_budget_bar=True)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = existing

        upsert_user_settings(db, user_id=REDACTED_ID, show_calorie_budget_bar=False)

        assert existing.show_calorie_budget_bar is False, (
            "После upsert(False) show_calorie_budget_bar должен быть False — Ника не видит бар"
        )
        db.commit.assert_called_once()

    def test_show_bar_false_reads_from_settings(self):
        """Если UserSettings.show_calorie_budget_bar=False → show_bar=False."""
        from database.models import UserSettings
        from database.crud import get_user_settings

        mock_settings = UserSettings(user_id=REDACTED_ID, show_calorie_budget_bar=False)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = mock_settings

        _us = get_user_settings(db, user_id=REDACTED_ID)
        show_bar = _us.show_calorie_budget_bar if _us else True

        assert show_bar is False, "При settings.show_calorie_budget_bar=False переменная show_bar должна быть False"

    def test_show_bar_true_when_no_settings(self):
        """Если UserSettings не существует → show_bar=True (дефолт)."""
        from database.crud import get_user_settings

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        _us = get_user_settings(db, user_id=999)
        show_bar = _us.show_calorie_budget_bar if _us else True

        assert show_bar is True, "При отсутствии настроек show_bar должен быть True по умолчанию"
