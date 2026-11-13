"""Вес блюда по фото = сумма компонентов, а не вес первого (13.11.2026).

Прод: «Запечённая курица с гречкой и свежими овощами» 408 ккал записалась как 120 г —
это вес одной курицы; «боул 100 г = 774 ккал» и т.п. (~70 записей).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

from handlers.photo import build_menu_meal_item, dish_weight_from_components, menu_data_from_router_data


def test_menu_data_weight_is_sum_of_components():
    data = {
        "dish_name": "Курица с гречкой",
        "items": [
            {"name": "Курица", "weight": 120, "calories": 200},
            {"name": "Гречка", "weight": 150, "calories": 165},
            {"name": "Овощи", "weight": 160, "calories": 43},
        ],
    }
    md = menu_data_from_router_data(data)
    assert md["weight"] == 430
    assert build_menu_meal_item(md)["weight_g"] == 430


def test_components_without_weight_are_skipped():
    assert dish_weight_from_components([{"weight": 100}, {"weight": None}, {"weight": "x"}], "weight") == 100
    assert dish_weight_from_components([{"weight": None}], "weight") is None
    assert dish_weight_from_components([], "weight") is None
