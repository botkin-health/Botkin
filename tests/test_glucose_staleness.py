"""#156: флаг устаревания глюкозы CGM.

CGM пишет ~каждые 5 мин. Разрыв между последней точкой и `now` > порога (30 мин)
ИЛИ пропущенный refresh (cooldown/бан) → данные не считаются текущими, агент
должен это проговаривать.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.health.glucose_stats import GLUCOSE_STALE_THRESHOLD_MIN, glucose_staleness

NOW = datetime(2026, 6, 17, 17, 8, tzinfo=timezone.utc)


def test_fresh_point_not_stale():
    last = NOW - timedelta(minutes=5)
    r = glucose_staleness(last, NOW)
    assert r["is_stale"] is False
    assert r["last_point_age_min"] == 5


def test_gap_over_threshold_is_stale():
    last = NOW - timedelta(hours=8)  # прецедент: 08:59 → 17:08
    r = glucose_staleness(last, NOW)
    assert r["is_stale"] is True
    assert r["last_point_age_min"] == 480


def test_boundary_at_threshold_not_stale():
    """Ровно на пороге (30 мин) — ещё не stale; на минуту больше — stale."""
    assert glucose_staleness(NOW - timedelta(minutes=GLUCOSE_STALE_THRESHOLD_MIN), NOW)["is_stale"] is False
    assert glucose_staleness(NOW - timedelta(minutes=GLUCOSE_STALE_THRESHOLD_MIN + 1), NOW)["is_stale"] is True


def test_refresh_skipped_forces_stale_even_if_recent():
    """refresh_skipped (cooldown/бан) → stale даже при свежей последней точке."""
    last = NOW - timedelta(minutes=5)
    r = glucose_staleness(last, NOW, refresh_skipped=True)
    assert r["is_stale"] is True
    assert r["last_point_age_min"] == 5


def test_no_points_is_stale():
    r = glucose_staleness(None, NOW)
    assert r["is_stale"] is True
    assert r["last_point_age_min"] is None
