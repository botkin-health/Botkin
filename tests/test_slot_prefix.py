"""Tests for slot prefix detection in telegram-bot/handlers/text.py.

Regression: when user's caption is a bare slot word like "Завтрак" (without
colon/dash), the prefix was lost and the meal ended up slotted by time only.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

from handlers.text import apply_slot_prefix, detect_slot_prefix


class TestDetectSlotPrefix:
    """detect_slot_prefix: find slot label at start of user text."""

    # --- Bare word (the bug fix) ---
    def test_bare_word_zavtrak(self):
        assert detect_slot_prefix("Завтрак") == "Завтрак"

    def test_bare_word_obed(self):
        assert detect_slot_prefix("Обед") == "Обед"

    def test_bare_word_uzhin(self):
        assert detect_slot_prefix("Ужин") == "Ужин"

    def test_bare_word_perekus(self):
        assert detect_slot_prefix("Перекус") == "Перекус"

    def test_bare_word_case_insensitive(self):
        assert detect_slot_prefix("ЗАВТРАК") == "Завтрак"
        assert detect_slot_prefix("завтрак") == "Завтрак"

    def test_bare_word_english(self):
        assert detect_slot_prefix("breakfast") == "Завтрак"
        assert detect_slot_prefix("Lunch") == "Обед"
        assert detect_slot_prefix("DINNER") == "Ужин"

    # --- Bare word + extra description (user labels + describes) ---
    def test_word_with_content(self):
        # User IS labelling as breakfast, content after is description
        assert detect_slot_prefix("Завтрак с кофе") == "Завтрак"
        assert detect_slot_prefix("Обед в ресторане") == "Обед"
        assert detect_slot_prefix("Ужин дома") == "Ужин"

    # --- With colon/dash (existing behavior) ---
    def test_colon_separator(self):
        assert detect_slot_prefix("Завтрак: яичница") == "Завтрак"

    def test_dash_separator(self):
        assert detect_slot_prefix("Завтрак - яичница") == "Завтрак"

    def test_emdash_separator(self):
        assert detect_slot_prefix("Завтрак — яичница") == "Завтрак"

    # --- With emoji prefix (align with _starts_with_token behavior) ---
    def test_emoji_then_word(self):
        assert detect_slot_prefix("🌅 Завтрак") == "Завтрак"
        assert detect_slot_prefix("🍽 Обед") == "Обед"

    # --- Negative cases: should NOT detect ---
    def test_no_slot_word(self):
        assert detect_slot_prefix("Жареное мясо с рисом") is None

    def test_conjugated_verb(self):
        # "завтракаю" — ongoing action, not a slot label
        assert detect_slot_prefix("завтракаю овсянкой") is None
        assert detect_slot_prefix("обедаю в офисе") is None

    def test_qualifier_before_word(self):
        # "Поздний обед" — qualifier, not a slot hint
        assert detect_slot_prefix("Поздний обед") is None
        assert detect_slot_prefix("поздний завтрак") is None

    def test_preposition_before_word(self):
        # "на завтрак ..." — describes purpose, not a label
        # (extract_meal_name handles this separately)
        assert detect_slot_prefix("на завтрак ем овсянку") is None

    def test_empty(self):
        assert detect_slot_prefix("") is None
        assert detect_slot_prefix(None) is None

    def test_whitespace_only(self):
        assert detect_slot_prefix("   ") is None


class TestApplySlotPrefix:
    """apply_slot_prefix: prepend slot label to meal_name if text hints slot."""

    def test_bare_word_prepends(self):
        # The regression case
        result = apply_slot_prefix("Завтрак", "Жареное мясо с рисом и брокколи")
        assert result == "Завтрак: Жареное мясо с рисом и брокколи"

    def test_colon_still_works(self):
        result = apply_slot_prefix("Завтрак: овсянка", "овсянка с бананом")
        assert result == "Завтрак: овсянка с бананом"

    def test_no_double_prefix(self):
        # meal_name already has the prefix — don't duplicate
        result = apply_slot_prefix("Завтрак", "Завтрак: овсянка")
        assert result == "Завтрак: овсянка"

    def test_no_slot_word_passthrough(self):
        result = apply_slot_prefix("Жареное мясо", "Жареное мясо с рисом")
        assert result == "Жареное мясо с рисом"

    def test_none_meal_name(self):
        assert apply_slot_prefix("Завтрак", None) is None

    def test_empty_text(self):
        assert apply_slot_prefix("", "Яичница") == "Яичница"

    def test_emoji_caption(self):
        result = apply_slot_prefix("🌅 Завтрак", "овсянка")
        assert result == "Завтрак: овсянка"

    def test_english_caption(self):
        result = apply_slot_prefix("breakfast", "oatmeal")
        assert result == "Завтрак: oatmeal"

    def test_verb_form_not_prefixed(self):
        # "завтракаю" should NOT trigger prefix
        result = apply_slot_prefix("завтракаю овсянкой", "овсянка с бананом")
        assert result == "овсянка с бананом"

    def test_qualifier_not_prefixed(self):
        # "Поздний обед" — let time-based slotting decide
        result = apply_slot_prefix("Поздний обед", "суп с курицей")
        assert result == "суп с курицей"


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
