"""«Съел половину этого салата» + список ингредиентов: деление детерминированное (14.10.2026)."""

from core.food.nutrition import process_llm_food_data
from core.llm.models import FoodData

DESCRIPTION = """Ужин:
117 г огурца
103 г моркови
275 г капусты
180 г творога 5% жирности
20 г семечек подсолнечника
20 г тыквенных семечек
143 г томатов
66 г оливок
9 г оливкового масла
20 г выдержанного пряного сыра

Съел половину этого салата, остальное доки потом"""

_ITEMS = [
    ("Огурец", 117, 18, 1, 0, 3),
    ("Морковь", 103, 42, 1, 0, 10),
    ("Капуста", 275, 69, 4, 0, 16),
    ("Творог 5%", 180, 218, 31, 9, 5),
    ("Семечки подсолнечника", 20, 117, 4, 10, 4),
    ("Тыквенные семечки", 20, 112, 6, 10, 2),
    ("Томаты", 143, 26, 1, 0, 6),
    ("Оливки", 66, 76, 0, 7, 0),
    ("Оливковое масло", 9, 80, 0, 9, 0),
    ("Сыр выдержанный пряный", 20, 76, 5, 6, 0),
]


def _llm(fraction=None):
    data = {
        "dish_name": "Овощной салат с творогом (съедена половина)",
        "items": [
            {"name": n, "weight": w, "calories": c, "protein": p, "fats": f, "carbs": u, "fiber": 0}
            for n, w, c, p, f, u in _ITEMS
        ],
    }
    if fraction is not None:
        data["eaten_fraction"] = fraction
    return {"type": "food", "data": data}


def test_olives_keep_own_weight_not_oil_weight():
    items, _ = process_llm_food_data(_llm(), DESCRIPTION)
    by_name = {i["product"]: i for i in items}
    assert by_name["Оливки"]["weight_g"] == 66
    assert by_name["Оливковое масло"]["weight_g"] == 9


def test_eaten_fraction_halves_every_item_and_totals():
    full_items, full_totals = process_llm_food_data(_llm(), DESCRIPTION)
    items, totals = process_llm_food_data(_llm(0.5), DESCRIPTION)
    assert len(items) == len(full_items)
    for half, full in zip(items, full_items):
        assert half["weight_g"] == round(full["weight_g"] * 0.5, 1)
        assert abs(half["calories"] - full["calories"] * 0.5) <= 0.1
    assert abs(totals["calories"] - full_totals["calories"] * 0.5) <= 1
    assert abs(totals["protein"] - full_totals["protein"] * 0.5) <= 1


def test_no_fraction_leaves_totals_untouched():
    _, totals = process_llm_food_data(_llm(), DESCRIPTION)
    assert totals["calories"] > 800


def test_model_rejects_invalid_fraction():
    assert FoodData(eaten_fraction=0.5).eaten_fraction == 0.5
    for bad in (0, 1, 1.5, -0.2, "abc", None):
        assert FoodData(eaten_fraction=bad).eaten_fraction is None
