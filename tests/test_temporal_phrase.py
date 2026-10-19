"""Tests for _temporal_phrase_to_time in telegram-bot/handlers/text.py.

Regression (#meal-time): названия приёмов пищи (завтрак/обед/ужин/перекус/полдник)
трактовались как временны́е фразы и возвращали фиксированный час (завтрак→08:00).
Из-за этого сообщение «завтрак: яйца, овощи», отправленное в 10:04, записывалось
с meal_time=08:00, ломая наложение кривой CGM на приём пищи.

Правило: ярлык приёма пищи (что человек ест) ≠ время суток (когда он ест).
Только настоящие temporal-фразы («утром», «вечером», «в полдень») задают время;
голый ярлык блюда должен вернуть None → вызывающий код подставит время сообщения.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

from handlers.text import _temporal_phrase_to_time


class TestMealLabelsAreNotTime:
    """Голые названия приёмов пищи НЕ должны инферить фиксированное время."""

    def test_zavtrak_label_returns_none(self):
        # Список продуктов с ярлыком «завтрак» без слова о времени → None
        assert _temporal_phrase_to_time("Завтрак: яйца, овощи, кускус") is None

    def test_na_zavtrak_returns_none(self):
        assert _temporal_phrase_to_time("на завтрак ел кускус после белка") is None

    def test_obed_label_returns_none(self):
        assert _temporal_phrase_to_time("Обед: суп, котлета") is None

    def test_uzhin_label_returns_none(self):
        assert _temporal_phrase_to_time("Ужин: салат и рыба") is None

    def test_perekus_label_returns_none(self):
        assert _temporal_phrase_to_time("Перекус: яблоко") is None

    def test_poldnik_label_returns_none(self):
        assert _temporal_phrase_to_time("Полдник: творог") is None

    def test_bare_product_list_returns_none(self):
        assert _temporal_phrase_to_time("яйца 2шт, огурец, помидор, кускус 100г") is None


class TestRealTemporalPhrases:
    """Настоящие фразы о времени суток продолжают работать."""

    def test_utrom(self):
        assert _temporal_phrase_to_time("утром ел кашу") == "08:00"

    def test_rannim_utrom(self):
        assert _temporal_phrase_to_time("ранним утром") == "06:00"

    def test_dnem(self):
        assert _temporal_phrase_to_time("днём перекусил") == "13:00"

    def test_vecherom(self):
        assert _temporal_phrase_to_time("вечером съел салат") == "20:00"

    def test_nochyu(self):
        assert _temporal_phrase_to_time("ночью") == "22:30"

    def test_pered_snom(self):
        assert _temporal_phrase_to_time("перекусил перед сном") == "22:30"


class TestExplicitClockTime:
    """Явное время в тексте (#629): «ел это в 18:00» → 18:00, а не время сообщения."""

    def test_v_hh_mm_colon(self):
        assert _temporal_phrase_to_time("сэндвич с тунцом. Ел это в 18:00") == "18:00"

    def test_bare_hh_mm_colon(self):
        assert _temporal_phrase_to_time("18:30 гречка 150 г") == "18:30"

    def test_v_hh_mm_dot(self):
        assert _temporal_phrase_to_time("в 7.30 овсянка") == "07:30"

    def test_v_hh_mm_dash(self):
        assert _temporal_phrase_to_time("в 18-00 сырники") == "18:00"

    def test_v_hour_end_of_text(self):
        assert _temporal_phrase_to_time("обед в 13") == "13:00"

    def test_v_hour_before_comma(self):
        assert _temporal_phrase_to_time("в 13, суп и котлета") == "13:00"

    def test_v_hour_chasov(self):
        assert _temporal_phrase_to_time("в 9 часов творог") == "09:00"

    def test_v_hour_vechera(self):
        assert _temporal_phrase_to_time("в 7 вечера салат") == "19:00"

    def test_v_hour_utra(self):
        assert _temporal_phrase_to_time("в 7 утра кофе") == "07:00"

    def test_v_12_nochi_is_midnight(self):
        assert _temporal_phrase_to_time("в 12 ночи бутерброд") == "00:00"

    def test_explicit_beats_part_of_day(self):
        # «вечером» дало бы 20:00 — явное время приоритетнее
        assert _temporal_phrase_to_time("вечером в 19:15 рыба") == "19:15"

    def test_invalid_time_ignored(self):
        assert _temporal_phrase_to_time("в 25:00 что-то") is None

    def test_quantities_are_not_time(self):
        assert _temporal_phrase_to_time("в 2 раза больше риса") is None
        assert _temporal_phrase_to_time("яйца 2 шт, хлеб 1.50 кусочка") is None
        assert _temporal_phrase_to_time("кофе с молоком 1.5%") is None
        assert _temporal_phrase_to_time("сыр 2 куска") is None
