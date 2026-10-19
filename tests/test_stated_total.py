"""Якорь на итог ккал, названный пользователем в тексте (#629).

Прецедент 19.10.2026: «…сэндвич Tunacado: тунцовый мусс, авокадо, помидор, хлеб, песто.
По данным сети 506 ккал, ~Б22 Ж27 У45» → бот разложил на компоненты и записал 518 ккал.
Названный итог — якорь: позиции масштабируются под него (тот же механизм, что #427 для карточек).
"""

import pytest

from core.food.nutrition import process_llm_food_data
from core.food.stated_total import extract_stated_totals

TUNACADO_TEXT = (
    "Joe & The Juice (Дубай), сэндвич Tunacado: тунцовый мусс, авокадо, помидор, "
    "классический хлеб, веганский песто. По данным сети 506 ккал, ~Б22 Ж27 У45\n\nЕл это в 18:00"
)
TUNACADO_ITEMS = [
    {"name": "Хлеб классический", "weight": 100, "calories": 250, "protein": 8, "fats": 3, "carbs": 45},
    {"name": "Тунцовый мусс", "weight": 70, "calories": 140, "protein": 13, "fats": 9, "carbs": 1},
    {"name": "Авокадо", "weight": 50, "calories": 80, "protein": 1, "fats": 8, "carbs": 0},
    {"name": "Помидор", "weight": 100, "calories": 20, "protein": 0, "fats": 0, "carbs": 0},
    {"name": "Веганский песто", "weight": 20, "calories": 28, "protein": 0, "fats": 7, "carbs": 0},
]


def _router(items, dish="Сэндвич Tunacado"):
    return {"type": "food", "data": {"dish_name": dish, "items": [dict(i) for i in items]}}


# ── extract_stated_totals ────────────────────────────────────────────────────


class TestExtract:
    def test_kcal_and_macros(self):
        assert extract_stated_totals(TUNACADO_TEXT) == {
            "calories": 506.0,
            "protein": 22.0,
            "fats": 27.0,
            "carbs": 45.0,
            "has_total_marker": True,
        }

    def test_kcal_only(self):
        st = extract_stated_totals("боул с лососем и рисом, 640 kcal")
        assert st["calories"] == 640.0 and "protein" not in st and st["has_total_marker"] is False

    def test_word_macros(self):
        st = extract_stated_totals("итого 450 ккал, белки 30 г, жиры 15, углеводы 40")
        assert (st["protein"], st["fats"], st["carbs"]) == (30.0, 15.0, 40.0)
        assert st["has_total_marker"] is True

    def test_decimal_comma(self):
        assert extract_stated_totals("на упаковке 320,5 ккал")["calories"] == 320.5

    def test_no_kcal(self):
        assert extract_stated_totals("гречка 150 г, котлета") is None

    def test_two_different_kcal_values_is_ambiguous(self):
        assert extract_stated_totals("батончик 200 ккал и йогурт 120 ккал") is None

    def test_per_100g_is_not_total(self):
        assert extract_stated_totals("творог 5%, 120 ккал на 100 г, съел 200 г") is None
        assert extract_stated_totals("сыр 350 ккал/100г, 30 г") is None

    def test_implausible_values_ignored(self):
        assert extract_stated_totals("0 ккал") is None
        assert extract_stated_totals("20000 ккал") is None


# ── process_llm_food_data(anchor_stated_total=True) ──────────────────────────


def test_tunacado_anchored_to_stated_total():
    items, totals = process_llm_food_data(_router(TUNACADO_ITEMS), TUNACADO_TEXT, anchor_stated_total=True)
    assert totals["calories"] == pytest.approx(506, abs=0.5)
    assert (totals["protein"], totals["fats"], totals["carbs"]) == (22.0, 27.0, 45.0)
    assert sum(i["calories"] for i in items) == pytest.approx(506, abs=1.5)
    assert items[0]["weight_g"] == 100  # вес не трогаем — якорь по калориям


def test_macros_scaled_when_not_stated():
    text = "сэндвич с тунцом: хлеб, тунцовый мусс, авокадо, помидор, песто — 506 ккал"
    _, totals = process_llm_food_data(_router(TUNACADO_ITEMS), text, anchor_stated_total=True)
    factor = 506 / 518
    assert totals["calories"] == pytest.approx(506, abs=0.5)
    assert totals["protein"] == pytest.approx(22 * factor, abs=0.3)
    assert totals["fats"] == pytest.approx(27 * factor, abs=0.3)


def test_flag_off_keeps_component_sum():
    # multi_food и прочие пути: описание общее на несколько блюд — якорь не включаем
    _, totals = process_llm_food_data(_router(TUNACADO_ITEMS), TUNACADO_TEXT)
    assert totals["calories"] == pytest.approx(518, abs=1)


def test_kcal_of_one_item_is_not_meal_total():
    items = [
        {"name": "Яблоко", "weight": 150, "calories": 78, "protein": 0, "fats": 0, "carbs": 19},
        {"name": "Батончик", "weight": 50, "calories": 200, "protein": 10, "fats": 8, "carbs": 20},
    ]
    _, totals = process_llm_food_data(
        _router(items, dish="Яблоко и батончик"), "яблоко и батончик 200 ккал", anchor_stated_total=True
    )
    assert totals["calories"] == pytest.approx(278, abs=1)


def test_far_off_without_marker_not_anchored():
    # «450 ккал» без маркера итога, а позиции дают 1500 — вероятно, ккал одной части
    items = [
        {"name": "Паста", "weight": 300, "calories": 1050, "protein": 30, "fats": 30, "carbs": 160},
        {"name": "Салат", "weight": 200, "calories": 600, "protein": 5, "fats": 40, "carbs": 10},
    ]
    # ни одна позиция не равна 450, но и сумма 1650 далека (×3.7) → не якорим
    _, totals = process_llm_food_data(_router(items, dish="Ужин"), "паста и салат 450 ккал", anchor_stated_total=True)
    assert totals["calories"] == pytest.approx(1650, abs=1)


def test_marker_allows_large_correction():
    items = [
        {"name": "Паста", "weight": 300, "calories": 1050, "protein": 30, "fats": 30, "carbs": 160},
        {"name": "Салат", "weight": 200, "calories": 600, "protein": 5, "fats": 40, "carbs": 10},
    ]
    _, totals = process_llm_food_data(
        _router(items, dish="Ужин"), "паста и салат, итого по меню 900 ккал", anchor_stated_total=True
    )
    assert totals["calories"] == pytest.approx(900, abs=0.5)


def test_single_item_untouched():
    items = [{"name": "Батончик", "weight": 50, "calories": 190, "protein": 10, "fats": 8, "carbs": 20}]
    _, totals = process_llm_food_data(_router(items, dish="Батончик"), "батончик 200 ккал", anchor_stated_total=True)
    assert totals["calories"] == pytest.approx(190, abs=1)
