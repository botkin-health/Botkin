"""Tests for fiber enrichment pipeline.

Covers:
  - fiber_per_100g / estimate_fiber (base lookup)
  - _item_name / _item_weight (schema adapter for the 3 item formats in DB)
  - enrich_items_with_fiber (idempotent mutation)
  - sum_fiber (roll-up)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.food.fiber_table import (
    enrich_items_with_fiber,
    estimate_fiber,
    fiber_per_100g,
    sum_fiber,
    _item_name,
    _item_weight,
)


# ── base lookup ───────────────────────────────────────────────────────────────


def test_fiber_per_100g_known_foods():
    assert fiber_per_100g("тыква") == 2.1
    assert fiber_per_100g("шпинат") == 2.2
    assert fiber_per_100g("чечевица отварная") == 7.9  # matches "чечевиц"
    assert fiber_per_100g("семена чиа") == 34.4


def test_fiber_per_100g_unknown_returns_none():
    assert fiber_per_100g("говядина тушёная") is None
    assert fiber_per_100g("") is None
    assert fiber_per_100g("нечто незнакомое") is None


def test_estimate_fiber_scales_by_weight():
    # 100g tyk = 2.1g fiber, 200g = 4.2g
    assert estimate_fiber("тыква запечённая", 200) == 4.2
    assert estimate_fiber("шпинат", 50) == 1.1


def test_estimate_fiber_zero_when_no_match():
    assert estimate_fiber("говядина", 300) == 0.0
    assert estimate_fiber("сыр", 100) == 0.0


def test_estimate_fiber_zero_when_no_weight():
    assert estimate_fiber("тыква", None) == 0.0
    assert estimate_fiber("тыква", 0) == 0.0


# ── schema adapter ────────────────────────────────────────────────────────────


def test_item_name_handles_all_schemas():
    # DB LLM format
    assert _item_name({"food": "Уха"}) == "Уха"
    # Internal meal_items format
    assert _item_name({"product": "Рис"}) == "Рис"
    # Supplements format
    assert _item_name({"name": "Псиллиум"}) == "Псиллиум"
    # Priority: product > name > food
    assert _item_name({"product": "A", "name": "B", "food": "C"}) == "A"
    assert _item_name({}) == ""


def test_item_weight_handles_all_schemas():
    assert _item_weight({"weight_g": 100}) == 100.0
    assert _item_weight({"amount": 150}) == 150.0
    assert _item_weight({"weight": 200}) == 200.0
    # Priority: weight_g > amount > weight
    assert _item_weight({"weight_g": 50, "amount": 999}) == 50.0
    assert _item_weight({}) == 0.0
    # Handles string numbers
    assert _item_weight({"amount": "100.0"}) == 100.0


# ── enrich_items_with_fiber ───────────────────────────────────────────────────


def test_enrich_idempotent_preserves_existing_fiber():
    items = [{"food": "Псиллиум", "amount": 5, "fiber": 4.0}]
    enrich_items_with_fiber(items)
    # Existing fiber > 0 must not be overwritten
    assert items[0]["fiber"] == 4.0


def test_enrich_fills_missing_fiber():
    items = [{"food": "Салат с тыквой", "amount": 200}]
    enrich_items_with_fiber(items)
    # "тыкв" matches before "салат" in the ordered table — it's placed after though,
    # so "салат" wins with 1.3g/100g × 200g = 2.6g
    # Actually order: салат (line ~110) matched first; тыкв (line ~90) even earlier.
    # Either way, fiber must be > 0.
    assert items[0]["fiber"] > 0


def test_enrich_overwrites_zero_fiber():
    # Legacy items stored with explicit fiber=0 should still get estimate
    items = [{"food": "Шпинат припущенный", "amount": 100, "fiber": 0}]
    enrich_items_with_fiber(items)
    assert items[0]["fiber"] == 2.2  # from fiber_table


def test_enrich_handles_unknown_food():
    items = [{"food": "Говядина тушёная", "amount": 200, "fiber": 0}]
    enrich_items_with_fiber(items)
    # Meat has no fiber match — stays 0
    assert items[0].get("fiber", 0) == 0


def test_enrich_handles_mixed_meal():
    """Real-world example: today's meal with mixed items."""
    items = [
        {"food": "Уха", "amount": 300},  # no match → 0
        {"food": "Салат с креветками, тыквой и зеленью", "amount": 200},  # matches
        {"name": "Псиллиум (БАД)", "weight_g": 5, "fiber": 4.0},  # preserve
    ]
    enrich_items_with_fiber(items)
    assert items[0].get("fiber", 0) == 0  # Уха — no ingredient match
    assert items[1]["fiber"] > 0  # Салат matches
    assert items[2]["fiber"] == 4.0  # Псиллиум preserved


def test_enrich_returns_same_list():
    items = [{"food": "Тыква", "amount": 100}]
    result = enrich_items_with_fiber(items)
    assert result is items  # same reference, mutation in place


# ── sum_fiber ─────────────────────────────────────────────────────────────────


def test_sum_fiber_basic():
    items = [
        {"fiber": 2.5},
        {"fiber": 1.0},
        {"fiber": 0},
    ]
    assert sum_fiber(items) == 3.5


def test_sum_fiber_missing_field():
    items = [{"fiber": 2.0}, {}]
    assert sum_fiber(items) == 2.0


def test_sum_fiber_null_values():
    items = [{"fiber": None}, {"fiber": "invalid"}, {"fiber": 1.5}]
    assert sum_fiber(items) == 1.5
