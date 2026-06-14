from core.llm.models import parse_llm_response
from core.llm.router import SYSTEM_PROMPT


def test_system_prompt_contains_multi_food_type():
    assert "multi_food" in SYSTEM_PROMPT


def test_system_prompt_contains_meals_array():
    assert '"meals"' in SYSTEM_PROMPT


def test_system_prompt_distinguishes_from_business_lunch():
    """Example 6 must clarify when NOT to use multi_food."""
    assert "DIFFERENT slots" in SYSTEM_PROMPT or "DIFFERENT slot" in SYSTEM_PROMPT


# --- parse_llm_response dispatch for multi_food -----------------------------


def test_parse_multi_food_roundtrips_two_meals():
    raw = {
        "type": "multi_food",
        "data": {
            "meals": [
                {"dish_name": "Завтрак", "meal_type": "breakfast", "items": [{"name": "Овсянка", "weight": 200}]},
                {"dish_name": "Обед", "meal_type": "lunch", "items": [{"name": "Суп", "weight": 300}]},
            ]
        },
    }
    parsed = parse_llm_response(raw)
    assert parsed["type"] == "multi_food"
    assert [m["dish_name"] for m in parsed["data"]["meals"]] == ["Завтрак", "Обед"]


def test_parse_multi_food_empty_meals_is_valid():
    parsed = parse_llm_response({"type": "multi_food", "data": {"meals": []}})
    assert parsed["data"]["meals"] == []


def test_parse_multi_food_coerces_stringified_numbers():
    # GPT often returns weights/calories as strings — must coerce, not crash.
    raw = {
        "type": "multi_food",
        "data": {"meals": [{"dish_name": "X", "items": [{"name": "A", "weight": "150", "calories": "200"}]}]},
    }
    parsed = parse_llm_response(raw)
    item = parsed["data"]["meals"][0]["items"][0]
    assert item["weight"] == 150.0
    assert item["calories"] == 200.0


def test_parse_multi_food_malformed_meals_falls_back_to_raw():
    # `meals` must be a list; on validation failure parse_llm_response is
    # backward-compatible and returns the original raw unchanged (not a crash).
    raw = {"type": "multi_food", "data": {"meals": "oops"}}
    assert parse_llm_response(raw) == raw
