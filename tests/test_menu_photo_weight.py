"""Tests for weight propagation in handle_menu_photo.

Regression: weight_g was hardcoded to None in telegram-bot/handlers/photo.py,
so 84 meal records across 3.5 months got amount=0 in nutrition_log.items
despite LLM correctly extracting weight from receipts/menus.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

from handlers.photo import build_menu_meal_item


class TestBuildMenuMealItem:
    """build_menu_meal_item: extract canonical meal item from menu_data."""

    def test_weight_from_menu_data(self):
        """When LLM returned weight — use it."""
        menu_data = {
            "dish_name": "Гриль-чиз с тунцом",
            "calories": 439,
            "protein": 19,
            "fats": 22,
            "carbs": 42,
            "weight": 165,  # LLM extracted from receipt
        }
        item = build_menu_meal_item(menu_data)
        assert item["weight_g"] == 165
        assert item["weight_source"] == "llm"

    def test_weight_grams_key_alias(self):
        """LLM can return weight_grams instead of weight — both should work."""
        menu_data = {
            "dish_name": "Салат",
            "calories": 200,
            "protein": 5,
            "fats": 10,
            "carbs": 20,
            "weight_grams": 250,
        }
        item = build_menu_meal_item(menu_data)
        assert item["weight_g"] == 250

    def test_default_to_100g_when_missing(self):
        """If LLM didn't return weight (None or missing) — fallback to 100g."""
        menu_data = {
            "dish_name": "Блюдо",
            "calories": 300,
            "protein": 10,
            "fats": 15,
            "carbs": 30,
            # no weight/weight_grams key
        }
        item = build_menu_meal_item(menu_data)
        assert item["weight_g"] == 100
        assert item["weight_source"] == "default_100g"

    def test_default_to_100g_when_zero(self):
        """If LLM returned 0 (receipt screenshots) — fallback to 100g."""
        menu_data = {
            "dish_name": "Блюдо",
            "calories": 300,
            "protein": 10,
            "fats": 15,
            "carbs": 30,
            "weight": 0,
        }
        item = build_menu_meal_item(menu_data)
        assert item["weight_g"] == 100
        assert item["weight_source"] == "default_100g"

    def test_default_to_100g_when_none(self):
        """Explicit None must trigger fallback."""
        menu_data = {
            "dish_name": "Блюдо",
            "calories": 300,
            "protein": 10,
            "fats": 15,
            "carbs": 30,
            "weight": None,
        }
        item = build_menu_meal_item(menu_data)
        assert item["weight_g"] == 100

    def test_preserves_calories_and_macros(self):
        """Whatever weight resolution does — KBZHU stay untouched."""
        menu_data = {
            "dish_name": "Блюдо",
            "calories": 439,
            "protein": 19,
            "fats": 22,
            "carbs": 42,
            "weight": 0,  # zero triggers fallback
        }
        item = build_menu_meal_item(menu_data)
        assert item["calories"] == 439
        assert item["protein"] == 19
        assert item["fats"] == 22
        assert item["carbs"] == 42

    def test_dish_name_propagates(self):
        menu_data = {"dish_name": "Тестовое блюдо", "calories": 100, "weight": 150}
        item = build_menu_meal_item(menu_data)
        assert item["product"] == "Тестовое блюдо"

    def test_source_marker(self):
        menu_data = {"dish_name": "X", "calories": 100, "weight": 100}
        item = build_menu_meal_item(menu_data)
        assert item["source"] == "menu_ocr"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
