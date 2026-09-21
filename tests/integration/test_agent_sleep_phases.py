"""Фазы сна в /recent_sleep читаются из обоих каналов записи (фикс 22.09.2026).

Почему integration, а не unit: тул выполняет сырой Postgres-SQL
(`raw_data->>`, `::numeric`, `(:days || ' days')::interval`), который на
in-memory SQLite из `tests/test_agent_cardio_tools.py` не исполняется. Баг
живёт именно в SQL, поэтому проверять его подделкой на SQLite бессмысленно —
нужен настоящий Postgres.

Баг: Garmin-синк пишет фазы как `deep_h`/`rem_h`, HAE-адаптер
(`webhook/apple_health.py`) — как `sleep_deep_h`/`sleep_rem_h`/`sleep_core_h`/
`sleep_awake_h`. Reader знал только про Garmin → у всех Apple Health-юзеров
фазы приходили пустыми при непустой БД (0 из 15 ночей за две недели).

Запуск: DATABASE_URL=... pytest tests/integration/test_agent_sleep_phases.py -m integration
"""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.integration


# Тот же SELECT, что в telegram-bot/webhook/agent_tools/sleep.py::recent_sleep.
# Держим копию здесь намеренно: тест должен падать, если в туле снова разъедутся
# имена ключей с каналами записи.
_SLEEP_SQL = """
    SELECT date,
           sleep_hours                          AS duration_hours,
           (raw_data->>'sleep_score')::int      AS quality_score,
           COALESCE((raw_data->>'deep_h')::numeric,
                    (raw_data->>'sleep_deep_h')::numeric) * 60   AS deep_min,
           COALESCE((raw_data->>'rem_h')::numeric,
                    (raw_data->>'sleep_rem_h')::numeric)  * 60   AS rem_min,
           (raw_data->>'sleep_core_h')::numeric * 60             AS core_min,
           (raw_data->>'sleep_awake_h')::numeric * 60            AS awake_min,
           source
    FROM activity_log
    WHERE user_id = :uid
      AND sleep_hours IS NOT NULL
      AND sleep_hours > 0
      AND date >= CURRENT_DATE - (:days || ' days')::interval
    ORDER BY date DESC
"""

_TEST_UID = -999001  # не пересекается с реальными telegram_id


@pytest.fixture
def session():
    engine = create_engine(os.environ["DATABASE_URL"])
    Session = sessionmaker(bind=engine)
    s = Session()
    s.execute(
        text(
            "INSERT INTO users (telegram_id, first_name, cohort, is_active) "
            "VALUES (:uid, 'sleep-phase-test', 'external', false) ON CONFLICT DO NOTHING"
        ),
        {"uid": _TEST_UID},
    )
    s.commit()
    yield s
    s.rollback()
    s.execute(text("DELETE FROM activity_log WHERE user_id = :uid"), {"uid": _TEST_UID})
    s.execute(text("DELETE FROM users WHERE telegram_id = :uid"), {"uid": _TEST_UID})
    s.commit()
    s.close()


def _insert_night(session, raw_data: str, source: str, days_ago: int = 1):
    session.execute(
        text(
            "INSERT INTO activity_log (user_id, date, sleep_hours, source, raw_data) "
            "VALUES (:uid, CURRENT_DATE - :ago, 7.4, :src, CAST(:raw AS jsonb)) "
            "ON CONFLICT (user_id, date) DO UPDATE "
            "SET raw_data = EXCLUDED.raw_data, source = EXCLUDED.source, sleep_hours = EXCLUDED.sleep_hours"
        ),
        {"uid": _TEST_UID, "ago": days_ago, "src": source, "raw": raw_data},
    )
    session.commit()
    return session.execute(text(_SLEEP_SQL), {"uid": _TEST_UID, "days": 7}).fetchone()


def test_hae_phase_keys_are_read(session):
    """Apple Health пишет sleep_deep_h/sleep_rem_h — их обязано быть видно."""
    row = _insert_night(
        session,
        '{"sleep_deep_h": 0.9, "sleep_rem_h": 1.5, "sleep_core_h": 4.6, "sleep_awake_h": 0.4}',
        "apple_health_v2",
    )
    assert int(row.deep_min) == 54
    assert int(row.rem_min) == 90
    assert int(row.core_min) == 276
    assert int(row.awake_min) == 24


def test_garmin_phase_keys_still_work(session):
    """Garmin-канал не сломан: deep_h/rem_h читаются как раньше."""
    row = _insert_night(session, '{"deep_h": 1.2, "rem_h": 2.0, "sleep_score": 84}', "garmin")
    assert int(row.deep_min) == 72
    assert int(row.rem_min) == 120
    assert row.quality_score == 84
    assert row.core_min is None  # у Garmin таких фаз нет — и это не баг
