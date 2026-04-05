"""Tests for user_settings CRUD operations."""
import pytest
from unittest.mock import MagicMock
from database.crud import get_user_settings, upsert_user_settings
from database.models import UserSettings


def make_db():
    """Return a mock SQLAlchemy session."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    return db


def test_get_user_settings_returns_none_when_missing():
    db = make_db()
    result = get_user_settings(db, user_id=895655)
    assert result is None


def test_upsert_creates_new_settings():
    db = make_db()
    upsert_user_settings(db, user_id=895655, show_calorie_budget_bar=False)
    db.add.assert_called_once()
    db.commit.assert_called_once()


def test_upsert_updates_existing_settings():
    existing = UserSettings(user_id=895655, show_calorie_budget_bar=True)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = existing

    upsert_user_settings(db, user_id=895655, show_calorie_budget_bar=False)
    assert existing.show_calorie_budget_bar == False
    db.commit.assert_called_once()


def test_get_show_bar_default_is_true():
    # server_default='true' — значение по умолчанию при вставке в БД
    from sqlalchemy import inspect
    col = inspect(UserSettings).columns["show_calorie_budget_bar"]
    assert col.server_default.arg == "true"


def test_get_reminders_default_is_false():
    from sqlalchemy import inspect
    col = inspect(UserSettings).columns["supplement_reminders_enabled"]
    assert col.server_default.arg == "false"
