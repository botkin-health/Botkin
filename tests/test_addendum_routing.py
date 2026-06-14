"""Tests for addendum intent detection in _is_clearly_conversational.

Addendum phrases ("forgot to mention tea") should route to BotkinClaw agent
(return True from _is_clearly_conversational) instead of the food pipeline,
even when the message contains food-related keywords.
Issue #54.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

from handlers.text import _is_clearly_conversational


class TestAddendumRoutesToAgent:
    def test_zabyl_dobavit_chai(self):
        assert _is_clearly_conversational("забыл добавить чай") is True

    def test_zabyl_upomyanut_coffee(self):
        assert _is_clearly_conversational("забыл упомянуть — запивал кофе") is True

    def test_zabyl_skazat(self):
        assert _is_clearly_conversational("забыл сказать, ещё выпил стакан воды") is True

    def test_zabyl_with_food_keyword_still_true(self):
        # "завтрак" is a food disqualifier — addendum must win
        assert _is_clearly_conversational("забыл упомянуть завтрак") is True

    def test_nujno_dobavit(self):
        assert _is_clearly_conversational("нужно добавить к предыдущему") is True

    def test_nujno_dopisat(self):
        assert _is_clearly_conversational("нужно дописать") is True


class TestNonAddendumRoutesFoodPipeline:
    def test_regular_food_entry_false(self):
        assert _is_clearly_conversational("яичница из 2 яиц") is False

    def test_slot_prefix_false(self):
        assert _is_clearly_conversational("Завтрак: яичница с тостом") is False

    def test_weight_entry_false(self):
        assert _is_clearly_conversational("200г куриной грудки") is False
