"""Tests for AppleHealthPayload float→int coercion.

iOS Shortcuts (бесплатный путь Apple Health) присылает усреднённые метрики
как float с дробной частью (heart_rate_avg=72.4). Pydantic v2 strict-int
иначе отклонял такие значения с 422. Валидатор `_round_float_to_int`
округляет их до целого, сохраняя int-семантику поля.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

from webhook.apple_health import AppleHealthPayload, _hae_to_daily_payloads


INT_FIELDS = [
    "steps",
    "flights_climbed",
    "resting_heart_rate",
    "heart_rate_min",
    "heart_rate_max",
    "heart_rate_avg",
    "blood_pressure_systolic",
    "blood_pressure_diastolic",
    "hrv",
]


@pytest.mark.parametrize("field", INT_FIELDS)
def test_fractional_float_is_rounded(field):
    """Дробный float округляется до int (банковское округление Python: 72.4→72)."""
    p = AppleHealthPayload(date="2026-06-09", **{field: 72.4})
    val = getattr(p, field)
    assert val == 72
    assert isinstance(val, int)


@pytest.mark.parametrize("field", INT_FIELDS)
def test_fractional_float_rounds_up(field):
    """72.6 округляется до 73."""
    p = AppleHealthPayload(date="2026-06-09", **{field: 72.6})
    assert getattr(p, field) == 73


@pytest.mark.parametrize("field", INT_FIELDS)
def test_none_passes_through(field):
    """None остаётся None (поле опционально)."""
    p = AppleHealthPayload(date="2026-06-09", **{field: None})
    assert getattr(p, field) is None


@pytest.mark.parametrize("field", INT_FIELDS)
def test_int_unchanged(field):
    """Уже-целый int проходит без изменений."""
    p = AppleHealthPayload(date="2026-06-09", **{field: 65})
    assert getattr(p, field) == 65


def test_realistic_shortcut_payload():
    """Полный payload как от iOS Shortcut с дробными метриками."""
    p = AppleHealthPayload(
        date="2026-06-09",
        steps=8421.0,
        heart_rate_avg=72.4,
        heart_rate_min=54.7,
        heart_rate_max=131.2,
        resting_heart_rate=58.5,
        hrv=42.3,
        flights_climbed=6.0,
        blood_pressure_systolic=118.6,
        blood_pressure_diastolic=78.4,
        distance_walking_km=6.2,  # float field — остаётся float
    )
    assert p.steps == 8421
    assert p.heart_rate_avg == 72
    assert p.heart_rate_min == 55
    assert p.heart_rate_max == 131
    assert p.resting_heart_rate == 58  # round(58.5) → 58 (banker's rounding)
    assert p.hrv == 42
    assert p.flights_climbed == 6
    assert p.blood_pressure_systolic == 119
    assert p.blood_pressure_diastolic == 78
    assert p.distance_walking_km == 6.2


def test_v2_path_still_works():
    """v2-путь (_hae_to_daily_payloads) уже шлёт int — валидатор для него no-op."""
    metrics = [
        {
            "name": "heart_rate",
            "units": "count/min",
            "data": [{"date": "2026-06-09 00:00:00 +0300", "Avg": 72.4, "Min": 55.6, "Max": 130.1}],
        },
        {
            "name": "step_count",
            "units": "count",
            "data": [{"date": "2026-06-09 00:00:00 +0300", "qty": 8421}],
        },
        {
            "name": "heart_rate_variability_sdnn",
            "units": "ms",
            "data": [{"date": "2026-06-09 00:00:00 +0300", "qty": 42.7}],
        },
    ]
    daily = _hae_to_daily_payloads(metrics)
    assert "2026-06-09" in daily
    p = daily["2026-06-09"]
    assert p.heart_rate_avg == 72
    assert p.heart_rate_min == 56
    assert p.heart_rate_max == 130
    assert p.steps == 8421
    assert p.hrv == 43
