# tests/test_kb_schema.py
import math
from core.health.kb_schema import to_canonical, CANONICAL, reverse_index


def test_alexander_camelcase_keys_map():
    canon, warnings = to_canonical({"LDL": 3.1, "ALT": 22, "TSH": 2.0})
    assert canon["LDL"] == 3.1
    assert canon["ALT"] == 22
    assert canon["TSH"] == 2.0
    assert warnings == []


def test_dima_snake_with_units_map_same_unit():
    canon, _ = to_canonical({"ldl_mmol_l": 3.1, "glucose_mmol_l": 5.0, "creatinine_umol_l": 90, "alt_u_l": 22})
    assert canon["LDL"] == 3.1
    assert canon["glucose"] == 5.0
    assert canon["creatinine"] == 90
    assert canon["ALT"] == 22


def test_case_insensitive():
    canon, _ = to_canonical({"alt": 30})
    assert canon["ALT"] == 30


def test_unit_conversion_insulin_pmol_to_uiu():
    # 100 pmol/L ÷ 6.945 ≈ 14.4 µIU/mL
    canon, _ = to_canonical({"insulin_pmol_l": 100.0})
    assert math.isclose(canon["insulin"], 100.0 / 6.945, rel_tol=1e-6)


def test_unit_conversion_folate_pth_b12():
    canon, _ = to_canonical({"folate_nmol_l": 20.0, "pth_pmol_l": 5.0, "vitamin_b12_pmol_l": 300.0})
    assert math.isclose(canon["folic_acid"], 20.0 / 2.266, rel_tol=1e-6)
    assert math.isclose(canon["PTH_intact"], 5.0 * 9.434, rel_tol=1e-6)
    assert math.isclose(canon["vitamin_B12"], 300.0 * 1.355, rel_tol=1e-6)


def test_albumin_pct_not_collapsed_into_albumin_g_l():
    # albumin_pct is a DIFFERENT marker (electrophoresis %), must NOT map to albumin_g_l
    canon, warnings = to_canonical({"albumin_pct": 60.0, "albumin_g_l": 42.0})
    assert canon["albumin_g_l"] == 42.0
    assert "albumin_pct" not in reverse_index()  # not a registered alias


def test_unknown_unit_alias_skipped_with_warning():
    canon, warnings = to_canonical({"insulin_some_weird_unit": 5.0})
    assert "insulin_some_weird_unit" not in canon
    assert canon == {}
    assert any("insulin_some_weird_unit" in w for w in warnings)


def test_passthrough_unmapped():
    canon, _ = to_canonical({"fibrinogen_g_l": 3.0}, passthrough_unmapped=True)
    assert canon["fibrinogen_g_l"] == 3.0  # passed through untouched


def test_no_passthrough_drops_unmapped():
    canon, _ = to_canonical({"fibrinogen_g_l": 3.0})
    assert "fibrinogen_g_l" not in canon


def test_collision_same_value_no_warning():
    canon, warnings = to_canonical({"LDL": 3.1, "ldl": 3.1})
    assert canon["LDL"] == 3.1
    assert warnings == []


def test_collision_different_value_warns():
    canon, warnings = to_canonical({"LDL": 3.1, "ldl": 9.9})
    assert any("LDL" in w for w in warnings)


def test_reverse_index_has_no_duplicate_aliases():
    # Invariant: each lowercased alias belongs to exactly one canonical key.
    seen = {}
    for canon_key, marker in CANONICAL.items():
        for alias in marker.aliases:
            a = alias.lower()
            assert a not in seen, f"duplicate alias {alias!r}: {seen.get(a)} vs {canon_key}"
            seen[a] = canon_key


def test_non_numeric_value_skipped():
    canon, _ = to_canonical({"LDL": "n/a"})
    assert "LDL" not in canon
