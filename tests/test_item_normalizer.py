"""
Tests for helpers.db_save.normalize_item_to_canonical — the SINGLE translator
that converts any nutrition-log item dialect into the canonical
{food, amount, unit, calories, protein, fats, carbs, fiber} shape.

Covers all 3 dialects found in production data (audit 2026-04-21):
  - Canonical (91%):   {food, amount, unit, ...}
  - Domain (internal): {product, weight_g, ...}
  - Psyllium backfill: {name, weight_g, ...}
  - LLM-style:         {name, weight, ...}
"""

import sys
from pathlib import Path

# ── project root on sys.path ─────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from helpers.db_save import normalize_item_to_canonical


# Canonical expected output for all equivalent inputs in each test
CANONICAL_SHAPE = {
    "food": "Гречка",
    "amount": 200.0,
    "unit": "г",
    "calories": 250,
    "protein": 10,
    "fats": 3,
    "carbs": 50,
    "fiber": 4.5,
}


def test_canonical_input_passes_through_unchanged():
    """Already-canonical dicts are returned bit-identical."""
    item = {
        "food": "Гречка",
        "amount": 200.0,
        "unit": "г",
        "calories": 250,
        "protein": 10,
        "fats": 3,
        "carbs": 50,
        "fiber": 4.5,
    }
    assert normalize_item_to_canonical(item) == CANONICAL_SHAPE


def test_domain_dialect_product_weight_g():
    """Internal domain: {product, weight_g, ...} → canonical."""
    item = {
        "product": "Гречка",
        "weight_g": 200.0,
        "calories": 250,
        "protein": 10,
        "fats": 3,
        "carbs": 50,
        "fiber": 4.5,
    }
    assert normalize_item_to_canonical(item) == CANONICAL_SHAPE


def test_psyllium_dialect_name_weight_g():
    """Psyllium backfill script used: {name, weight_g, ...}."""
    item = {
        "name": "Гречка",
        "weight_g": 200.0,
        "calories": 250,
        "protein": 10,
        "fats": 3,
        "carbs": 50,
        "fiber": 4.5,
    }
    assert normalize_item_to_canonical(item) == CANONICAL_SHAPE


def test_llm_dialect_name_weight():
    """Some LLM outputs use: {name, weight, ...}."""
    item = {
        "name": "Гречка",
        "weight": 200.0,
        "calories": 250,
        "protein": 10,
        "fats": 3,
        "carbs": 50,
        "fiber": 4.5,
    }
    assert normalize_item_to_canonical(item) == CANONICAL_SHAPE


def test_legacy_fat_singular_key():
    """Very old schema used 'fat' (singular). Must map to 'fats'."""
    item = {
        "food": "Масло",
        "amount": 10.0,
        "calories": 90,
        "protein": 0,
        "fat": 10,  # singular!
        "carbs": 0,
        "fiber": 0,
    }
    result = normalize_item_to_canonical(item)
    assert result["fats"] == 10
    assert "fat" not in result


def test_missing_fields_default_to_zero():
    """Robustness: missing numeric fields must not crash."""
    item = {"product": "X"}
    result = normalize_item_to_canonical(item)
    assert result["food"] == "X"
    assert result["amount"] == 0.0
    assert result["calories"] == 0
    assert result["protein"] == 0
    assert result["fats"] == 0
    assert result["carbs"] == 0
    assert result["fiber"] == 0.0
    assert result["unit"] == "г"


def test_missing_name_uses_placeholder():
    """No name field anywhere → placeholder, not crash."""
    item = {"amount": 100, "calories": 50}
    result = normalize_item_to_canonical(item)
    assert result["food"] == "Неизвестный продукт"
    assert result["amount"] == 100.0


def test_none_values_coerced_to_zero():
    """None in numeric fields must not blow up."""
    item = {
        "product": "Y",
        "weight_g": None,
        "calories": None,
        "protein": None,
        "fats": None,
        "carbs": None,
        "fiber": None,
    }
    result = normalize_item_to_canonical(item)
    assert result["amount"] == 0.0
    assert result["calories"] == 0
    assert result["fiber"] == 0.0


def test_string_numeric_fields_coerced():
    """Occasionally LLM returns strings instead of numbers."""
    item = {
        "product": "Z",
        "weight_g": "150",
        "calories": "300",
        "protein": "15",
        "fats": "5",
        "carbs": "40",
        "fiber": "2.5",
    }
    result = normalize_item_to_canonical(item)
    assert result["amount"] == 150.0
    assert result["calories"] == 300
    assert result["fiber"] == 2.5


def test_note_pass_through():
    """Optional 'note' field is preserved if non-empty."""
    item = {"product": "A", "weight_g": 100, "note": "вкусно"}
    result = normalize_item_to_canonical(item)
    assert result["note"] == "вкусно"


def test_empty_note_not_in_output():
    """Empty note is omitted (no null noise)."""
    item = {"product": "A", "weight_g": 100, "note": ""}
    result = normalize_item_to_canonical(item)
    assert "note" not in result


def test_drinks_pass_through():
    """Optional 'drinks' field (ml) preserved."""
    item = {"product": "Кофе", "weight_g": 0, "drinks": 250.0}
    result = normalize_item_to_canonical(item)
    assert result["drinks"] == 250.0


def test_fiber_rounded_to_one_decimal():
    """Fiber is rounded to 1 decimal place for storage consistency."""
    item = {"product": "X", "weight_g": 100, "fiber": 3.456789}
    result = normalize_item_to_canonical(item)
    assert result["fiber"] == 3.5


def test_idempotent_on_repeat_application():
    """Normalising twice yields the same result as once — normaliser is idempotent."""
    raw = {"product": "Гречка", "weight_g": 200, "calories": 250, "protein": 10, "fats": 3, "carbs": 50, "fiber": 4.5}
    once = normalize_item_to_canonical(raw)
    twice = normalize_item_to_canonical(once)
    assert once == twice
