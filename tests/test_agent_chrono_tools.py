"""Тесты #502: log_bp/log_supplement не могли передать дату прошлого события —
в input_schema для LLM не было полей measured_at/date/time, хотя HTTP-эндпоинты
(telegram-bot/webhook/agent_tools/vitals.py, supplements.py) их принимали.
Модель верно вычисляла дату («позавчера» → конкретный день), но физически не
могла её передать — запись падала на текущий момент.

Юнит-уровень (как test_agent_dispatch_plan.py): схема тула для LLM + форвардинг
аргументов диспетчером _call_tool, без полного цикла ask_agent.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import core.agent_chat as agent_chat


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.ok = True

    def json(self):
        return self._payload


class _FakeRequests:
    """Записывает вызовы .post, чтобы тест мог проверить какие поля дошли до эндпоинта."""

    def __init__(self):
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"method": "post", "url": url, "headers": headers, "json": json})
        return _FakeResp({"status": "ok"})


def _tool(name):
    return next(t for t in agent_chat.TOOLS if t["name"] == name)


# ── Схема log_bp несёт measured_at ──────────────────────────────────────────


def test_log_bp_schema_has_measured_at():
    tool = _tool("log_bp")
    assert "measured_at" in tool["input_schema"]["properties"]


def test_dispatch_log_bp_forwards_measured_at(monkeypatch):
    fake = _FakeRequests()
    monkeypatch.setattr(agent_chat, "requests", fake)

    args = {"systolic": 150, "diastolic": 90, "measured_at": "2026-09-19T09:00:00"}
    agent_chat._call_tool("log_bp", args, "tok")

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["url"].endswith("/log_bp")
    assert call["json"] == args
    assert call["json"]["measured_at"] == "2026-09-19T09:00:00"


# ── Схема log_supplement несёт date/time ────────────────────────────────────


def test_log_supplement_schema_has_date_and_time():
    tool = _tool("log_supplement")
    props = tool["input_schema"]["properties"]
    assert "date" in props
    assert "time" in props


def test_dispatch_log_supplement_forwards_date_and_time(monkeypatch):
    fake = _FakeRequests()
    monkeypatch.setattr(agent_chat, "requests", fake)

    args = {
        "supplement_name": "Омега-3",
        "dosage": "1000 мг",
        "date": "2026-09-20",
        "time": "09:00",
    }
    agent_chat._call_tool("log_supplement", args, "tok")

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["url"].endswith("/log_supplement")
    assert call["json"] == args
    assert call["json"]["date"] == "2026-09-20"


# ── log_workout (уже был в порядке, #500) — сверяем, что схема не потеряла start_time ──


def test_log_workout_schema_has_start_time():
    tool = _tool("log_workout")
    assert "start_time" in tool["input_schema"]["properties"]


# ── Общее правило хронологии в системном промпте ────────────────────────────


def test_system_prompt_date_line_mentions_any_writing_tool():
    """#502: правило «явная дата или переспросить» должно быть общим, не только для еды."""
    import inspect

    src = inspect.getsource(agent_chat)
    assert "ЛЮБОГО инструмента записи данных" in src
