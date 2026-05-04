import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "telegram-bot"))

from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock

from webhook.apple_health import app

client = TestClient(app)


def _tg_payload(from_id: int, text: str = None, has_photo: bool = False, has_voice: bool = False):
    msg = {"message_id": 1, "from": {"id": from_id, "first_name": "Test"}, "chat": {"id": from_id}}
    if text:
        msg["text"] = text
    if has_photo:
        msg["photo"] = [{"file_id": "xxx"}]
    if has_voice:
        msg["voice"] = {"file_id": "yyy"}
    return {"update_id": 1, "message": msg}


@patch("webhook.telegram_router.handle_onboarding", new_callable=AsyncMock)
@patch("webhook.telegram_router.SessionLocal")
def test_unknown_user_goes_to_onboarding(MockSession, mock_onboarding):
    db = MagicMock()
    MockSession.return_value = db
    db.query.return_value.filter_by.return_value.first.return_value = None  # new user

    r = client.post("/telegram/webhook", json=_tg_payload(from_id=999999, text="/start"))
    assert r.status_code == 200
    mock_onboarding.assert_awaited_once()


@patch("webhook.telegram_router.forward_to_container", new_callable=AsyncMock)
@patch("webhook.telegram_router.SessionLocal")
def test_known_user_with_container_gets_forwarded(MockSession, mock_forward):
    db = MagicMock()
    MockSession.return_value = db
    user = MagicMock(telegram_id=111111111, container_id="nc-sasha", container_port=8001, is_active=True)
    db.query.return_value.filter_by.return_value.first.return_value = user

    r = client.post("/telegram/webhook", json=_tg_payload(from_id=111111111, text="выпил витамины"))
    assert r.status_code == 200
    mock_forward.assert_awaited_once()


@patch("webhook.telegram_router.forward_to_container", new_callable=AsyncMock)
@patch("webhook.telegram_router.SessionLocal")
def test_photo_returns_ok_without_forward(MockSession, mock_forward):
    db = MagicMock()
    MockSession.return_value = db
    user = MagicMock(telegram_id=111111111, container_id="nc-sasha", container_port=8001, is_active=True)
    db.query.return_value.filter_by.return_value.first.return_value = user

    r = client.post("/telegram/webhook", json=_tg_payload(from_id=111111111, has_photo=True))
    assert r.status_code == 200
    # Photo should NOT be forwarded to container (handled by legacy aiogram)
    mock_forward.assert_not_awaited()


@patch("webhook.telegram_router.SessionLocal")
def test_user_without_container_returns_ok(MockSession):
    """User exists but no container yet — returns 200, no forward."""
    db = MagicMock()
    MockSession.return_value = db
    user = MagicMock(telegram_id=836757955, container_id=None, container_port=None, is_active=True)
    db.query.return_value.filter_by.return_value.first.return_value = user

    r = client.post("/telegram/webhook", json=_tg_payload(from_id=836757955, text="привет"))
    assert r.status_code == 200
