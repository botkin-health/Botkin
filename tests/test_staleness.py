# tests/test_staleness.py
from datetime import date, timedelta


class TestGetStalenessDays:
    def test_vitamin_d_is_365(self):
        from core.health.staleness import get_staleness_days

        assert get_staleness_days("vitamin_D") == 365

    def test_hba1c_is_180(self):
        from core.health.staleness import get_staleness_days

        assert get_staleness_days("HbA1c") == 180

    def test_weight_is_60(self):
        from core.health.staleness import get_staleness_days

        assert get_staleness_days("weight") == 60

    def test_ldl_is_730(self):
        from core.health.staleness import get_staleness_days

        assert get_staleness_days("LDL") == 730

    def test_lipoprotein_a_is_1460(self):
        from core.health.staleness import get_staleness_days

        assert get_staleness_days("lipoprotein_a") == 1460

    def test_height_is_none(self):
        from core.health.staleness import get_staleness_days

        assert get_staleness_days("height_cm") is None

    def test_unknown_key_returns_default(self):
        from core.health.staleness import get_staleness_days, DEFAULT_STALENESS_DAYS

        assert get_staleness_days("unknown_xyzzy_marker") == DEFAULT_STALENESS_DAYS


class TestDaysAgoFromStr:
    def test_30_days_ago(self):
        from core.health.staleness import days_ago_from_str

        d = (date.today() - timedelta(days=30)).isoformat()
        assert days_ago_from_str(d) == 30

    def test_none_input(self):
        from core.health.staleness import days_ago_from_str

        assert days_ago_from_str(None) is None

    def test_dash_input(self):
        from core.health.staleness import days_ago_from_str

        assert days_ago_from_str("—") is None

    def test_invalid_string(self):
        from core.health.staleness import days_ago_from_str

        assert days_ago_from_str("not-a-date") is None

    def test_today_is_zero(self):
        from core.health.staleness import days_ago_from_str

        assert days_ago_from_str(date.today().isoformat()) == 0


class TestStaleLabel:
    def test_fresh_returns_none(self):
        from core.health.staleness import stale_label

        assert stale_label(100, 365) is None

    def test_exactly_at_threshold_is_none(self):
        from core.health.staleness import stale_label

        assert stale_label(365, 365) is None

    def test_one_over_threshold_is_warning(self):
        from core.health.staleness import stale_label

        label = stale_label(366, 365)
        assert label is not None
        assert "⚠" in label

    def test_moderate_stale_shows_months(self):
        from core.health.staleness import stale_label

        label = stale_label(400, 365)
        assert "⚠" in label
        assert "мес" in label
        assert "13" in label  # 400 // 30 = 13

    def test_very_stale_shows_alarm(self):
        from core.health.staleness import stale_label

        label = stale_label(800, 365)
        assert "🚨" in label

    def test_none_threshold_always_none(self):
        from core.health.staleness import stale_label

        assert stale_label(5000, None) is None

    def test_none_days_is_none(self):
        from core.health.staleness import stale_label

        assert stale_label(None, 365) is None

    def test_weight_threshold_60_fresh(self):
        from core.health.staleness import stale_label

        assert stale_label(30, 60) is None

    def test_weight_threshold_60_stale(self):
        from core.health.staleness import stale_label

        assert stale_label(90, 60) is not None
