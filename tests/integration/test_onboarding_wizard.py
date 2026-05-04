"""Integration tests for the onboarding wizard (Sprint 1a Task 9)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "telegram-bot"))

import pytest
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.mark.asyncio
@patch("handlers.onboarding.send_message", new_callable=AsyncMock)
@patch("handlers.onboarding.SessionLocal")
async def test_new_user_creates_row_and_asks_name(MockSession, mock_send):
    """New user: creates row in DB and asks for name."""
    db = MagicMock()
    MockSession.return_value = db
    db.query.return_value.filter_by.return_value.first.return_value = None  # not in DB

    from handlers.onboarding import process_onboarding_message

    payload = {
        "message": {
            "from": {"id": 999888, "first_name": "NewUser", "username": "newuser"},
            "chat": {"id": 999888},
            "text": "/start",
        }
    }
    await process_onboarding_message(payload)

    db.add.assert_called_once()
    mock_send.assert_awaited_once()
    # Message should mention "имя" or greeting
    sent_text = mock_send.call_args.args[1]
    assert any(word in sent_text.lower() for word in ["привет", "имя", "зовут"])


@pytest.mark.asyncio
@patch("handlers.onboarding.send_message", new_callable=AsyncMock)
@patch("handlers.onboarding.SessionLocal")
async def test_age_step_advances_on_valid_number(MockSession, mock_send):
    """User in 'age' step sends valid age → advances to 'sex' step."""
    db = MagicMock()
    MockSession.return_value = db
    user = MagicMock(telegram_id=999888, onboarding_step="age", onboarding_data={"name": "Андрей"})
    db.query.return_value.filter_by.return_value.first.return_value = user

    from handlers.onboarding import process_onboarding_message

    payload = {"message": {"from": {"id": 999888}, "chat": {"id": 999888}, "text": "35"}}
    await process_onboarding_message(payload)

    assert user.onboarding_step == "sex"
    mock_send.assert_awaited_once()


@pytest.mark.asyncio
@patch("handlers.onboarding.send_message", new_callable=AsyncMock)
@patch("handlers.onboarding.SessionLocal")
async def test_age_step_rejects_invalid(MockSession, mock_send):
    """User in 'age' step sends non-number → stays at 'age'."""
    db = MagicMock()
    MockSession.return_value = db
    user = MagicMock(telegram_id=999888, onboarding_step="age", onboarding_data={"name": "Андрей"})
    db.query.return_value.filter_by.return_value.first.return_value = user

    from handlers.onboarding import process_onboarding_message

    payload = {"message": {"from": {"id": 999888}, "chat": {"id": 999888}, "text": "не число"}}
    await process_onboarding_message(payload)

    assert user.onboarding_step == "age"  # didn't advance


@pytest.mark.asyncio
@patch("handlers.onboarding.send_message", new_callable=AsyncMock)
@patch("handlers.onboarding.SessionLocal")
async def test_has_garmin_step_completes_onboarding(MockSession, mock_send):
    """Last step: user gets health_token in message."""
    db = MagicMock()
    MockSession.return_value = db
    user = MagicMock(
        telegram_id=999888,
        onboarding_step="has_garmin",
        onboarding_data={"name": "Андрей", "age": 35, "sex": "M", "height_cm": 178},
        health_token=None,
    )
    db.query.return_value.filter_by.return_value.first.return_value = user

    from handlers.onboarding import process_onboarding_message

    payload = {"message": {"from": {"id": 999888}, "chat": {"id": 999888}, "text": "Нет"}}
    await process_onboarding_message(payload)

    assert user.onboarding_step == "done"
    assert user.health_token is not None
    assert user.health_token.startswith("hvt_999888_")
    # Check that health_token is mentioned in the final message
    sent_text = mock_send.call_args.args[1]
    assert "hvt_" in sent_text or "health" in sent_text.lower()
