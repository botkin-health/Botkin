"""Тесты возрастной коррекции пожизненного ASCVD-риска (calc_ascvd_lifetime).

Фокус — возрастной множитель risk_pct (баг dead-branch для 70-79, см. PR #240 follow-up):
порядок elif `age >= 60` поглощал диапазон 60-79, из-за чего 70-79 получали ×0.92
вместо задуманного ×0.80.
"""

from core.health.cv_risk import calc_ascvd_lifetime


def _one_major_male(age: int) -> dict:
    """Профиль мужчины с ровно ОДНИМ major-фактором (курение) → базовый risk 50.0.

    Все остальные параметры оптимальны, чтобы изолировать возрастной множитель.
    """
    return calc_ascvd_lifetime(
        age=age,
        sex="male",
        smoking=True,  # единственный major
        sbp_mmhg=110,  # optimal (<120)
        tchol_mmolL=4.5,  # optimal (<4.7)
        hdl_mmolL=1.5,  # optimal (>= 1.0 + 0.3)
        diabetes=False,
    )


def test_age_70_79_applies_0_80_multiplier():
    """70-79 лет: базовый 50.0 × 0.80 = 40.0 (а не ×0.92 → 46.0)."""
    result = _one_major_male(age=72)
    assert result["risk_pct"] == 40.0


def test_age_70_boundary_applies_0_80_multiplier():
    """Граница ровно 70 лет попадает в ветку ×0.80."""
    result = _one_major_male(age=70)
    assert result["risk_pct"] == 40.0


def test_age_60_69_applies_0_92_multiplier():
    """60-69 лет: базовый 50.0 × 0.92 = 46.0 (фикс 70+ не задел этот диапазон)."""
    result = _one_major_male(age=65)
    assert result["risk_pct"] == 46.0


def test_age_50_59_applies_no_multiplier():
    """50-59 лет: множитель не применяется, базовый 50.0 без изменений."""
    result = _one_major_male(age=55)
    assert result["risk_pct"] == 50.0


def test_age_under_50_applies_1_05_multiplier():
    """<50 лет: базовый 50.0 × 1.05 = 52.5."""
    result = _one_major_male(age=45)
    assert result["risk_pct"] == 52.5
