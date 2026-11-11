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


def test_inconsistent_stated_total_is_not_anchor():
    # 11.11.2026: фото тарелки, LLM дала итог 218 ккал при БЖУ компонентов на ~385 ккал.
    # Раньше компоненты ужимались ×0.57 (курица 100 г = 94 ккал), а БЖУ в итогах оставались от 385.
    items = [
        {"name": "Гречка варёная", "weight": 150, "calories": 165, "protein": 6, "fats": 1.5, "carbs": 32},
        {
            "name": "Курица варёная/запечённая (мясо)",
            "weight": 100,
            "calories": 165,
            "protein": 25,
            "fats": 7,
            "carbs": 0,
        },
        {"name": "Болгарский перец", "weight": 80, "calories": 22, "protein": 1, "fats": 0.2, "carbs": 4.5},
        {"name": "Огурец", "weight": 100, "calories": 15, "protein": 0.7, "fats": 0.1, "carbs": 3},
        {"name": "Помидоры черри", "weight": 80, "calories": 16, "protein": 0.7, "fats": 0.2, "carbs": 3.2},
    ]
    data = {
        "type": "food",
        "data": {
            "dish_name": "Гречка с курицей",
            "items": items,
            "total_nutrition": {"calories": 218, "protein": 33.4, "fats": 9.0, "carbs": 42.7},
            "totals_anchor": "card",
        },
    }
    out_items, totals = process_llm_food_data(data, description="")
    assert totals["calories"] == pytest.approx(383, abs=2)
    assert totals["protein"] == pytest.approx(sum(i["protein"] for i in out_items), abs=0.5)
    assert out_items[1]["calories"] == pytest.approx(165, abs=1)
