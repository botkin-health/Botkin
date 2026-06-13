from core.llm.router import SYSTEM_PROMPT


def test_system_prompt_contains_multi_food_type():
    assert "multi_food" in SYSTEM_PROMPT


def test_system_prompt_contains_meals_array():
    assert '"meals"' in SYSTEM_PROMPT


def test_system_prompt_distinguishes_from_business_lunch():
    """Example 6 must clarify when NOT to use multi_food."""
    assert "DIFFERENT slots" in SYSTEM_PROMPT or "DIFFERENT slot" in SYSTEM_PROMPT
