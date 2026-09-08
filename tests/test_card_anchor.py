import pytest

from core.food.nutrition import process_llm_food_data

CARD_ITEMS = [
    {"name": "Курица", "weight": 300, "calories": 330, "protein": 62, "fats": 7, "carbs": 0},
    {"name": "Кускус", "weight": 60, "calories": 215, "protein": 7, "fats": 1, "carbs": 45},
    {"name": "Кабачок", "weight": 150, "calories": 27, "protein": 2, "fats": 0, "carbs": 5},
    {"name": "Масло", "weight": 25, "calories": 172, "protein": 0, "fats": 19, "carbs": 0},
]
TOTAL = {"calories": 564, "protein": 43, "fats": 21, "carbs": 50}


def _data(anchor):
    d = {"dish_name": "Стрипсы с кабачком", "items": [dict(i) for i in CARD_ITEMS], "total_nutrition": dict(TOTAL)}
    if anchor:
        d["totals_anchor"] = "card"
    return {"type": "food", "data": d}


def test_card_anchor_scales_multi_items_to_stated_total():
    items, totals = process_llm_food_data(_data(True), description="")
    assert totals["calories"] == pytest.approx(564, abs=1) and len(items) == 4
    raw_sum = sum(i["calories"] for i in CARD_ITEMS)
    assert items[0]["calories"] == pytest.approx(330 * 564 / raw_sum, abs=1) and items[0]["weight_g"] == 300


def test_without_anchor_multi_item_keeps_old_behaviour():
    _, totals = process_llm_food_data(_data(False), description="")
    assert totals["calories"] == pytest.approx(sum(i["calories"] for i in CARD_ITEMS), abs=2)


def test_anchor_single_item_still_uses_total():
    d = _data(True)
    d["data"]["items"] = [dict(CARD_ITEMS[0])]
    _, totals = process_llm_food_data(d, description="")
    assert totals["calories"] == pytest.approx(564, abs=1)
