# tests/test_biomarkers_aggregate.py
from core.health.biomarkers import aggregate_biomarkers


def _tests():
    # ascending dates; aggregate must pick LATEST as seen value
    return [
        {"date": "2024-01-01", "values": {"LDL": 3.9, "glucose": 5.0}},
        {"date": "2025-06-01", "values": {"ldl": 3.1}},  # alias + newer
        {"date": "2023-01-01", "values": {"LDL": 4.2}},  # oldest, peak_max
    ]


def test_seen_is_latest_value():
    bio = aggregate_biomarkers(_tests())
    assert bio["LDL"]["value"] == 3.1
    assert bio["LDL"]["date"] == "2025-06-01"


def test_history_peak_earliest():
    bio = aggregate_biomarkers(_tests())
    ldl = bio["LDL"]
    assert ldl["earliest"]["value"] == 4.2 and ldl["earliest"]["date"] == "2023-01-01"
    assert ldl["peak_max"]["value"] == 4.2
    assert ldl["peak_min"]["value"] == 3.1
    assert ldl["n_history"] == 3


def test_single_point_no_history_fields():
    bio = aggregate_biomarkers([{"date": "2025-01-01", "values": {"glucose": 5.0}}])
    assert bio["glucose"]["value"] == 5.0
    assert "peak_max" not in bio["glucose"]


def test_meta():
    bio = aggregate_biomarkers(_tests())
    assert bio["_meta"]["earliest_test_date"] == "2023-01-01"
    assert bio["_meta"]["total_tests"] == 3
    assert bio["_meta"]["total_markers"] == len([k for k in bio if k != "_meta"])
