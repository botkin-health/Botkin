"""Модели CGM-глюкозы: glucose_readings + cgm_connections (#96)."""

from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from database.models import CgmConnection, GlucoseReading, User


def _make_user(db, telegram_id=111):
    db.add(User(telegram_id=telegram_id, first_name="T"))
    db.commit()


def test_insert_glucose_reading(test_db):
    _make_user(test_db)
    test_db.add(
        GlucoseReading(
            user_id=111,
            ts=datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc),
            value=5.4,
            trend=3,
        )
    )
    test_db.commit()

    got = test_db.query(GlucoseReading).one()
    assert float(got.value) == 5.4
    assert got.trend == 3
    assert got.source == "librelinkup"  # default


def test_glucose_unique_user_ts(test_db):
    """(user_id, ts) уникальна — основа idempotent-upsert импортёра."""
    _make_user(test_db)
    ts = datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc)
    test_db.add(GlucoseReading(user_id=111, ts=ts, value=5.0))
    test_db.commit()

    test_db.add(GlucoseReading(user_id=111, ts=ts, value=6.0))
    with pytest.raises(IntegrityError):
        test_db.commit()
    test_db.rollback()


def test_cgm_connection_patient_id_unique(test_db):
    """patient_id уникален — один follower не маппится на двух юзеров."""
    _make_user(test_db)
    test_db.add(CgmConnection(patient_id="999b0098-6ac0-11ee-89dc-f22a02593d8c", telegram_id=111))
    test_db.commit()

    test_db.add(CgmConnection(patient_id="999b0098-6ac0-11ee-89dc-f22a02593d8c", telegram_id=111))
    with pytest.raises(IntegrityError):
        test_db.commit()
    test_db.rollback()
