import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "telegram-bot"))

import pytest
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.mark.asyncio
@patch("handlers.first_food.log_event")
@patch("handlers.first_food.SessionLocal")
async def test_celebrates_and_clears_flag_when_pending(MockSession, mock_le):
    db = MagicMock()
    MockSession.return_value = db
    user = MagicMock(telegram_id=5, onboarding_data={"first_food_pending": True})
    db.query.return_value.filter_by.return_value.first.return_value = user
    from handlers.first_food import record_first_food

    message = MagicMock(answer=AsyncMock())
    await record_first_food(5, message)

    # E5 залогирован (once)
    assert any(c.kwargs.get("event") == "first_food_logged" for c in mock_le.call_args_list)
    # флаг снят
    assert user.onboarding_data.get("first_food_pending") is not True
    # празднующая строка отправлена
    message.answer.assert_awaited()
    assert "команд" in message.answer.call_args.args[0].lower()


@pytest.mark.asyncio
@patch("handlers.first_food.log_event")
@patch("handlers.first_food.SessionLocal")
async def test_logs_e5_but_no_message_when_not_pending(MockSession, mock_le):
    db = MagicMock()
    MockSession.return_value = db
    user = MagicMock(telegram_id=6, onboarding_data={})  # флага нет
    db.query.return_value.filter_by.return_value.first.return_value = user
    from handlers.first_food import record_first_food

    message = MagicMock(answer=AsyncMock())
    await record_first_food(6, message)

    # E5 всё равно логируется (это событие активации, once)
    assert any(c.kwargs.get("event") == "first_food_logged" for c in mock_le.call_args_list)
    # но празднования нет
    message.answer.assert_not_awaited()
