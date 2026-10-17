"""Tests for POST /api/feedback — кнопка фидбека в мини-аппе (#271).

Третий канал захвата инбокса #188 (после /feedback command и agent flag_for_devs).
Проверяет: запись source='webapp', валидацию текста/kind, opt-out-гейт, auth (initData).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import Base, UserFeedback, UserSettings


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)


@pytest.fixture
def api_db(engine):
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def app_and_db(api_db, monkeypatch):
    import database
    from webhook import feedback_api

    # Endpoint calls SessionLocal() then db.close(); keep the test session alive.
    monkeypatch.setattr(api_db, "close", lambda: None)
    monkeypatch.setattr(database, "SessionLocal", lambda: api_db)

    app = FastAPI()
    app.include_router(feedback_api.router)
    return app, api_db


@pytest.fixture
def client(app_and_db):
    from webhook.tg_auth import get_tg_user

    app, _ = app_and_db
    app.dependency_overrides[get_tg_user] = lambda: {"id": 895655}
    return TestClient(app)


def test_creates_webapp_feedback(client, app_and_db):
    _, db = app_and_db
    r = client.post("/api/feedback", json={"text": "Кнопка не работает", "kind": "bug"})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    rows = db.query(UserFeedback).all()
    assert len(rows) == 1
    assert rows[0].user_id == 895655
    assert rows[0].source == "webapp"
    assert rows[0].kind == "bug"
    assert rows[0].text == "Кнопка не работает"


def test_kind_defaults_to_unspecified(client, app_and_db):
    _, db = app_and_db
    r = client.post("/api/feedback", json={"text": "просто идея"})
    assert r.status_code == 200
    assert db.query(UserFeedback).one().kind == "unspecified"


def test_text_is_stripped(client, app_and_db):
    _, db = app_and_db
    client.post("/api/feedback", json={"text": "  хвостатый  ", "kind": "feature"})
    assert db.query(UserFeedback).one().text == "хвостатый"


def test_empty_text_rejected(client, app_and_db):
    _, db = app_and_db
    r = client.post("/api/feedback", json={"text": "   ", "kind": "bug"})
    assert r.status_code == 422
    assert db.query(UserFeedback).count() == 0


def test_invalid_kind_rejected(client, app_and_db):
    _, db = app_and_db
    r = client.post("/api/feedback", json={"text": "x", "kind": "spam"})
    assert r.status_code == 422
    assert db.query(UserFeedback).count() == 0


def test_opt_out_user_not_stored(client, app_and_db):
    _, db = app_and_db
    db.add(UserSettings(user_id=895655, feedback_opt_out=True))
    db.commit()
    r = client.post("/api/feedback", json={"text": "не хочу", "kind": "bug"})
    assert r.status_code == 200
    assert r.json()["status"] == "opted_out"
    assert db.query(UserFeedback).count() == 0


def test_requires_auth(app_and_db):
    """Без override get_tg_user реальная зависимость отвергает запрос."""
    app, _ = app_and_db
    c = TestClient(app)
    # нет заголовка Authorization → 422 (required Header)
    assert c.post("/api/feedback", json={"text": "x"}).status_code == 422
    # битый initData → 403 (HMAC mismatch)
    r = c.post("/api/feedback", json={"text": "x"}, headers={"Authorization": "tma deadbeef"})
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Вложения (multipart)
# ---------------------------------------------------------------------------

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def fake_bot(monkeypatch):
    from webhook import feedback_api

    bot = MagicMock()
    bot.send_message = AsyncMock()
    bot.send_photo = AsyncMock(return_value=SimpleNamespace(photo=[SimpleNamespace(file_id="ph1")]))
    bot.send_document = AsyncMock(return_value=SimpleNamespace(document=SimpleNamespace(file_id="doc1")))
    bot.session.close = AsyncMock()
    monkeypatch.setattr(feedback_api, "_make_bot", lambda: bot)
    monkeypatch.setattr(feedback_api, "_admin_id", lambda: 111)
    return bot


def _post(client, files, text="Смотрите скрин", kind="bug"):
    return client.post("/api/feedback", data={"text": text, "kind": kind}, files=files)


PNG = ("shot.png", b"\x89PNG-bytes", "image/png")


def test_multipart_with_image_sends_photo(client, app_and_db, fake_bot):
    _, db = app_and_db
    r = _post(client, [("files", PNG)])
    assert r.status_code == 200 and r.json()["status"] == "ok"
    fake_bot.send_message.assert_awaited_once()
    fake_bot.send_photo.assert_awaited_once()
    fake_bot.send_document.assert_not_awaited()
    row = db.query(UserFeedback).one()
    assert row.kind == "bug" and row.text == "Смотрите скрин"
    assert row.attachments == [{"name": "shot.png", "mime": "image/png", "size": 10, "file_id": "ph1"}]


def test_multipart_pdf_and_heic_sent_as_documents(client, fake_bot):
    r = _post(client, [("files", ("a.pdf", b"%PDF", "application/pdf")), ("files", ("b.heic", b"x", ""))])
    assert r.status_code == 200
    assert fake_bot.send_document.await_count == 2
    fake_bot.send_photo.assert_not_awaited()


def test_too_many_files_422(client, app_and_db, fake_bot):
    _, db = app_and_db
    r = _post(client, [("files", PNG)] * 4)
    assert r.status_code == 422
    assert db.query(UserFeedback).count() == 0
    fake_bot.send_message.assert_not_awaited()


def test_file_too_large_413(client, app_and_db, fake_bot):
    _, db = app_and_db
    big = ("big.png", b"0" * (10 * 1024 * 1024 + 1), "image/png")
    r = _post(client, [("files", big)])
    assert r.status_code == 413
    assert db.query(UserFeedback).count() == 0


def test_bad_mime_422(client, fake_bot):
    r = _post(client, [("files", ("x.exe", b"MZ", "application/x-msdownload"))])
    assert r.status_code == 422


def test_multipart_empty_text_422(client, fake_bot):
    assert _post(client, [("files", PNG)], text="  ").status_code == 422


def test_opt_out_with_files_does_not_call_bot(client, app_and_db, fake_bot):
    _, db = app_and_db
    db.add(UserSettings(user_id=895655, feedback_opt_out=True))
    db.commit()
    r = _post(client, [("files", PNG)])
    assert r.json() == {"status": "opted_out"}
    assert db.query(UserFeedback).count() == 0
    fake_bot.send_message.assert_not_awaited()
    fake_bot.send_photo.assert_not_awaited()


def test_bot_failure_still_200_and_row_saved(client, app_and_db, fake_bot):
    _, db = app_and_db
    fake_bot.send_message.side_effect = RuntimeError("telegram down")
    r = _post(client, [("files", PNG)])
    assert r.status_code == 200 and r.json()["status"] == "ok"
    row = db.query(UserFeedback).one()
    assert row.attachments == [{"name": "shot.png", "mime": "image/png", "size": 10}]


def test_no_admin_configured_still_ok(client, app_and_db, fake_bot, monkeypatch):
    from webhook import feedback_api

    monkeypatch.setattr(feedback_api, "_admin_id", lambda: 0)
    r = _post(client, [("files", PNG)])
    assert r.status_code == 200
    fake_bot.send_photo.assert_not_awaited()
