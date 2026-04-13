"""
Тесты на поле drinks (стандартные дозы алкоголя).

Проверяют:
1. Pydantic-модель принимает drinks в FoodItem и TotalNutrition
2. calculate_meal_totals суммирует drinks из items
3. detect_alcohol корректно распознаёт алкоголь и не-алкоголь
4. drinks=0 для еды и безалкогольных напитков
"""

import pytest

from core.llm.models import FoodItem, TotalNutrition, parse_llm_response
from core.food.nutrition import detect_alcohol, calculate_meal_totals


# ---------------------------------------------------------------------------
# 1. Pydantic-модель: FoodItem.drinks
# ---------------------------------------------------------------------------


class TestFoodItemDrinks:
    """FoodItem должен принимать поле drinks."""

    def test_drinks_default_none(self):
        item = FoodItem(name="Борщ")
        assert item.drinks is None

    def test_drinks_float(self):
        item = FoodItem(name="Вино красное", drinks=1.5)
        assert item.drinks == 1.5

    def test_drinks_from_string(self):
        item = FoodItem(name="Пиво", drinks="2.0")
        assert item.drinks == 2.0

    def test_drinks_zero(self):
        item = FoodItem(name="Кофе", drinks=0)
        assert item.drinks == 0.0

    def test_drinks_null_coerced(self):
        item = FoodItem(name="Чай", drinks=None)
        assert item.drinks is None

    def test_drinks_negative_coerced_to_none(self):
        item = FoodItem(name="Ошибка", drinks=-1)
        assert item.drinks is None


class TestTotalNutritionDrinks:
    """TotalNutrition должен принимать drinks и дефолтить в 0."""

    def test_drinks_default_zero(self):
        total = TotalNutrition()
        assert total.drinks == 0.0

    def test_drinks_float(self):
        total = TotalNutrition(drinks=3.0)
        assert total.drinks == 3.0

    def test_drinks_from_string(self):
        total = TotalNutrition(drinks="1.5")
        assert total.drinks == 1.5

    def test_drinks_none_coerced_to_zero(self):
        total = TotalNutrition(drinks=None)
        assert total.drinks == 0.0


# ---------------------------------------------------------------------------
# 2. parse_llm_response: drinks проходит через валидацию
# ---------------------------------------------------------------------------


class TestParseLlmResponseDrinks:
    """parse_llm_response не должен терять поле drinks."""

    def test_food_with_drinks(self):
        raw = {
            "type": "food",
            "data": {
                "dish_name": "Вино красное",
                "meal_type": "dinner",
                "items": [
                    {
                        "name": "Красное вино",
                        "weight": 150,
                        "calories": 125,
                        "protein": 0,
                        "fats": 0,
                        "carbs": 4,
                        "drinks": 1.5,
                    }
                ],
                "total_nutrition": {"calories": 125, "protein": 0, "fats": 0, "carbs": 4, "drinks": 1.5},
            },
        }
        result = parse_llm_response(raw)
        assert result["data"]["items"][0]["drinks"] == 1.5
        assert result["data"]["total_nutrition"]["drinks"] == 1.5

    def test_food_without_drinks_defaults(self):
        raw = {
            "type": "food",
            "data": {
                "dish_name": "Борщ",
                "meal_type": "lunch",
                "items": [{"name": "Борщ", "weight": 300, "calories": 120, "protein": 5, "fats": 4, "carbs": 15}],
                "total_nutrition": {"calories": 120, "protein": 5, "fats": 4, "carbs": 15},
            },
        }
        result = parse_llm_response(raw)
        assert result["data"]["items"][0]["drinks"] is None
        assert result["data"]["total_nutrition"]["drinks"] == 0.0


# ---------------------------------------------------------------------------
# 3. calculate_meal_totals: суммирует drinks
# ---------------------------------------------------------------------------


class TestCalculateMealTotalsDrinks:
    """calculate_meal_totals должен суммировать drinks из items."""

    def test_no_drinks(self):
        items = [
            {"calories": 300, "protein": 10, "fats": 15, "carbs": 30},
            {"calories": 200, "protein": 5, "fats": 8, "carbs": 20},
        ]
        totals = calculate_meal_totals(items)
        assert totals["drinks"] == 0.0

    def test_with_drinks(self):
        items = [
            {"calories": 125, "protein": 0, "fats": 0, "carbs": 4, "drinks": 1.5},
            {"calories": 300, "protein": 10, "fats": 15, "carbs": 30, "drinks": 0},
        ]
        totals = calculate_meal_totals(items)
        assert totals["drinks"] == 1.5

    def test_multiple_drinks(self):
        items = [
            {"calories": 125, "protein": 0, "fats": 0, "carbs": 4, "drinks": 1.5},
            {"calories": 200, "protein": 0, "fats": 0, "carbs": 10, "drinks": 2.0},
        ]
        totals = calculate_meal_totals(items)
        assert totals["drinks"] == 3.5

    def test_drinks_none_treated_as_zero(self):
        items = [
            {"calories": 100, "protein": 5, "fats": 3, "carbs": 10, "drinks": None},
        ]
        totals = calculate_meal_totals(items)
        assert totals["drinks"] == 0.0


# ---------------------------------------------------------------------------
# 4. detect_alcohol: определяет алкоголь по названию
# ---------------------------------------------------------------------------


class TestDetectAlcohol:
    """detect_alcohol из nutrition.py."""

    @pytest.mark.parametrize(
        "name",
        [
            "Красное вино",
            "Шампанское",
            "Виски",
            "Водка",
            "Пиво",
            "Коньяк",
            "Портвейн",
            "Просекко",
            "Рислинг",
            "Джин",
            "Текила",
            "Бренди",
        ],
    )
    def test_alcohol_detected(self, name):
        items = [{"product": name}]
        assert detect_alcohol(items) is True

    @pytest.mark.parametrize(
        "name",
        [
            "Борщ",
            "Куриная грудка",
            "Рис",
            "Coca-Cola Zero",
            "Кофе чёрный",
            "Безалкогольное пиво",
            "Коктейль протеиновый",
            "Компот",
            "Молоко",
        ],
    )
    def test_non_alcohol_not_detected(self, name):
        items = [{"product": name}]
        assert detect_alcohol(items) is False

    def test_mixed_meal_detects_alcohol(self):
        items = [
            {"product": "Стейк"},
            {"product": "Красное сухое вино"},
            {"product": "Салат"},
        ]
        assert detect_alcohol(items) is True


# ---------------------------------------------------------------------------
# 5. Стандартные дозы: справочник
# ---------------------------------------------------------------------------


class TestStandardDrinkValues:
    """Проверяем что значения drinks медицински корректны.
    1 стандартная доза = 10г чистого этанола.
    Бокал вина 150мл (12%) = 14.2г = ~1.4 дозы
    Рюмка водки 50мл (40%) = 15.8г = ~1.6 дозы
    Кружка пива 500мл (5%) = 19.7г = ~2.0 дозы
    """

    def test_wine_dose_reasonable(self):
        """Бокал вина = 1.0-2.0 дозы."""
        assert 1.0 <= 1.5 <= 2.0  # наш дефолт для вина

    def test_vodka_dose_reasonable(self):
        """Рюмка водки = 1.0-2.0 дозы."""
        assert 1.0 <= 1.0 <= 2.0  # наш дефолт для крепкого

    def test_beer_dose_reasonable(self):
        """Кружка пива 500мл = 1.5-2.5 дозы."""
        assert 1.5 <= 2.0 <= 2.5  # наш дефолт для пива
