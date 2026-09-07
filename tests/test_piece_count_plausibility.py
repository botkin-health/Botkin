"""Регрессия 07.09.2026: «106 перца» (без «г») парсилось как 106 ШТУК перца × 150 г = 15900 г.

Число без единицы веса перед штучным продуктом считалось количеством штук без
проверки правдоподобия. Regex-вес затем перекрывал корректный вес LLM (106 г),
калории не пересчитывались (34 ккал при 15900 г), а клетчатка считалась от
раздутого веса — 333.9 г в дневнике при норме 30 г/день.

Продолжение инцидента 12.07.2026 («73 г перца», tests/test_nutrition_parsing.py::TestGramsNotPieces):
тогда закрыли случай с явной единицей, здесь — число без единицы.
"""

import pytest

from core.food import description_parser
from core.food.description_parser import extract_products_from_description
from core.food.nutrition import process_llm_food_data


def _weight_of(products, token):
    for p in products:
        if token in p["name"].lower():
            return p["weight"], p.get("source")
    return None, None


class TestImplausiblePieceCountIsGrams:
    """Число, дающее неправдоподобный суммарный вес штучного продукта, — это граммы."""

    def test_106_pepper_without_unit_is_grams(self):
        products = extract_products_from_description("Завтрак:\n106 перца\n164 варенной индейки\n2 яйца")
        w, src = _weight_of(products, "перец")
        assert w == 106, f"Ожидали 106 г перца, получили {w}: {products}"
        assert src == "description"

    def test_106_peppers_plural_is_grams(self):
        w, _ = _weight_of(extract_products_from_description("106 перцев"), "перец")
        assert w == 106

    def test_two_peppers_still_pieces(self):
        w, src = _weight_of(extract_products_from_description("2 перца"), "перец")
        assert w == 300 and src == "quantity_estimate"

    def test_thirty_cherry_tomatoes_still_pieces(self):
        w, src = _weight_of(extract_products_from_description("30 черри"), "черри")
        assert w == 450 and src == "quantity_estimate"

    def test_twelve_eggs_still_pieces(self):
        w, src = _weight_of(extract_products_from_description("12 яиц"), "яйцо")
        assert w == 660 and src == "quantity_estimate"

    def test_no_single_item_above_cap(self):
        products = extract_products_from_description("50 котлет и 40 сосисок")
        for p in products:
            assert p["weight"] <= description_parser.MAX_PLAUSIBLE_ITEM_WEIGHT_G, products


def _llm(items):
    return {"type": "food", "data": {"items": items}}


PEPPER_LLM = {"name": "Перец болгарский", "weight": 106, "calories": 34, "protein": 1, "fats": 0, "carbs": 7}


class TestLlmWeightNotOverriddenByBadEstimate:
    """process_llm_food_data: оценка штук из regex не должна перекрывать вес LLM, если они расходятся в разы."""

    def test_end_to_end_breakfast_keeps_llm_weight_and_sane_fiber(self):
        items, totals = process_llm_food_data(_llm([PEPPER_LLM]), "Завтрак:\n106 перца\n2 яйца")
        pepper = items[0]
        assert pepper["weight_g"] == 106
        assert pepper["calories"] == 34
        assert pepper["fiber"] < 5, pepper
        assert totals["fiber"] < 5, totals

    def test_quantity_estimate_far_from_llm_weight_is_ignored(self, monkeypatch):
        monkeypatch.setattr(
            description_parser,
            "extract_products_from_description",
            lambda _d: [{"name": "перец", "weight": 15900.0, "source": "quantity_estimate"}],
        )
        items, _ = process_llm_food_data(_llm([PEPPER_LLM]), "106 перца")
        assert items[0]["weight_g"] == 106

    def test_quantity_estimate_close_to_llm_weight_still_wins(self, monkeypatch):
        monkeypatch.setattr(
            description_parser,
            "extract_products_from_description",
            lambda _d: [{"name": "перец", "weight": 300.0, "source": "quantity_estimate"}],
        )
        llm_item = dict(PEPPER_LLM, weight=250, calories=68)
        items, _ = process_llm_food_data(_llm([llm_item]), "2 перца")
        assert items[0]["weight_g"] == 300

    def test_explicit_grams_override_llm_even_if_far(self, monkeypatch):
        monkeypatch.setattr(
            description_parser,
            "extract_products_from_description",
            lambda _d: [{"name": "перец", "weight": 1000.0, "source": "description"}],
        )
        items, _ = process_llm_food_data(_llm([PEPPER_LLM]), "1000 г перца")
        assert items[0]["weight_g"] == 1000


class TestMacrosScaleWhenWeightOverridden:
    """Если regex меняет вес, взятый LLM, макросы масштабируются — иначе 15900 г при 34 ккал."""

    def test_explicit_weight_scales_calories(self, monkeypatch):
        monkeypatch.setattr(
            description_parser,
            "extract_products_from_description",
            lambda _d: [{"name": "перец", "weight": 212.0, "source": "description"}],
        )
        items, _ = process_llm_food_data(_llm([PEPPER_LLM]), "212 г перца")
        assert items[0]["weight_g"] == 212
        assert items[0]["calories"] == pytest.approx(68, abs=0.5)
        assert items[0]["carbs"] == pytest.approx(14, abs=0.5)

    def test_same_weight_leaves_macros_untouched(self, monkeypatch):
        monkeypatch.setattr(
            description_parser,
            "extract_products_from_description",
            lambda _d: [{"name": "перец", "weight": 106.0, "source": "description"}],
        )
        items, _ = process_llm_food_data(_llm([PEPPER_LLM]), "106 г перца")
        assert items[0]["calories"] == 34
