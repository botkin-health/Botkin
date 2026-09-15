"""Тесты инструментов, которых агенту не хватало 15.09.2026.

Три слепые зоны, найденные при разборе «почему бот не видит показания»:
1. ЭКГ с Apple Watch (`ecg_records`) — таблица наполняется с 31.08, эндпоинта не было;
2. уведомления часов о пульсе в покое (`heart_rate_events`) — то же самое;
3. `recent_glucose` при пустом окне не сообщал, что данные вообще есть: окно
   упирается в 168 часов, и при разрыве длиннее недели агент достраивал историю
   из контекста (заявил, что мониторинг кончился в январе, хотя в базе лежало лето).

In-memory SQLite + мок auth, без сети.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

import pytest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import Base, User, GlucoseReading, EcgRecord, HeartRateEvent

UID = 895655
MSK = ZoneInfo("Europe/Moscow")


@pytest.fixture
def engine():
    e = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=e)
    yield e
    Base.metadata.drop_all(bind=e)


@pytest.fixture
def db_session(engine):
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    session.add(
        User(
            telegram_id=UID,
            first_name="Test",
            cohort="owner",
            jwt_secret="test_secret",
            is_active=True,
            timezone="Europe/Moscow",
        )
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()


def _make_mock_user():
    user = MagicMock()
    user.telegram_id = UID
    user.timezone = "Europe/Moscow"
    return user


@pytest.fixture
def client(db_session, monkeypatch):
    from webhook import agent_tools as agent_tools_api
    from webhook.agent_tools import glucose
    from webhook.jwt_auth import get_agent_user, get_db

    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(glucose, "_refresh_glucose", lambda telegram_id: None)

    app = FastAPI()
    app.include_router(agent_tools_api.router)
    app.dependency_overrides[get_agent_user] = lambda: _make_mock_user()
    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app)


# ── ЭКГ ───────────────────────────────────────────────────────────────────────


def test_recent_ecg_returns_records_and_aggregates(client, db_session):
    now = datetime.now(timezone.utc)
    for i, (cls, hr) in enumerate([("sinusRhythm", 90), ("sinusRhythm", 78), ("atrialFibrillation", 120)]):
        db_session.add(
            EcgRecord(
                user_id=UID,
                recorded_at=now - timedelta(days=i + 1),
                classification=cls,
                average_heart_rate=hr,
                duration_sec=30,
                source=f"ecg-{i}",
            )
        )
    db_session.commit()

    body = client.get("/api/agent/recent_ecg").json()
    assert body["count"] == 3
    assert body["by_classification"] == {"sinusRhythm": 2, "atrialFibrillation": 1}
    assert body["hr_range"] == {"min": 78, "max": 120}
    assert body["avg_hr"] == 96.0
    # Самая свежая запись — первой (порядок по убыванию времени).
    assert body["items"][0]["avg_hr"] == 90


def test_recent_ecg_window_excludes_old(client, db_session):
    """Запись старше окна не попадает — иначе «ЭКГ за месяц» соберёт прошлогоднее."""
    now = datetime.now(timezone.utc)
    db_session.add(
        EcgRecord(user_id=UID, recorded_at=now - timedelta(days=200), classification="sinusRhythm", source="old")
    )
    db_session.commit()

    assert client.get("/api/agent/recent_ecg", params={"days": 30}).json()["count"] == 0
    assert client.get("/api/agent/recent_ecg", params={"days": 365}).json()["count"] == 1


def test_recent_ecg_empty(client):
    body = client.get("/api/agent/recent_ecg").json()
    assert body["count"] == 0 and body["items"] == []


# ── События пульса ────────────────────────────────────────────────────────────


def test_heart_rate_events_returns_events_and_peak(client, db_session):
    now = datetime.now(timezone.utc)
    for i, mx in enumerate([105, 127, 112]):
        db_session.add(
            HeartRateEvent(
                user_id=UID,
                started_at=now - timedelta(days=i + 1),
                ended_at=now - timedelta(days=i + 1) + timedelta(minutes=12),
                event_type="high",
                threshold_bpm=100,
                min_bpm=100,
                max_bpm=mx,
                avg_bpm=mx - 5,
                duration_min=12,
                source=f"hr-{i}",
            )
        )
    db_session.commit()

    body = client.get("/api/agent/heart_rate_events").json()
    assert body["count"] == 3
    assert body["by_type"] == {"high": 3}
    assert body["max_bpm_overall"] == 127
    assert body["items"][0]["ended_at"] is not None


def test_heart_rate_events_empty(client):
    body = client.get("/api/agent/heart_rate_events").json()
    assert body["count"] == 0 and body["items"] == []


# ── Пустое окно глюкозы объясняет само себя ───────────────────────────────────


def test_empty_window_reports_last_point_ever(client, db_session):
    """Датчик молчит дольше окна — ответ обязан назвать последнюю точку за всю историю.

    Это и есть защита от выдумки: без этих полей агент отличить «CGM не было
    никогда» от «данные были две недели назад» не может.
    """
    old = datetime.now(timezone.utc) - timedelta(days=14)
    for i in range(5):
        db_session.add(
            GlucoseReading(user_id=UID, ts=old + timedelta(minutes=5 * i), value=5.0, trend=None, source="test")
        )
    db_session.commit()

    body = client.get("/api/agent/recent_glucose", params={"hours": 24}).json()
    assert body["total_count"] == 0
    assert body["all_time_count"] == 5
    assert body["days_since_last_point"] == 13  # 14 дней минус 20 минут точек
    last_ts = old + timedelta(minutes=20)  # 5-я точка
    assert body["last_point_ever_local"].startswith(last_ts.astimezone(MSK).date().isoformat())
    assert body["is_stale"] is True


def test_empty_window_without_any_data(client):
    """Данных нет вообще — полей про «последнюю точку» быть не должно."""
    body = client.get("/api/agent/recent_glucose", params={"hours": 24}).json()
    assert body["total_count"] == 0
    assert body["all_time_count"] == 0
    assert "last_point_ever_local" not in body
    assert "days_since_last_point" not in body
