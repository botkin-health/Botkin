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


def test_returns_none_on_db_error():
    with patch("helpers.db_save.SessionLocal", side_effect=RuntimeError("db down")):
        result = save_meal_to_db({"meal_items": [], "meal_totals": {}}, "Обед", user_id=1)

    assert result is None
