"""Tests for POST /add_agent_correction endpoint and _call_tool dispatch."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

# telegram-bot → webhook package (same pattern as test_agent_tools_api.py)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_user(telegram_id: int = 12345, cohort: str = "family"):
    user = MagicMock()
    user.telegram_id = telegram_id
    user.cohort = cohort
    user.container_id = None
    return user


def _make_client(tmp_path: Path, telegram_id: int, kb_data: dict | None = None):
    """Return (TestClient, kb_file_path) with a real KB file and mocked auth."""
    from webhook import agent_tools_api
    from webhook.jwt_auth import get_agent_user

    kb_dir = tmp_path / "data" / "kb"
    kb_dir.mkdir(parents=True)
    kb_file = kb_dir / f"kb_{telegram_id}.json"
    kb_file.write_text(json.dumps(kb_data or {"patient_info": {}}), encoding="utf-8")

    app = FastAPI()
    app.include_router(agent_tools_api.router)

    mock_user = _make_mock_user(telegram_id)
    app.dependency_overrides[get_agent_user] = lambda: mock_user

    client = TestClient(app)
    return client, kb_file, mock_user


# ---------------------------------------------------------------------------
# Tests for the endpoint
# ---------------------------------------------------------------------------


class TestAddAgentCorrectionEndpoint:
    def test_add_correction_ok(self, tmp_path):
        """POST valid key+value → KB file updated, updated_at present."""
        from webhook import agent_tools_api

        client, kb_file, mock_user = _make_client(tmp_path, telegram_id=12345)

        with patch.object(agent_tools_api, "_resolve_user_kb_path", return_value=(kb_file, "kb_12345.json")):
            resp = client.post(
                "/api/agent/add_agent_correction",
                json={"key": "surgery_year", "value": "2010", "reason": "пользователь уточнил"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["key"] == "surgery_year"

        saved = json.loads(kb_file.read_text(encoding="utf-8"))
        assert "agent_corrections" in saved
        correction = saved["agent_corrections"]["surgery_year"]
        assert correction["value"] == "2010"
        assert correction["reason"] == "пользователь уточнил"
        assert "updated_at" in correction

    def test_add_correction_updates_existing_key(self, tmp_path):
        """Second POST with same key overwrites value."""
        from webhook import agent_tools_api

        existing = {"agent_corrections": {"surgery_year": {"value": "2019", "reason": "old", "updated_at": "x"}}}
        client, kb_file, _ = _make_client(tmp_path, telegram_id=12345, kb_data=existing)

        with patch.object(agent_tools_api, "_resolve_user_kb_path", return_value=(kb_file, "kb_12345.json")):
            resp = client.post(
                "/api/agent/add_agent_correction",
                json={"key": "surgery_year", "value": "2010"},
            )

        assert resp.status_code == 200
        saved = json.loads(kb_file.read_text(encoding="utf-8"))
        assert saved["agent_corrections"]["surgery_year"]["value"] == "2010"

    def test_add_correction_bad_key_spaces(self, tmp_path):
        """Key with spaces → 422."""
        from webhook import agent_tools_api

        client, kb_file, _ = _make_client(tmp_path, telegram_id=12345)

        with patch.object(agent_tools_api, "_resolve_user_kb_path", return_value=(kb_file, "kb_12345.json")):
            resp = client.post(
                "/api/agent/add_agent_correction",
                json={"key": "bad key!", "value": "x"},
            )

        assert resp.status_code == 422

    def test_add_correction_bad_key_special_chars(self, tmp_path):
        """Key with special chars → 422."""
        from webhook import agent_tools_api

        client, kb_file, _ = _make_client(tmp_path, telegram_id=12345)

        with patch.object(agent_tools_api, "_resolve_user_kb_path", return_value=(kb_file, "kb_12345.json")):
            resp = client.post(
                "/api/agent/add_agent_correction",
                json={"key": "key/with/slashes", "value": "x"},
            )

        assert resp.status_code == 422

    def test_add_correction_no_kb(self, tmp_path):
        """User without KB file → 404."""
        from webhook import agent_tools_api
        from webhook.jwt_auth import get_agent_user

        app = FastAPI()
        app.include_router(agent_tools_api.router)
        mock_user = _make_mock_user(99999)
        app.dependency_overrides[get_agent_user] = lambda: mock_user
        client = TestClient(app)

        missing_path = tmp_path / "data" / "kb" / "kb_99999.json"  # does not exist

        with patch.object(agent_tools_api, "_resolve_user_kb_path", return_value=(missing_path, "kb_99999.json")):
            resp = client.post(
                "/api/agent/add_agent_correction",
                json={"key": "some_fact", "value": "val"},
            )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests for _call_tool dispatch
# ---------------------------------------------------------------------------


class TestCallToolDispatch:
    def test_call_tool_add_correction_dispatches(self):
        """_call_tool('add_agent_correction', ...) → POST to /add_agent_correction."""
        import core.agent_chat as agent_chat

        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.text = json.dumps({"status": "ok", "key": "surgery_year"})

        with patch.object(agent_chat.requests, "post", return_value=mock_resp) as mock_post:
            result = agent_chat._call_tool(
                "add_agent_correction",
                {"key": "surgery_year", "value": "2010", "reason": "уточнение"},
                token="fake-jwt",
            )

        assert mock_post.called
        call_url = mock_post.call_args[0][0]
        assert "add_agent_correction" in call_url

        call_json = mock_post.call_args[1]["json"]
        assert call_json["key"] == "surgery_year"
        assert call_json["value"] == "2010"
        assert call_json["reason"] == "уточнение"

        data = json.loads(result)
        assert data["status"] == "ok"

    def test_call_tool_add_correction_in_tools_list(self):
        """add_agent_correction must be present in TOOLS with required fields."""
        from core.agent_chat import TOOLS

        names = [t["name"] for t in TOOLS]
        assert "add_agent_correction" in names

        tool = next(t for t in TOOLS if t["name"] == "add_agent_correction")
        schema = tool["input_schema"]
        assert "key" in schema["properties"]
        assert "value" in schema["properties"]
        assert "key" in schema["required"]
        assert "value" in schema["required"]

    def test_call_tool_http_error_returns_json_error(self):
        """When endpoint returns 4xx, _call_tool returns JSON error string."""
        import core.agent_chat as agent_chat

        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 422
        mock_resp.text = '{"detail": "Недопустимый ключ"}'

        with patch.object(agent_chat.requests, "post", return_value=mock_resp):
            result = agent_chat._call_tool(
                "add_agent_correction",
                {"key": "bad key!", "value": "x"},
                token="fake-jwt",
            )

        data = json.loads(result)
        assert "error" in data
        assert "422" in data["error"]
