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
