"""#347-класс: webhook не держит сессию Postgres поперёк обработчиков и не отдаёт 5xx
Telegram (иначе update повторяется и разбирается дважды — прецедент 08.09.2026)."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

SECRET = "webhook-secret-abc123"
HEADERS = {"X-Telegram-Bot-Api-Secret-Token": SECRET}
PHOTO_UPDATE = {
    "update_id": 7,
    "message": {
        "message_id": 1,
        "from": {"id": 895655, "username": "lyskovsky"},
        "chat": {"id": 895655},
        "photo": [{}],
    },
}
TEXT_UPDATE = {
    "update_id": 8,
    "message": {
        "message_id": 2,
        "from": {"id": 895655, "username": "lyskovsky"},
        "chat": {"id": 895655},
        "text": "привет",
    },
}


def _fake_session(events, user):
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = user
    db.close.side_effect = lambda: events.append("db_closed")
    return db


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
    from webhook import telegram_router

    app = FastAPI()
    app.include_router(telegram_router.router)
    return TestClient(app), telegram_router


def test_db_session_closed_before_legacy_dispatch(client):
    tc, router = client
    events = []
    user = MagicMock(username="lyskovsky", onboarding_step="done")

    async def fake_feed(payload):
        events.append("dispatch")

    with (
        patch.object(router, "SessionLocal", return_value=_fake_session(events, user)),
        patch.object(router, "_feed_legacy_bot", side_effect=fake_feed),
    ):
        r = tc.post("/telegram/webhook", json=PHOTO_UPDATE, headers=HEADERS)
    assert r.status_code == 200 and r.json()["action"] == "legacy_media"
    assert events == ["db_closed", "dispatch"], events


def test_handler_exception_returns_200_not_5xx(client):
    tc, router = client
    events = []
    user = MagicMock(username="lyskovsky", onboarding_step="done")
    with (
        patch.object(router, "SessionLocal", return_value=_fake_session(events, user)),
        patch.object(router, "_feed_legacy_bot", side_effect=AsyncMock(side_effect=RuntimeError("boom"))),
    ):
        r = tc.post("/telegram/webhook", json=TEXT_UPDATE, headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["status"] == "error_logged"


def test_new_user_goes_to_onboarding_after_db_closed(client):
    tc, router = client
    events = []

    async def fake_onboarding(payload):
        events.append("onboarding")

    with (
        patch.object(router, "SessionLocal", return_value=_fake_session(events, None)),
        patch.object(router, "handle_onboarding", side_effect=fake_onboarding),
    ):
        r = tc.post("/telegram/webhook", json=TEXT_UPDATE, headers=HEADERS)
    assert r.json()["action"] == "onboarding" and events == ["db_closed", "onboarding"]
