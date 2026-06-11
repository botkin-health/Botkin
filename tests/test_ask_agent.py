"""Тесты ask_agent — главный agent-loop BotkinClaw (аудит 11.06.2026: было 0 тестов).

Anthropic API и tools API замоканы на уровне core.agent_chat.requests;
история — настоящая таблица agent_conversations на SQLite (прод-CAST AS JSONB
переписывается engine-событием, см. фикстуру agent_db).
"""

import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.models import Base, User

import core.agent_chat as agent_chat


# ── Фикстуры ─────────────────────────────────────────────────────────────────


@pytest.fixture
def agent_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    # Прод-SQL пишет историю через CAST(:content AS JSONB) — на SQLite такой
    # CAST имеет NUMERIC-affinity и превращает JSON-строку в 0. Переписываем
    # на лету, сохраняя остальную логику настоящей.
    @event.listens_for(engine, "before_cursor_execute", retval=True)
    def _strip_jsonb_cast(conn, cursor, statement, parameters, context, executemany):
        return statement.replace("CAST(? AS JSONB)", "?"), parameters

    Base.metadata.create_all(bind=engine)
    with engine.connect() as c:
        c.execute(
            text(
                """CREATE TABLE agent_conversations (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       user_id BIGINT NOT NULL,
                       role TEXT NOT NULL,
                       content TEXT NOT NULL,
                       tool_use_id TEXT,
                       source TEXT,
                       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
            )
        )
        c.commit()
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    session = TestSession()
    session.add(
        User(
            telegram_id=895655,
            first_name="Sasha",
            cohort="owner",
            pack_name="bariatric",
            jwt_secret="test_secret",
            agent_system_prompt="Ты — семейный AI-врач. Отвечай кратко.",
            is_active=True,
        )
    )
    session.commit()
    session.close()

    monkeypatch.setattr(agent_chat, "SessionLocal", TestSession)
    # usage-логгер ходит в реальный Postgres своим SessionLocal — глушим
    import core.llm_usage as llm_usage

    monkeypatch.setattr(llm_usage, "log_anthropic_response", lambda **kw: None)
    return TestSession


class FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = status_code < 400
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeRequests:
    """Подменяет core.agent_chat.requests: Anthropic — по сценарию, tools — заглушка."""

    def __init__(self, anthropic_script, tool_payload=None):
        self.anthropic_script = list(anthropic_script)
        self.tool_payload = tool_payload or {"status": "ok"}
        self.anthropic_calls = []
        self.tool_calls = []

    def post(self, url, headers=None, json=None, timeout=None, params=None):
        if url == agent_chat.ANTHROPIC_API_URL:
            self.anthropic_calls.append({"headers": headers, "payload": json})
            return self.anthropic_script.pop(0)
        self.tool_calls.append({"url": url, "headers": headers, "json": json})
        return FakeResp(self.tool_payload)

    def get(self, url, headers=None, params=None, timeout=None):
        self.tool_calls.append({"url": url, "headers": headers, "params": params})
        return FakeResp(self.tool_payload)


def _anthropic_text(text_str):
    return FakeResp(
        {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": text_str}],
            "usage": {"input_tokens": 100, "output_tokens": 20},
        }
    )


def _anthropic_tool_use(name, args, tu_id="tu_001"):
    return FakeResp(
        {
            "stop_reason": "tool_use",
            "content": [
                {"type": "text", "text": "Сейчас посмотрю."},
                {"type": "tool_use", "id": tu_id, "name": name, "input": args},
            ],
            "usage": {"input_tokens": 100, "output_tokens": 30},
        }
    )


def _history_rows(TestSession):
    s = TestSession()
    rows = s.execute(text("SELECT role, content, source FROM agent_conversations ORDER BY id")).fetchall()
    s.close()
    return rows


# ── Тесты ────────────────────────────────────────────────────────────────────


def test_text_answer_saved_to_history(agent_db, monkeypatch):
    """(1) Текстовый ответ возвращается и пишется в agent_conversations."""
    fake = FakeRequests([_anthropic_text("Всё в порядке, вес стабилен.")])
    monkeypatch.setattr(agent_chat, "requests", fake)

    reply = agent_chat.ask_agent(895655, "как мой вес?")

    assert reply == "Всё в порядке, вес стабилен."
    rows = _history_rows(agent_db)
    roles = [r.role for r in rows]
    assert roles == ["user", "assistant"]
    assert all(r.source == "botkinclaw" for r in rows)
    assert "как мой вес?" in json.loads(rows[0].content)
    assert "вес стабилен" in str(json.loads(rows[1].content))


def test_tool_loop_calls_tools_api_and_returns_final_answer(agent_db, monkeypatch):
    """(2) tool_use → HTTP-вызов tools API с JWT → tool_result → финальный ответ."""
    fake = FakeRequests(
        [
            _anthropic_tool_use("get_weight_history", {"days": 7}),
            _anthropic_text("Твой вес 82.0 кг, тренд стабильный."),
        ],
        tool_payload={"status": "ok", "latest": {"weight_kg": 82.0}},
    )
    monkeypatch.setattr(agent_chat, "requests", fake)

    reply = agent_chat.ask_agent(895655, "что с весом за неделю?")

    assert "82.0" in reply
    # Anthropic вызван дважды: tool_use + финал
    assert len(fake.anthropic_calls) == 2
    # Tools API вызван с Bearer JWT
    assert len(fake.tool_calls) == 1
    auth = fake.tool_calls[0]["headers"]["Authorization"]
    assert auth.startswith("Bearer ")
    # Во втором вызове Anthropic ушёл tool_result с данными
    second_msgs = fake.anthropic_calls[1]["payload"]["messages"]
    flat = json.dumps(second_msgs, ensure_ascii=False)
    assert "tool_result" in flat and "82.0" in flat.replace("\\", "")
    # История: user → assistant(tool_use) → tool_result → assistant(финал)
    roles = [r.role for r in _history_rows(agent_db)]
    assert roles == ["user", "assistant", "tool_result", "assistant"]


def test_api_error_raises_cleanly(agent_db, monkeypatch):
    """(3) 500 от Anthropic → чистый HTTPError наружу (хендлер его ловит),
    без полу-сохранённого ответа ассистента в истории."""
    import requests as real_requests

    fake = FakeRequests([FakeResp({"error": "boom"}, status_code=500)])
    monkeypatch.setattr(agent_chat, "requests", fake)

    with pytest.raises(real_requests.HTTPError):
        agent_chat.ask_agent(895655, "привет")

    roles = [r.role for r in _history_rows(agent_db)]
    assert "assistant" not in roles


def test_inactive_user_rejected(agent_db, monkeypatch):
    """Неактивный/чужой user_id — RuntimeError, ноль обращений к API."""
    fake = FakeRequests([])
    monkeypatch.setattr(agent_chat, "requests", fake)

    with pytest.raises(RuntimeError):
        agent_chat.ask_agent(999999, "привет")
    assert fake.anthropic_calls == []
