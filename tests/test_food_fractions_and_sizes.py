"""Регрессия 18.10.2026: «1/2 банана» записалось как 240 г банана (212 ккал).

Счётчик штук в description_parser видел только «2 банана» (знаменатель дроби)
→ 2 × 120 г. «50% банана» не матчилось вовсе, вес оставался за LLM.
Плюс размер фрукта («маленькое яблоко», «большой банан») парсер не учитывал —
вес целиком зависел от догадки LLM.
"""

import pytest

from core.food.description_parser import extract_products_from_description
from core.food.nutrition import process_llm_food_data


def _weight_of(products, token):
    for p in products:
        if token in p["name"].lower():
            return p["weight"]
    return None


class TestFractionCounts:
    @pytest.mark.parametrize(
        "text",
        [
            "Завтрак:\n1/2 банана\nМаленькое яблоко",
            "1/2 банана",
            "1 / 2 банана",
            "½ банана",
            "50% банана",
            "50 % банана",
            "0.5 банана",
            "полбанана",
        ],
    )
    def test_half_banana_is_60g(self, text):
        assert _weight_of(extract_products_from_description(text), "банан") == 60

    def test_quarter_apple(self):
        assert _weight_of(extract_products_from_description("¼ яблока"), "яблоко") == 40

    def test_three_quarters_pear(self):
        assert _weight_of(extract_products_from_description("3/4 груши"), "груша") == 105

    def test_third_apple_rounded(self):
        assert _weight_of(extract_products_from_description("1/3 яблока"), "яблоко") == 53.3

    def test_poltora_banana(self):
        assert _weight_of(extract_products_from_description("полтора банана"), "банан") == 180

    def test_one_and_half_bananas(self):
        assert _weight_of(extract_products_from_description("1,5 банана"), "банан") == 180

    def test_percent_of_eggs(self):
        # «50% яйца» — половина яйца, а не 50 яиц
        assert _weight_of(extract_products_from_description("50% яйца"), "яйцо") == 27.5

    def test_whole_numbers_unchanged(self):
        assert _weight_of(extract_products_from_description("2 банана"), "банан") == 240

    def test_fat_percent_is_not_a_count(self):
        # «2.5% молоко» — жирность, к счётчику штук отношения не имеет
        from core.food.description_parser import normalize_fractions

        assert normalize_fractions("стакан молока 2.5%") == "стакан молока 2.5%"
        assert normalize_fractions("2.5% молоко") == "2.5% молоко"
        assert normalize_fractions("кефир 2.5% банан") == "кефир 2.5% банан"


class TestFruitSize:
    @pytest.mark.parametrize(
        "text,token,expected",
        [
            ("маленькое яблоко", "яблоко", 130),
            ("Маленькое яблоко", "яблоко", 130),
            ("большое яблоко", "яблоко", 220),
            ("крупное яблоко", "яблоко", 220),
            ("среднее яблоко", "яблоко", 160),
            ("маленький банан", "банан", 100),
            ("большой банан", "банан", 140),
            ("маленькая груша", "груша", 110),
            ("большой апельсин", "апельсин", 190),
            ("маленький мандарин", "мандарин", 60),
        ],
    )
    def test_size_word(self, text, token, expected):
        assert _weight_of(extract_products_from_description(text), token) == expected

    def test_count_with_size(self):
        assert _weight_of(extract_products_from_description("2 маленьких яблока"), "яблоко") == 260

    def test_fraction_with_size(self):
        assert _weight_of(extract_products_from_description("1/2 большого банана"), "банан") == 70

    def test_breakfast_from_incident(self):
        products = extract_products_from_description("Завтрак:\n1/2 банана\nМаленькое яблоко")
        assert _weight_of(products, "банан") == 60
        assert _weight_of(products, "яблоко") == 130


def _llm(items):
    return {"type": "food", "data": {"items": items}}


class TestEndToEnd:
    def test_half_banana_not_doubled(self):
        llm = _llm(
            [
                {"name": "Банан", "weight": 60, "calories": 53, "protein": 1, "fats": 0, "carbs": 14},
                {"name": "Яблоко маленькое", "weight": 130, "calories": 68, "protein": 0, "fats": 0, "carbs": 18},
            ]
        )
        items, totals = process_llm_food_data(llm, "Завтрак:\n1/2 банана\nМаленькое яблоко")
        banana = next(i for i in items if "банан" in i["product"].lower())
        assert banana["weight_g"] == 60
        assert totals["calories"] < 150, totals
