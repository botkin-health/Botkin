"""Integration tests for /telegram/webhook routing.

After ADR-0002 (21.05.2026) NanoClaw was removed. The router no longer has a
forward-to-container path — all known users route to legacy aiogram dispatcher
where BotkinClaw (in-process AI agent) lives.
"""

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


@patch("webhook.telegram_router._feed_legacy_bot", new_callable=AsyncMock)
@patch("webhook.telegram_router.SessionLocal")
def test_known_user_text_goes_to_legacy(MockSession, mock_feed):
    """Known user text routes to legacy aiogram (BotkinClaw lives there)."""
    db = MagicMock()
    MockSession.return_value = db
    user = MagicMock(
        telegram_id=111111111,
        username="testuser",
        container_id=None,
        container_port=None,
        is_active=True,
        onboarding_step="done",
    )
    db.query.return_value.filter_by.return_value.first.return_value = user

    r = client.post("/telegram/webhook", json=_tg_payload(from_id=111111111, text="выпил витамины"))
    assert r.status_code == 200
    assert r.json()["action"] == "legacy_text"
    mock_feed.assert_awaited()


@patch("webhook.telegram_router._feed_legacy_bot", new_callable=AsyncMock)
@patch("webhook.telegram_router.SessionLocal")
def test_photo_goes_to_legacy_media(MockSession, mock_feed):
    """Photo messages always go to legacy aiogram (photo handler lives there)."""
    db = MagicMock()
    MockSession.return_value = db
    user = MagicMock(
        telegram_id=111111111,
        username="testuser",
        container_id=None,
        container_port=None,
        is_active=True,
        onboarding_step="done",
    )
    db.query.return_value.filter_by.return_value.first.return_value = user

    r = client.post("/telegram/webhook", json=_tg_payload(from_id=111111111, has_photo=True))
    assert r.status_code == 200
    assert r.json()["action"] == "legacy_media"
    mock_feed.assert_awaited()


@patch("webhook.telegram_router.handle_onboarding", new_callable=AsyncMock)
@patch("webhook.telegram_router.SessionLocal")
def test_user_in_onboarding_continues_wizard(MockSession, mock_onboarding):
    """User with onboarding_step != 'done' routes to onboarding."""
    db = MagicMock()
    MockSession.return_value = db
    user = MagicMock(
        telegram_id=222222222,
        username="testuser",
        container_id=None,
        container_port=None,
        is_active=True,
        onboarding_step="age",
    )
    db.query.return_value.filter_by.return_value.first.return_value = user

    r = client.post("/telegram/webhook", json=_tg_payload(from_id=222222222, text="35"))
    assert r.status_code == 200
    assert r.json()["action"] == "onboarding_continue"
    mock_onboarding.assert_awaited_once()
