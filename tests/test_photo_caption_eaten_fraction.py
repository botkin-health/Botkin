"""Фото + подпись «съел примерно 35%» → доля доходит до деления (30.10.2026).

Путь фото с подписью: роутер → menu_data_from_router_data → menu_data в state
(Pydantic MenuData) → build_router_result_from_menu_data → process_llm_food_data.
Раньше eaten_fraction терялся на каждом из первых трёх шагов, и в превью шёл итог
всего стола: 1887 ккал вместо ~660. Тест идёт через state, как бот: первый фикс
(30.10) обходил state и пропустил, что MenuData выкидывает незнакомые поля.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

from core.food.nutrition import process_llm_food_data
from handlers.photo import build_router_result_from_menu_data, menu_data_from_router_data
from services.state_helpers import create_photo_state

CAPTION = "ужин. из этой кучи японских суши и сашими съел примерно 35%"

# Компоненты ровно из лога прода (сумма 1887 ккал)
_ITEMS = [
    ("Роллы ассорти", 480, 840, 30, 24, 123),
    ("Сашими из тунца", 120, 144, 31, 1, 0),
    ("Нигири с лососем", 105, 170, 10, 4, 24),
    ("Нигири с тунцом", 70, 100, 10, 1, 14),
    ("Гункан с авокадо", 120, 230, 5, 10, 30),
    ("Поке с тунцом и авокадо", 250, 370, 24, 20, 22),
    ("Огурец", 50, 8, 0, 0, 2),
    ("Имбирь маринованный и соус", 40, 25, 1, 0, 5),
]


def _router_data(fraction=0.35, with_total=False):
    items = [
        {"name": n, "weight": w, "calories": c, "protein": p, "fats": f, "carbs": u} for n, w, c, p, f, u in _ITEMS
    ]
    data = {"dish_name": "Суши, роллы, сашими и поке (съедена примерно треть: 35%)", "items": items}
    if with_total:
        data["total_nutrition"] = {"calories": 1887, "protein": 111, "fats": 60, "carbs": 220}
    if fraction is not None:
        data["eaten_fraction"] = fraction
    return data


def _totals(router_data):
    menu_data = menu_data_from_router_data(router_data)
    state = create_photo_state(user_id="1", photo_paths=[], photo_file_ids=[], caption=CAPTION, menu_data=menu_data)
    menu_data = state.data["menu_data"]
    result = build_router_result_from_menu_data(menu_data, caption=CAPTION)
    _, totals = process_llm_food_data(result, CAPTION)
    return totals


def test_fraction_scales_photo_with_caption():
    assert abs(_totals(_router_data()).get("calories") - 1887 * 0.35) <= 1


def test_fraction_scales_when_router_gives_total():
    # Итог роутера якорит items (totals_anchor=card), доля применяется поверх.
    assert abs(_totals(_router_data(with_total=True)).get("calories") - 1887 * 0.35) <= 1


def test_no_fraction_keeps_full_total():
    assert abs(_totals(_router_data(fraction=None)).get("calories") - 1887) <= 1


def test_empty_router_data_gives_none():
    assert menu_data_from_router_data({"dish_name": "X"}) is None
