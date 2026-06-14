"""Tests for height routing into body_measurements (PR #73, issue #43).

Guards the fix where «рост 171» was silently lost:
- height is a PROFILE field (users.height_cm), not a body circumference;
- a height-only message must NOT create an empty body-measurement row (which
  also clobbered a real same-day JSON entry);
- an implausible height (outside 100–250) is rejected, not silently "saved".
"""

import pytest

from helpers.db_save import save_body_measurement_to_db, valid_height_cm


# --- valid_height_cm (pure) -------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        (171, 171),
        ("171", 171),
        (171.5, 171),  # float tolerated, truncated
        ("175.0", 175),
        (100, 100),  # lower bound inclusive
        (250, 250),  # upper bound inclusive
    ],
)
def test_valid_height_returns_int(raw, expected):
    assert valid_height_cm(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "abc", 0, 70, 99, 251, 400, "рост"])
def test_invalid_height_returns_none(raw):
    assert valid_height_cm(raw) is None


# --- save_body_measurement_to_db (DB) ---------------------------------------


@pytest.fixture
def patched_db(test_db, monkeypatch):
    """Point helpers.db_save at the in-memory DB; keep the session open across
    the function's own db.close(); skip the JSON-file side effect."""
    import helpers.db_save as mod

    monkeypatch.setattr(test_db, "close", lambda: None)
    monkeypatch.setattr(mod, "SessionLocal", lambda: test_db)
    monkeypatch.setattr(mod, "save_body_measurement_to_json", lambda data: None)
    return test_db


def _make_user(db, telegram_id=999):
    from database.models import User

    user = User(telegram_id=telegram_id, height_cm=None)
    db.add(user)
    db.commit()
    return user


def _count_measurements(db, user_id):
    from database.models import BodyMeasurement

    return db.query(BodyMeasurement).filter(BodyMeasurement.user_id == user_id).count()


def test_height_only_updates_profile_without_measurement_row(patched_db):
    user = _make_user(patched_db)

    ok = save_body_measurement_to_db({"height_cm": 171}, user_id=user.telegram_id)

    assert ok is True
    assert user.height_cm == 171
    assert _count_measurements(patched_db, user.telegram_id) == 0


def test_out_of_range_height_is_not_saved(patched_db):
    user = _make_user(patched_db)
    user.height_cm = 180
    patched_db.commit()

    ok = save_body_measurement_to_db({"height_cm": 70}, user_id=user.telegram_id)

    assert ok is True
    assert user.height_cm == 180  # unchanged — implausible value rejected
    assert _count_measurements(patched_db, user.telegram_id) == 0


def test_circumference_creates_measurement_row(patched_db):
    user = _make_user(patched_db)

    ok = save_body_measurement_to_db({"waist_cm": 85}, user_id=user.telegram_id)

    assert ok is True
    assert _count_measurements(patched_db, user.telegram_id) == 1


def test_height_plus_circumference_does_both(patched_db):
    user = _make_user(patched_db)

    ok = save_body_measurement_to_db({"height_cm": 176, "waist_cm": 80}, user_id=user.telegram_id)

    assert ok is True
    assert user.height_cm == 176
    assert _count_measurements(patched_db, user.telegram_id) == 1
