"""#614: дроби, слова-числа и доли за пределами #611.

Таблица «форма записи → вес». Если форма неоднозначна, парсер возвращает пусто
и вес остаётся за LLM (в таблице — None).
"""

import pytest

from core.food.description_parser import extract_products_from_description, normalize_fractions
from core.food.nutrition import process_llm_food_data


def _weight_of(text, token):
    for p in extract_products_from_description(text):
        if token in p["name"].lower():
            return p["weight"]
    return None


class TestWordFractionsBeforeCountable:
    @pytest.mark.parametrize(
        "text,token,expected",
        [
            ("половина банана", "банан", 60),
            ("пол-банана", "банан", 60),
            ("половинка яблока", "яблоко", 80),
            ("треть яблока", "яблоко", 53.3),
            ("четверть яблока", "яблоко", 40),
            ("три четверти яблока", "яблоко", 120),
            ("две трети яблока", "яблоко", 106.7),
            ("две с половиной груши", "груша", 350),
            ("2 с половиной яйца", "яйцо", 137.5),
            ("две с половиной банана", "банан", 300),
            ("полторы груши", "груша", 210),
        ],
    )
    def test_word_forms(self, text, token, expected):
        assert _weight_of(text, token) == expected


class TestMixedAndDecimal:
    @pytest.mark.parametrize(
        "text,token,expected",
        [
            ("1 1/2 банана", "банан", 180),
            ("1 ½ банана", "банан", 180),
            ("1 1/2 яблока", "яблоко", 240),
            ("2 1/2 яйца", "яйцо", 137.5),
            ("1,5 штуки банана", "банан", 180),
            ("2.5 яблока", "яблоко", 400),
            ("2,5 яблока", "яблоко", 400),
            ("1/2 яблок", "яблоко", 80),
            ("1/2 яиц", "яйцо", 27.5),
        ],
    )
    def test_mixed(self, text, token, expected):
        assert _weight_of(text, token) == expected


class TestFractionBeforeMeasure:
    @pytest.mark.parametrize(
        "text,token,expected",
        [
            ("полстакана молока", "молока", 100),
            ("пол стакана кефира", "кефира", 100),
            ("1/2 стакана молока", "молока", 100),
            ("½ стакана молока", "молока", 100),
            ("полтора стакана молока", "молока", 300),
            ("три четверти стакана молока", "молока", 150),
            ("2 стакана воды", "воды", 400),
        ],
    )
    def test_glass(self, text, token, expected):
        assert _weight_of(text, token) == expected

    @pytest.mark.parametrize("text", ["1/2 ст. ложки мёда", "1/2 ст.л. мёда", "1/4 пачки творога", "1/2 порции риса"])
    def test_unknown_measure_left_to_llm(self, text):
        assert extract_products_from_description(text) == []


class TestLiters:
    @pytest.mark.parametrize(
        "text,token,expected",
        [
            ("0,5 л молока", "молока", 500),
            ("0.5 л воды", "воды", 500),
            ("1.5 л воды", "воды", 1500),
            ("2 литра кефира", "кефира", 2000),
            ("300 мл кефира", "кефира", 300),
            ("200 г творога", "творога", 200),
            ("5 г лосося", "лосос", 5),
        ],
    )
    def test_liters_to_grams(self, text, token, expected):
        assert _weight_of(text, token) == expected


class TestInterference:
    @pytest.mark.parametrize(
        "text",
        ["молоко 2.5%", "творог 5%", "2.5% молоко", "кефир 2.5% банан", "йогурт 1.5% яблоко", "сыр 45% яйцо"],
    )
    def test_fat_percent_untouched(self, text):
        assert normalize_fractions(text) == text

    def test_fat_percent_does_not_make_fruit_weight(self):
        assert _weight_of("кефир 2.5% банан", "банан") is None

    @pytest.mark.parametrize("text", ["в 13:30 банан", "банан в 9:05", "18.10.2026 банан"])
    def test_time_and_date_are_not_counts(self, text):
        assert _weight_of(text, "банан") is None

    def test_time_does_not_break_fraction(self):
        assert _weight_of("в 13:30 1/2 банана", "банан") == 60

    @pytest.mark.parametrize("text", ["50% банана", "25% яблока"])
    def test_round_percent_still_fraction(self, text):
        assert _weight_of(text, "банан" if "банан" in text else "яблоко") in (60, 40)

    def test_fraction_words_not_before_food_left_alone(self):
        # «четверть часа» / «треть пути» — не доля продукта
        assert normalize_fractions("четверть часа") == "четверть часа"


class TestEndToEnd:
    def test_half_glass_fills_missing_llm_weight(self):
        # ADR-0011 п. 5: вес модели не перекрывается; граммы из текста — только если веса нет
        llm = {"type": "food", "data": {"items": [{"name": "Молоко", "calories": 60, "protein": 3}]}}
        items, _ = process_llm_food_data(llm, "полстакана молока")
        assert items[0]["weight_g"] == 100

    def test_half_glass_keeps_llm_weight_on_mismatch(self, caplog):
        llm = {
            "type": "food",
            "data": {
                "items": [{"name": "Молоко", "weight": 200, "calories": 120, "protein": 6, "fats": 6, "carbs": 9}]
            },
        }
        items, totals = process_llm_food_data(llm, "полстакана молока")
        assert items[0]["weight_g"] == 200
        assert totals["calories"] == 120
        assert "расходится с текстом" in caplog.text

    def test_half_liter_not_half_gram(self):
        llm = {
            "type": "food",
            "data": {
                "items": [{"name": "Молоко", "weight": 500, "calories": 300, "protein": 15, "fats": 15, "carbs": 24}]
            },
        }
        items, _ = process_llm_food_data(llm, "0,5 л молока")
        assert items[0]["weight_g"] == 500
