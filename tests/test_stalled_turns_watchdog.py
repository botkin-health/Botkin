"""Сторож незакрытых ходов: scripts/server/check_stalled_turns.py.

Здесь — чистые хелперы и выбор получателя алерта. Сам поиск зависших ходов
живёт в Postgres-SQL (DISTINCT ON, make_interval), на SQLite он не исполняется,
поэтому проверяется в tests/integration/test_stalled_turns_sql.py.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "check_stalled_turns", ROOT / "scripts" / "server" / "check_stalled_turns.py"
)
watchdog = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(watchdog)


class TestPreview:
    def test_extracts_text_from_content_blocks(self):
        content = json.dumps([{"type": "text", "text": "Похоже Botkin насовсем помер..."}], ensure_ascii=False)
        assert watchdog._preview(content) == "Похоже Botkin насовсем помер..."

    def test_joins_several_text_blocks_and_skips_tool_use(self):
        content = json.dumps(
            [
                {"type": "text", "text": "Записываю!"},
                {"type": "tool_use", "name": "log_meal_text", "input": {}},
                {"type": "text", "text": "готово"},
            ],
            ensure_ascii=False,
        )
        assert watchdog._preview(content) == "Записываю! готово"

    def test_plain_string_content_unwrapped(self):
        """Реплики юзера лежат как JSON-строка — кавычки в алерте не нужны."""
        assert watchdog._preview('"Теперь понятно?"') == "Теперь понятно?"

    def test_broken_json_does_not_raise(self):
        assert watchdog._preview("{не json") == "{не json"

    def test_truncates_long_text(self):
        content = json.dumps([{"type": "text", "text": "я" * 500}], ensure_ascii=False)
        assert len(watchdog._preview(content, limit=120)) == 120


class TestOwnerId:
    def test_reads_first_available_env(self, monkeypatch):
        monkeypatch.delenv("BOTKIN_OWNER_ID", raising=False)
        monkeypatch.setenv("BOTKIN_USER_ID", "42")
        assert watchdog._owner_id() == 42

    def test_prefers_explicit_owner_var(self, monkeypatch):
        monkeypatch.setenv("BOTKIN_OWNER_ID", "7")
        monkeypatch.setenv("BOTKIN_USER_ID", "42")
        assert watchdog._owner_id() == 7

    def test_none_when_unset(self, monkeypatch):
        for key in ("BOTKIN_OWNER_ID", "BOTKIN_USER_ID", "HEALTHVAULT_USER_ID"):
            monkeypatch.delenv(key, raising=False)
        assert watchdog._owner_id() is None

    def test_garbage_value_does_not_crash(self, monkeypatch):
        for key in ("BOTKIN_OWNER_ID", "BOTKIN_USER_ID", "HEALTHVAULT_USER_ID"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("BOTKIN_OWNER_ID", "не-число")
        assert watchdog._owner_id() is None


class TestDryRun:
    def test_dry_run_sends_nothing(self, monkeypatch):
        called = []
        monkeypatch.setattr(watchdog.requests, "post", lambda *a, **kw: called.append(a) or None)
        assert watchdog._send("token", 1, "текст", dry=True) is True
        assert called == []

    def test_telegram_failure_reported_as_false(self, monkeypatch):
        class _Resp:
            status_code = 403
            text = "forbidden"

            def json(self):
                return {"ok": False, "description": "bot was blocked by the user"}

        monkeypatch.setattr(watchdog.requests, "post", lambda *a, **kw: _Resp())
        assert watchdog._send("token", 1, "текст", dry=False) is False


def test_thresholds_are_sane():
    """Порог должен быть заведомо больше любого живого хода агента.

    Ход — до MAX_TOOL_ITERATIONS обращений к модели, каждое с ретраями и
    таймаутом 60 с. Если порог опустить к паре минут, сторож начнёт извиняться
    за ходы, которые ещё считаются.
    """
    assert watchdog.STALE_AFTER_MINUTES >= 10
    assert watchdog.LOOKBACK_HOURS <= 48


def test_user_message_admits_fault_without_blaming_user():
    text = watchdog.USER_TEXT.lower()
    assert "сбой" in text
    assert "не потерялось" in text
    # Просим повторить вопрос — иначе человек останется ждать ответа, которого нет
    assert "ещё раз" in text


@pytest.mark.parametrize("role", ["user", "error"])
def test_sql_targets_unanswered_roles(role):
    """Ход считается зависшим по последней строке: реплика юзера или сбой."""
    assert f"'{role}'" in watchdog._STALLED_SQL


def test_sql_skips_already_notified():
    """Иначе сторож будет слать извинение каждые 15 минут."""
    assert "watchdog_source" in watchdog._STALLED_SQL
    assert watchdog.WATCHDOG_SOURCE == "watchdog_notified"
