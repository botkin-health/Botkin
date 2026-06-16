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
async def test_birth_date_step_advances_on_valid_date(MockSession, mock_send):
    """User in 'birth_date' step sends valid date → advances to 'sex' step.

    Возраст в текущей FSM выводится из даты рождения (шаг 2/10), отдельного
    шага 'age' нет — см. handlers.onboarding._run_step.
    """
    db = MagicMock()
    MockSession.return_value = db
    user = MagicMock(telegram_id=999888, onboarding_step="birth_date", onboarding_data={"name": "Андрей"})
    db.query.return_value.filter_by.return_value.first.return_value = user

    from handlers.onboarding import process_onboarding_message

    payload = {"message": {"from": {"id": 999888}, "chat": {"id": 999888}, "text": "20.08.1990"}}
    await process_onboarding_message(payload)

    assert user.onboarding_step == "sex"
    # Возраст посчитан из даты рождения и записан в onboarding_data
    assert isinstance(user.onboarding_data.get("age"), int)
    mock_send.assert_awaited_once()


@pytest.mark.asyncio
@patch("handlers.onboarding.send_message", new_callable=AsyncMock)
@patch("handlers.onboarding.SessionLocal")
async def test_birth_date_step_rejects_invalid(MockSession, mock_send):
    """User in 'birth_date' step sends garbage → stays at 'birth_date'."""
    db = MagicMock()
    MockSession.return_value = db
    user = MagicMock(telegram_id=999888, onboarding_step="birth_date", onboarding_data={"name": "Андрей"})
    db.query.return_value.filter_by.return_value.first.return_value = user

    from handlers.onboarding import process_onboarding_message

    payload = {"message": {"from": {"id": 999888}, "chat": {"id": 999888}, "text": "не дата"}}
    await process_onboarding_message(payload)

    assert user.onboarding_step == "birth_date"  # didn't advance
    mock_send.assert_awaited_once()  # re-prompted with format hint


@pytest.mark.asyncio
@patch("handlers.onboarding.send_message", new_callable=AsyncMock)
@patch("handlers.onboarding.SessionLocal")
async def test_wearables_step_completes_onboarding(MockSession, mock_send):
    """Last step ('wearables'): «Нет» finishes onboarding and issues health_token.

    Завершение в текущей FSM происходит на шаге 'wearables' (ответ «Нет»/«Готово»),
    отдельного шага 'has_garmin' нет — см. handlers.onboarding._run_step / _finish_onboarding.
    """
    db = MagicMock()
    MockSession.return_value = db
    user = MagicMock(
        telegram_id=999888,
        onboarding_step="wearables",
        onboarding_data={"name": "Андрей", "age": 35, "sex": "M", "height_cm": 178},
        birth_date=None,  # возраст берётся из onboarding_data, без арифметики над MagicMock
        health_token=None,
    )
    db.query.return_value.filter_by.return_value.first.return_value = user

    from handlers.onboarding import process_onboarding_message

    payload = {"message": {"from": {"id": 999888}, "chat": {"id": 999888}, "text": "Нет"}}
    await process_onboarding_message(payload)

    assert user.onboarding_step == "done"
    assert user.health_token is not None
    assert user.health_token.startswith("hvt_999888_")
    # Финальная сводка отправлена. Сырой health_token в чат больше НЕ печатается
    # (он отдаётся через мини-аппу / apple-connect), поэтому проверяем сам факт
    # сообщения о завершении, а не наличие токена в тексте.
    sent_text = mock_send.call_args.args[1]
    assert "Готово" in sent_text
