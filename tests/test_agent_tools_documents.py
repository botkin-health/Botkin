"""Tests for /api/agent/list_documents, /update_document, /send_document (issue #370)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def kb_env(tmp_path, monkeypatch):
    import core.health.profile_documents as pd

    kb_dir = tmp_path / "kb"
    uploads_dir = tmp_path / "uploads"
    kb_dir.mkdir()
    uploads_dir.mkdir()
    monkeypatch.setattr(pd, "_KB_DIR", kb_dir)
    monkeypatch.setattr(pd, "_UPLOADS_DIR", uploads_dir)
    return tmp_path


def _write_kb(kb_env, user_id, documents):
    import json

    kb_path = kb_env / "kb" / f"kb_{user_id}.json"
    kb_path.write_text(json.dumps({"documents": documents}), encoding="utf-8")


def _mock_user():
    user = MagicMock()
    user.telegram_id = 895655
    user.first_name = "Sasha"
    return user


@pytest.fixture
def client():
    from webhook.agent_tools.documents import router
    from webhook.jwt_auth import get_agent_user

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_agent_user] = _mock_user
    return TestClient(app)


def test_list_documents_empty(kb_env, client):
    resp = client.get("/api/agent/list_documents")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["documents"] == []


def test_list_documents_returns_metadata(kb_env, client):
    _write_kb(
        kb_env,
        895655,
        [{"added_at": "2026-08-12", "file": "a.jpg", "extracted": {}, "title": "Полис ОМС", "category": "insurance"}],
    )
    resp = client.get("/api/agent/list_documents")
    body = resp.json()
    assert body["total"] == 1
    assert body["documents"][0]["title"] == "Полис ОМС"
    assert body["documents"][0]["category"] == "insurance"


def test_update_document_sets_fields(kb_env, client):
    _write_kb(kb_env, 895655, [{"added_at": "2026-08-12", "file": "a.jpg", "extracted": {}}])
    resp = client.post(
        "/api/agent/update_document",
        params={"document_id": "a.jpg"},
        json={"title": "Полис ОМС", "category": "insurance"},
    )
    body = resp.json()
    assert body["status"] == "ok"
    assert body["document"]["title"] == "Полис ОМС"
    assert body["document"]["category"] == "insurance"


def test_update_document_unknown_id(kb_env, client):
    _write_kb(kb_env, 895655, [{"added_at": "2026-08-12", "file": "a.jpg", "extracted": {}}])
    resp = client.post(
        "/api/agent/update_document",
        params={"document_id": "missing.jpg"},
        json={"title": "x"},
    )
    body = resp.json()
    assert body["status"] == "error"


def test_update_document_unknown_category(kb_env, client):
    _write_kb(kb_env, 895655, [{"added_at": "2026-08-12", "file": "a.jpg", "extracted": {}}])
    resp = client.post(
        "/api/agent/update_document",
        params={"document_id": "a.jpg"},
        json={"category": "bogus"},
    )
    body = resp.json()
    assert body["status"] == "error"


def test_send_document_missing_file(kb_env, client):
    _write_kb(kb_env, 895655, [{"added_at": "2026-08-12", "file": "a.jpg", "extracted": {}}])
    # no actual file on disk
    resp = client.post("/api/agent/send_document", json={"document_id": "a.jpg"})
    body = resp.json()
    assert body["status"] == "error"
    assert body["sent"] is False


def test_send_document_success(kb_env, client):
    _write_kb(kb_env, 895655, [{"added_at": "2026-08-12", "file": "a.jpg", "extracted": {}, "title": "Полис ОМС"}])
    (kb_env / "uploads" / "895655").mkdir(parents=True, exist_ok=True)
    (kb_env / "uploads" / "895655" / "a.jpg").write_bytes(b"fake-image-bytes")

    with (
        patch("webhook.agent_tools.documents.resolve_bot_token", return_value="123:ABC"),
        patch("webhook.agent_tools.documents._requests.post") as mock_post,
    ):
        mock_post.return_value.json.return_value = {"ok": True}
        resp = client.post("/api/agent/send_document", json={"document_id": "a.jpg"})

    body = resp.json()
    assert body["status"] == "ok"
    assert body["sent"] is True
    assert body["title"] == "Полис ОМС"
    called_url = mock_post.call_args[0][0]
    assert "sendPhoto" in called_url


def test_send_document_no_bot_token(kb_env, client):
    _write_kb(kb_env, 895655, [{"added_at": "2026-08-12", "file": "a.jpg", "extracted": {}}])
    (kb_env / "uploads" / "895655").mkdir(parents=True, exist_ok=True)
    (kb_env / "uploads" / "895655" / "a.jpg").write_bytes(b"fake")

    with patch("webhook.agent_tools.documents.resolve_bot_token", return_value=""):
        resp = client.post("/api/agent/send_document", json={"document_id": "a.jpg"})

    body = resp.json()
    assert body["status"] == "error"
    assert body["sent"] is False


def test_send_document_traversal_blocked(kb_env, client):
    _write_kb(kb_env, 895655, [{"added_at": "2026-08-12", "file": "a.jpg", "extracted": {}}])
    resp = client.post("/api/agent/send_document", json={"document_id": "../../etc/passwd"})
    body = resp.json()
    assert body["status"] == "error"
    assert body["sent"] is False
