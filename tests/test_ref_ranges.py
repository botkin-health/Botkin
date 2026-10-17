"""core/health/ref_ranges: флаги по полу, структура данных, инвариант канона (#591)."""

import pytest

from core.health.kb_schema import CANONICAL
from core.health.ref_ranges import REF_RANGES, flag_for, normalize_sex, ref_range


def test_keys_in_canonical():
    assert not [k for k in REF_RANGES if k not in CANONICAL]


@pytest.mark.parametrize(
    "raw,expected",
    [("male", "male"), ("M", "male"), ("female", "female"), (" f ", "female"), (None, None), ("x", None)],
)
def test_normalize_sex(raw, expected):
    assert normalize_sex(raw) == expected


def test_male_bounds_and_flags():
    assert ref_range("Hb", "male") == (130, 170)
    assert flag_for("Hb", 120, "male") == "↓"
    assert flag_for("Hb", 175, "male") == "↑"
    assert flag_for("Hb", 150, "male") == ""
    assert flag_for("Hb", 130, "male") == ""  # границы включительно


def test_female_and_unknown_have_no_flags_until_ranges_added():
    # Женские референсы намеренно не заданы (нужен источник от лаборатории/врача).
    assert all("female" not in v for v in REF_RANGES.values())
    for sex in ("female", None, "other"):
        assert flag_for("Hb", 50, sex) == ""


def test_unknown_marker_and_non_numeric():
    assert flag_for("no_such_marker", 1, "male") == ""
    assert flag_for("Hb", "abc", "male") == ""
    assert flag_for("Hb", None, "male") == ""
