import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

from unittest.mock import MagicMock


def test_has_garmin_data_false_for_no_garmin_no_activity():
    from dashboard_blocks import has_garmin_data

    user = MagicMock(garmin_email=None, telegram_id=999)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    assert has_garmin_data(db, user) is False


def test_has_garmin_data_true_when_email_set():
    from dashboard_blocks import has_garmin_data

    user = MagicMock(garmin_email="test@garmin.com", telegram_id=999)
    db = MagicMock()
    assert has_garmin_data(db, user) is True


def test_has_garmin_data_true_when_activity_exists():
    from dashboard_blocks import has_garmin_data

    user = MagicMock(garmin_email=None, telegram_id=999)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = MagicMock(steps=8000)
    assert has_garmin_data(db, user) is True


def test_has_nutrition_data_false_when_no_rows():
    from dashboard_blocks import has_nutrition_data

    user = MagicMock(telegram_id=999)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    assert has_nutrition_data(db, user) is False


def test_has_weight_data_true_when_row_exists():
    from dashboard_blocks import has_weight_data

    user = MagicMock(telegram_id=999)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = MagicMock()
    assert has_weight_data(db, user) is True
