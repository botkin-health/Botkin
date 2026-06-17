"""Расчёт статистики глюкозы: TIR / avg / std (#96)."""

from core.health.glucose_stats import compute_glucose_stats


def test_empty():
    assert compute_glucose_stats([]) == {"count": 0}


def test_all_in_range():
    # Все в целевом диапазоне 3.9–10.0 → TIR 100%.
    stats = compute_glucose_stats([5.0, 6.0, 7.0, 8.0])
    assert stats["count"] == 4
    assert stats["avg"] == 6.5
    assert stats["min"] == 5.0
    assert stats["max"] == 8.0
    assert stats["tir_pct"] == 100.0
    assert stats["below_pct"] == 0.0
    assert stats["above_pct"] == 0.0


def test_mixed_ranges():
    # 1 ниже (3.0), 2 в диапазоне (5,9), 1 выше (12) → 25/50/25.
    stats = compute_glucose_stats([3.0, 5.0, 9.0, 12.0])
    assert stats["below_pct"] == 25.0
    assert stats["tir_pct"] == 50.0
    assert stats["above_pct"] == 25.0


def test_boundaries_inclusive():
    # Границы 3.9 и 10.0 считаются в диапазоне (consensus ADA/EASD).
    stats = compute_glucose_stats([3.9, 10.0])
    assert stats["tir_pct"] == 100.0


def test_std_zero_for_constant():
    stats = compute_glucose_stats([6.0, 6.0, 6.0])
    assert stats["std"] == 0.0
