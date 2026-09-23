"""Регрессия #518 (дефект 2): log_bp — naive measured_at уезжает в UTC,
замеры одной датой (без времени) перетирают друг друга через ON CONFLICT.

Причина: `measured_at = datetime.fromisoformat(req.measured_at)` не привязывает
naive-значение к таймзоне пользователя. Дальше `_dt_isoformat_local()` (ответ
агенту) трактует naive datetime как UTC (`_dt_to_user_tz` в common.py) — для
Europe/Moscow (+3) замер «вчера в 23:00» превращается в «02:00 следующего дня»
и в ответе, и (на проде, где колонка timestamptz) в реальном хранении.

Второй эффект: значение только с датой («2026-09-19», без времени) сейчас
парсится как полночь — naive datetime(2026,9,19,0,0,0), которая тоже трактуется
как UTC и превращается в "2026-09-19T03:00:00+0300" (наблюдалось на дев-стенде).
Хуже того — `ON CONFLICT (user_id, measured_at) DO UPDATE` схлопывает ВСЕ
замеры без явного времени за один день в одну и ту же полночь: два разных
замера («утром 130/85, вечером 140/90») перезаписывают друг друга, тихо теряя
один из них.

Ожидаемое поведение после фикса:
  - naive datetime с явным временем → локализуется в таймзоне ПОЛЬЗОВАТЕЛЯ
    (не UTC): "2026-09-21T23:00:00" (Europe/Moscow) остаётся 21.09 23:00 МСК.
  - значение только с датой → сочетается с ТЕКУЩИМ временем суток пользователя
    (не с полночью) — так два раздельных замера за один день не сталкиваются
    на ON CONFLICT.
  - повтор ИДЕНТИЧНОГО вызова (то же значение measured_at с явным временем) —
    по-прежнему одна запись (идемпотентность/апдейт не сломаны).
  - ответ тула возвращает measured_at в таймзоне пользователя.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "telegram-bot"))

import pytest
from datetime import timedelta, timezone
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import Base, User, BloodPressureLog

MSK = timezone(timedelta(hours=3))


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
    user = User(
        telegram_id=895655,
        first_name="Sasha",
        username="alexlyskovsky",
        cohort="owner",
        container_id="nc-sasha",
        pack_name="bariatric",
        health_token="hvt_old_token",
        jwt_secret="test_secret",
        is_active=True,
    )
    session.add(user)
    session.commit()
    try:
        yield session
    finally:
        session.close()


def _make_mock_user():
    user = MagicMock()
    user.telegram_id = 895655
    user.cohort = "owner"
    user.timezone = "Europe/Moscow"
    user.onboarding_data = {}
    return user


@pytest.fixture
def client(db_session, monkeypatch):
    from webhook import agent_tools as agent_tools_api
    from webhook.jwt_auth import get_agent_user, get_db

    monkeypatch.setattr(db_session, "close", lambda: None)

    app = FastAPI()
    app.include_router(agent_tools_api.router)

    mock_user = _make_mock_user()
    app.dependency_overrides[get_agent_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: db_session

    return TestClient(app)


def _bp_rows(db_session):
    return db_session.query(BloodPressureLog).filter_by(user_id=895655).order_by(BloodPressureLog.id).all()


# ── naive datetime не должно уезжать в UTC ───────────────────────────────────


def test_naive_datetime_localized_to_user_tz_not_utc(client, db_session):
    """«2026-09-21T23:00» для Europe/Moscow → 21.09 23:00 МСК, а не 22.09."""
    r = client.post(
        "/api/agent/log_bp",
        json={"systolic": 120, "diastolic": 78, "measured_at": "2026-09-21T23:00:00"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["measured_at"].startswith("2026-09-21T23:00:00"), (
        f"naive-время уехало на другие сутки: {body['measured_at']!r}"
    )
    assert "2026-09-22" not in body["measured_at"]

    row = _bp_rows(db_session)[0]
    # Хранимое значение должно соответствовать 21.09 23:00 по Москве (+03:00),
    # т.е. в UTC это 20:00 того же дня — НЕ полночь/утро следующего дня.
    stored = row.measured_at
    if stored.tzinfo is None:
        stored = stored.replace(tzinfo=timezone.utc)
    assert stored.astimezone(MSK).strftime("%Y-%m-%dT%H:%M:%S") == "2026-09-21T23:00:00"


# ── два замера одной датой (без времени) не должны перетирать друг друга ────


def test_two_date_only_readings_same_day_create_two_rows(client, db_session):
    """«вчера утром 130/85, вечером 140/90» переданы только датой (без времени)
    — обе записи должны сохраниться, не схлопнуться в одну через ON CONFLICT."""
    r1 = client.post(
        "/api/agent/log_bp",
        json={"systolic": 130, "diastolic": 85, "measured_at": "2026-09-19"},
    )
    r2 = client.post(
        "/api/agent/log_bp",
        json={"systolic": 140, "diastolic": 90, "measured_at": "2026-09-19"},
    )
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text

    rows = _bp_rows(db_session)
    assert len(rows) == 2, (
        f"замеры схлопнулись в {len(rows)} запись(и) вместо 2: {[(r.systolic, r.diastolic) for r in rows]}"
    )
    systolics = sorted(r.systolic for r in rows)
    assert systolics == [130, 140]


# ── повтор идентичного вызова с полным временем — идемпотентность ───────────


def test_identical_retry_with_full_time_stays_one_row(client, db_session):
    payload = {"systolic": 125, "diastolic": 80, "pulse": 62, "measured_at": "2026-09-21T08:00:00+03:00"}
    r1 = client.post("/api/agent/log_bp", json=payload)
    r2 = client.post("/api/agent/log_bp", json=payload)
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text

    rows = _bp_rows(db_session)
    assert len(rows) == 1, f"идентичный повтор создал дубликат: {len(rows)} записей"
    assert rows[0].systolic == 125
    assert rows[0].diastolic == 80
