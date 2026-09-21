"""save_meal_to_db должна отдавать id записи nutrition_log, а не bool (#258).

Вызывающий код (handle_meal_confirmation) использует id для food_interactions.nutrition_log_id.
"""

from unittest.mock import patch

from database.models import NutritionLog
from helpers.db_save import save_meal_to_db


def test_returns_created_nutrition_log_id(test_db):
    meal_data = {
        "meal_items": [{"product": "Банан", "weight_g": 120, "calories": 110}],
        "meal_totals": {"calories": 110, "protein": 1, "fats": 0, "carbs": 28},
        "meal_time": "09:00",
    }

    with patch("helpers.db_save.SessionLocal", return_value=test_db):
        result = save_meal_to_db(meal_data, "Завтрак", user_id=42)

    assert isinstance(result, int)
    row = test_db.query(NutritionLog).filter(NutritionLog.id == result).one()
    assert row.user_id == 42
    assert row.meal_name == "Завтрак"


def test_saves_status_plan_when_is_plan_true(test_db):
    """#407: meal_data с is_plan=True должен сохраняться со status='plan'."""
    meal_data = {
        "meal_items": [{"product": "Творог", "weight_g": 200, "calories": 200}],
        "meal_totals": {"calories": 200, "protein": 20, "fats": 5, "carbs": 5},
        "meal_time": "09:00",
        "is_plan": True,
    }

    with patch("helpers.db_save.SessionLocal", return_value=test_db):
        result = save_meal_to_db(meal_data, "Завтрак", user_id=42)

    row = test_db.query(NutritionLog).filter(NutritionLog.id == result).one()
    assert row.status == "plan"


def test_saves_status_eaten_when_is_plan_absent(test_db):
    """Без is_plan (обычный флоу) status остаётся 'eaten' по умолчанию."""
    meal_data = {
        "meal_items": [{"product": "Банан", "weight_g": 120, "calories": 110}],
        "meal_totals": {"calories": 110, "protein": 1, "fats": 0, "carbs": 28},
        "meal_time": "09:00",
    }

    with patch("helpers.db_save.SessionLocal", return_value=test_db):
        result = save_meal_to_db(meal_data, "Завтрак", user_id=42)

    row = test_db.query(NutritionLog).filter(NutritionLog.id == result).one()
    assert row.status == "eaten"


def test_returns_none_on_db_error():
    with patch("helpers.db_save.SessionLocal", side_effect=RuntimeError("db down")):
        result = save_meal_to_db({"meal_items": [], "meal_totals": {}}, "Обед", user_id=1)

    assert result is None


def test_returns_none_when_meal_items_key_missing():
    """Опечатка/отсутствие ключа meal_items (#256-класс бага) должна быть

    видна в логах как ValidationError, а не тихо сохранять пустой приём пищи.
    Проверяем что SessionLocal вообще не вызывается — валидация падает раньше,
    чем открывается сессия БД.
    """
    with patch("helpers.db_save.SessionLocal") as mock_session:
        result = save_meal_to_db({"meal_item": [], "meal_totals": {}}, "Обед", user_id=1)

    assert result is None
    mock_session.assert_not_called()


def test_duplicate_meal_returns_existing_id_instead_of_crashing(test_db):
    """Повторная отправка того же блюда не должна ронять сохранение.

    Прецедент 20.09.2026: пользователь отправил «Обед: Панини…» дважды за 15 секунд —
    вторая попытка упёрлась в уникальный ключ
    (user_id, date, meal_time, meal_name) и дала необработанный
    psycopg2.errors.UniqueViolation в helpers/db_save.py:204. Это были
    единственные две ошибки бота за ту неделю. Теперь ловим IntegrityError,
    откатываем транзакцию и возвращаем id уже существующей записи.
    """
    meal_data = {
        "meal_items": [{"product": "Панини", "weight_g": 250, "calories": 750}],
        "meal_totals": {"calories": 750, "protein": 24, "fats": 35, "carbs": 80},
        "meal_time": "23:02",
    }

    with patch("helpers.db_save.SessionLocal", return_value=test_db):
        first = save_meal_to_db(meal_data, "Обед: Панини", user_id=42)
        second = save_meal_to_db(meal_data, "Обед: Панини", user_id=42)

    assert first is not None
    assert second == first, "второй вызов обязан вернуть ту же запись, а не None"

    rows = (
        test_db.query(NutritionLog).filter(NutritionLog.user_id == 42, NutritionLog.meal_name == "Обед: Панини").all()
    )
    assert len(rows) == 1, "дубль в БД появляться не должен"
