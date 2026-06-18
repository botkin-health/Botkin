"""Тесты эндпоинта /api/agent/recent_glucose — прореживание и параметр date (#163).

Ключевой баг #163: точки обрезались до последних 96 (= 8 часов CGM при шаге 5 мин),
поэтому при широком окне агент видел только последнюю ночь и не мог сопоставить еду
с дневной кривой. Фикс: равномерное прореживание по всему окну + параметр date для
конкретного календарного дня.

In-memory SQLite + мок auth/refresh, без сети и реальных JWT.
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

from database.models import Base, User, GlucoseReading

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
            telegram_id=895655,
            first_name="Sasha",
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
    user.telegram_id = 895655
    user.timezone = "Europe/Moscow"
    return user


@pytest.fixture
def client(db_session, monkeypatch):
    from webhook import agent_tools_api
    from webhook.jwt_auth import get_agent_user, get_db

    monkeypatch.setattr(db_session, "close", lambda: None)
    # on-demand refresh не должен делать сетевой вызов в тестах
    monkeypatch.setattr(agent_tools_api, "_refresh_glucose", lambda telegram_id: None)

    app = FastAPI()
    app.include_router(agent_tools_api.router)
    app.dependency_overrides[get_agent_user] = lambda: _make_mock_user()
    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app)


def _seed_readings(db, start_utc: datetime, count: int, step_min: int = 5, value: float = 5.0):
    """Положить count точек CGM начиная с start_utc с шагом step_min минут."""
    for i in range(count):
        db.add(
            GlucoseReading(
                user_id=895655,
                ts=start_utc + timedelta(minutes=i * step_min),
                value=value,
                trend=None,
                source="test",
            )
        )
    db.commit()


# ── Прореживание ──────────────────────────────────────────────────────────────


def test_no_downsample_when_few_points(client, db_session):
    """≤96 точек — возвращаются все, downsampled=false."""
    start = datetime.now(timezone.utc) - timedelta(hours=4)
    _seed_readings(db_session, start, count=48)  # 4 часа по 5 мин

    r = client.get("/api/agent/recent_glucose", params={"hours": 24})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_count"] == 48
    assert body["returned_count"] == 48
    assert body["downsampled"] is False
    assert len(body["points"]) == 48


def test_downsample_spans_full_window(client, db_session):
    """>96 точек: прорежено до ≤96, НО точки покрывают всё окно, не только конец.

    Регрессия на #163: раньше брались последние 96 (= 8ч), теперь — равномерно по всему окну.
    """
    # 3 суток по 5 мин = 864 точки. Старая логика отдала бы только последние 8 часов.
    start = datetime.now(timezone.utc) - timedelta(hours=71)
    _seed_readings(db_session, start, count=850)

    r = client.get("/api/agent/recent_glucose", params={"hours": 72})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_count"] == 850
    assert body["downsampled"] is True
    assert body["returned_count"] <= 96
    # Первая возвращённая точка должна быть близко к началу окна (а не за последние 8ч).
    first_ts = datetime.fromisoformat(body["points"][0]["ts"])
    last_ts = datetime.fromisoformat(body["points"][-1]["ts"])
    span_hours = (last_ts - first_ts).total_seconds() / 3600
    assert span_hours > 60, f"точки должны покрывать всё окно, а покрыли {span_hours:.1f}ч"


def test_stats_use_all_points_not_sample(client, db_session):
    """min/max в stats — по ВСЕМ точкам, даже если они не попали в прореженную выборку."""
    start = datetime.now(timezone.utc) - timedelta(hours=20)
    _seed_readings(db_session, start, count=200, value=5.0)
    # Один экстремум в середине — статистически он должен отразиться в min.
    mid = db_session.query(GlucoseReading).order_by(GlucoseReading.ts).all()[100]
    mid.value = 3.1
    db_session.commit()

    r = client.get("/api/agent/recent_glucose", params={"hours": 24})
    body = r.json()
    assert body["total_count"] == 200
    assert body["stats"]["min"] == pytest.approx(3.1, abs=0.01)


# ── Параметр date ───────────────────────────────────────────────────────────


def test_date_param_returns_only_that_day(client, db_session):
    """date='YYYY-MM-DD' возвращает точки только за этот календарный день (TZ юзера)."""
    # День X в МСК: 2026-06-15 00:00 МСК = 2026-06-14 21:00 UTC
    day_start_utc = datetime(2026, 6, 15, 0, 0, tzinfo=MSK).astimezone(timezone.utc)
    _seed_readings(db_session, day_start_utc, count=288)  # ровно сутки
    # И точки предыдущего дня — не должны попасть.
    _seed_readings(db_session, day_start_utc - timedelta(hours=3), count=12)

    r = client.get("/api/agent/recent_glucose", params={"date": "2026-06-15"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["date"] == "2026-06-15"
    assert body["total_count"] == 288  # только точки этого дня
    # Все точки — в пределах календарных суток 15-го в МСК.
    for p in body["points"]:
        ts = datetime.fromisoformat(p["ts"])
        assert ts.astimezone(MSK).date().isoformat() == "2026-06-15"


def test_bad_date_returns_400(client, db_session):
    r = client.get("/api/agent/recent_glucose", params={"date": "15-06-2026"})
    assert r.status_code == 400


def test_empty_window_ok(client, db_session):
    """Нет точек — корректный пустой ответ, не падение."""
    r = client.get("/api/agent/recent_glucose", params={"date": "2020-01-01"})
    assert r.status_code == 200
    body = r.json()
    assert body["total_count"] == 0
    assert body["points"] == []
    assert body["downsampled"] is False
