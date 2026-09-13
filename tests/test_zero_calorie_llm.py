"""Явный 0 ккал от LLM (вода, чай, американо) — валидное значение, не «нет данных».

Регрессия e2e 13.09.2026: Sonnet 5 честно вернул «Вода, 200 г, 0 ккал», а
process_llm_food_data ушёл в поиск по базе и дефолтную оценку → 200 ккал Б20 Ж10 У30.
"""

from core.food.nutrition import process_llm_food_data


def _llm(items):
    return {"type": "food", "data": {"dish_name": "x", "meal_type": "snack", "items": items, "total_nutrition": {}}}


def test_water_with_explicit_zero_stays_zero():
    items, totals = process_llm_food_data(
        _llm(
            [
                {
                    "name": "Вода",
                    "weight": 200,
                    "quantity": "1 стакан",
                    "calories": 0,
                    "protein": 0,
                    "fats": 0,
                    "carbs": 0,
                    "fiber": 0,
                }
            ]
        )
    )
    assert len(items) == 1
    assert items[0]["calories"] == 0
    assert items[0]["protein"] == 0 and items[0]["fats"] == 0 and items[0]["carbs"] == 0
    assert items[0]["source"] == "llm_router_zero"
    assert totals["calories"] == 0


def test_black_tea_zero_without_diet_marker():
    items, _ = process_llm_food_data(
        _llm(
            [
                {
                    "name": "Чай ромашковый",
                    "weight": 250,
                    "quantity": "1 стакан",
                    "calories": 0,
                    "protein": 0,
                    "fats": 0,
                    "carbs": 0,
                }
            ]
        )
    )
    assert items[0]["calories"] == 0


def test_missing_calories_still_falls_back_to_estimate():
    """None (модель не дала калорий) — по-прежнему оценка, а не 0."""
    items, _ = process_llm_food_data(
        _llm(
            [
                {
                    "name": "Борщ",
                    "weight": 300,
                    "quantity": "1 тарелка",
                    "calories": None,
                    "protein": None,
                    "fats": None,
                    "carbs": None,
                }
            ]
        )
    )
    assert items[0]["calories"] > 0


def test_zero_calories_with_nonzero_macros_is_not_trusted():
    """0 ккал, но БЖУ ненулевые — противоречие, оставляем прежнюю логику (пересчёт)."""
    items, _ = process_llm_food_data(
        _llm(
            [
                {
                    "name": "Творог 5%",
                    "weight": 100,
                    "quantity": "пачка",
                    "calories": 0,
                    "protein": 16,
                    "fats": 5,
                    "carbs": 3,
                }
            ]
        )
    )
    assert items[0]["calories"] > 0
