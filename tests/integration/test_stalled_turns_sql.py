"""Поиск зависших ходов агента — SQL сторожа на настоящем Postgres.

Почему integration: запрос использует `DISTINCT ON` и `make_interval`, которых
на in-memory SQLite нет. Логика «последняя строка диалога = реплика юзера или
сбой» и есть предмет проверки, подделывать её смысла нет.

Запуск: DATABASE_URL=... pytest tests/integration/test_stalled_turns_sql.py -m integration
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "check_stalled_turns", ROOT / "scripts" / "server" / "check_stalled_turns.py"
)
watchdog = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(watchdog)

_UID = -999002  # не пересекается с реальными telegram_id


@pytest.fixture
def session():
    engine = create_engine(os.environ["DATABASE_URL"])
    s = sessionmaker(bind=engine)()
    s.execute(
        text(
            "INSERT INTO users (telegram_id, first_name, cohort, is_active) "
            "VALUES (:uid, 'watchdog-test', 'external', true) ON CONFLICT (telegram_id) DO NOTHING"
        ),
        {"uid": _UID},
    )
    s.commit()
    yield s
    s.rollback()
    s.execute(text("DELETE FROM agent_conversations WHERE user_id = :uid"), {"uid": _UID})
    s.execute(text("DELETE FROM users WHERE telegram_id = :uid"), {"uid": _UID})
    s.commit()
    s.close()


def _add(session, role, minutes_ago, source="botkinclaw", body="текст"):
    session.execute(
        text(
            "INSERT INTO agent_conversations (user_id, role, content, source, created_at) "
            "VALUES (:uid, :role, CAST(:c AS jsonb), :src, NOW() - make_interval(mins => :ago))"
        ),
        {
            "uid": _UID,
            "role": role,
            "c": json.dumps([{"type": "text", "text": body}], ensure_ascii=False),
            "src": source,
            "ago": minutes_ago,
        },
    )
    session.commit()


def _stalled(session, stale_after=20, lookback=24):
    rows = session.execute(
        text(watchdog._STALLED_SQL),
        {"lookback": lookback, "stale_after": stale_after, "watchdog_source": watchdog.WATCHDOG_SOURCE},
    ).fetchall()
    return [r for r in rows if r.user_id == _UID]


def test_unanswered_user_message_is_stalled(session):
    """Ровно случай 24-25.08: вопрос есть, ответа нет."""
    _add(session, "user", minutes_ago=45, body="Похоже Botkin насовсем помер...")
    found = _stalled(session)
    assert len(found) == 1
    assert found[0].role == "user"
    assert found[0].age_min >= 44


def test_answered_turn_is_not_stalled(session):
    """Нормальный ход завершается ответом — тревожить незачем."""
    _add(session, "user", minutes_ago=45)
    _add(session, "assistant", minutes_ago=44, body="ответил")
    assert _stalled(session) == []


def test_recent_message_is_not_stalled_yet(session):
    """Ход может ещё считаться: несколько обращений к модели с ретраями."""
    _add(session, "user", minutes_ago=3)
    assert _stalled(session) == []


def test_recorded_error_counts_as_stalled(session):
    """role='error' — зафиксированный сбой: пользователю тоже надо ответить."""
    _add(session, "error", minutes_ago=30, source="botkinclaw_error", body="HTTPError: 500")
    found = _stalled(session)
    assert len(found) == 1 and found[0].role == "error"


def test_already_notified_is_skipped(session):
    """Иначе извинение уходило бы каждые 15 минут."""
    _add(session, "user", minutes_ago=60)
    _add(session, "error", minutes_ago=30, source=watchdog.WATCHDOG_SOURCE, body="уведомлён")
    assert _stalled(session) == []


def test_tool_result_midturn_is_not_stalled(session):
    """Промежуточные строки хода — не зависание, важен исход."""
    _add(session, "user", minutes_ago=40)
    _add(session, "tool_result", minutes_ago=39, body="{}")
    _add(session, "assistant", minutes_ago=38, body="готово")
    assert _stalled(session) == []


def test_old_incident_outside_lookback_is_ignored(session):
    """Недельной давности молчание разбирается отчётом, а не письмом сегодня."""
    _add(session, "user", minutes_ago=60 * 60)  # 2.5 суток назад
    assert _stalled(session, lookback=24) == []
