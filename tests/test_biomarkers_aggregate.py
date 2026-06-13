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


# --- staleness fields ---

def test_aggregate_includes_staleness_fields():
    from datetime import date, timedelta
    old_date = (date.today() - timedelta(days=400)).isoformat()
    bio = aggregate_biomarkers([{"date": old_date, "values": {"vitamin_D": 32.5}}])
    vd = bio["vitamin_D"]
    assert "days_ago" in vd
    assert "staleness_threshold_days" in vd
    assert "is_stale" in vd


def test_aggregate_stale_is_true_when_old():
    from datetime import date, timedelta
    # vitamin_D threshold = 365; 400 days > 365 → is_stale=True
    old_date = (date.today() - timedelta(days=400)).isoformat()
    bio = aggregate_biomarkers([{"date": old_date, "values": {"vitamin_D": 32.5}}])
    assert bio["vitamin_D"]["is_stale"] is True
    assert bio["vitamin_D"]["days_ago"] == 400
    assert bio["vitamin_D"]["staleness_threshold_days"] == 365


def test_aggregate_is_stale_false_when_fresh():
    from datetime import date, timedelta
    recent_date = (date.today() - timedelta(days=10)).isoformat()
    bio = aggregate_biomarkers([{"date": recent_date, "values": {"vitamin_D": 45.0}}])
    assert bio["vitamin_D"]["is_stale"] is False


def test_aggregate_none_threshold_means_never_stale():
    from core.health.staleness import stale_label
    # Verify the stale_label function (used internally) returns None for None threshold
    assert stale_label(99999, None) is None
