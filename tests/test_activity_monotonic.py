"""
Regression test for the monotonic guard in create_or_update_activity.

Bug (2026-06-16): a get_stats() race let a partial mid-sync Garmin snapshot
(steps=284, active=63, total=835) overwrite the full day already stored
(steps=7823, active=258, total=2109). Cumulative daily metrics must only grow.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import Base
from database.crud import create_or_update_activity


@pytest.fixture
def engine():
    e = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(e)
    yield e
    e.dispose()


@pytest.fixture
def db_session(engine):
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    s = Session()
    yield s
    s.close()


UID = 895655
D = date(2026, 6, 16)


def _full_day(db):
    return create_or_update_activity(
        db,
        user_id=UID,
        date=D,
        steps=7823,
        active_calories=258,
        total_calories=2109,
        bmr_calories=1851,
        distance_km=6.096,
        source="garmin_connect",
    )


def test_partial_sync_does_not_clobber_full_day(db_session):
    """The reported bug: partial snapshot must not lower stored cumulative values."""
    _full_day(db_session)

    # Partial mid-sync snapshot arrives ~2 min later, all counters tiny.
    row = create_or_update_activity(
        db_session,
        user_id=UID,
        date=D,
        steps=284,
        active_calories=63,
        total_calories=835,
        bmr_calories=772,
        distance_km=0.2,
        source="garmin_connect",
    )

    assert row.steps == 7823
    assert row.active_calories == 258
    assert row.total_calories == 2109
    assert row.bmr_calories == 1851
    assert row.distance_km == 6.096


def test_growth_within_day_is_applied(db_session):
    """Normal intraday progression: higher values overwrite as usual."""
    create_or_update_activity(
        db_session,
        user_id=UID,
        date=D,
        steps=3000,
        active_calories=80,
        total_calories=1000,
        bmr_calories=900,
        source="garmin_connect",
    )
    row = create_or_update_activity(
        db_session,
        user_id=UID,
        date=D,
        steps=7823,
        active_calories=258,
        total_calories=2109,
        bmr_calories=1851,
        source="garmin_connect",
    )
    assert row.steps == 7823
    assert row.active_calories == 258
    assert row.total_calories == 2109


def test_non_cumulative_fields_always_overwrite(db_session):
    """Averages/snapshots (stress, HR, sleep) must update even when lower."""
    create_or_update_activity(
        db_session,
        user_id=UID,
        date=D,
        steps=7823,
        stress_level=80,
        heart_rate_avg=70,
        sleep_hours=8.0,
        source="garmin_connect",
    )
    row = create_or_update_activity(
        db_session,
        user_id=UID,
        date=D,
        steps=7823,
        stress_level=34,
        heart_rate_avg=58,
        sleep_hours=6.5,
        source="garmin_connect",
    )
    assert row.stress_level == 34
    assert row.heart_rate_avg == 58
    assert row.sleep_hours == 6.5


def test_monotonic_false_allows_manual_correction(db_session):
    """Explicit override (backfill/manual fix) must overwrite unconditionally."""
    _full_day(db_session)
    row = create_or_update_activity(
        db_session,
        user_id=UID,
        date=D,
        steps=100,
        active_calories=10,
        total_calories=500,
        bmr_calories=400,
        source="manual_fix",
        monotonic=False,
    )
    assert row.steps == 100
    assert row.active_calories == 10
