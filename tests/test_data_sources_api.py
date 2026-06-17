"""Tests for GET /api/profile/data_sources — список источников данных (#149).

Проверяет:
- структуру ответа (поля id, name, icon, connected, last_updated)
- корректное определение connected=True/False по данным в activity_log/weights/glucose_readings
- Netatmo — источник файловый, не привязан к БД
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import Base


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    with eng.connect() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS activity_log "
            "(id INTEGER PRIMARY KEY, user_id INTEGER, date TEXT, source TEXT, total_calories REAL)"
        ))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS weights "
            "(id INTEGER PRIMARY KEY, user_id INTEGER, measured_at TEXT, weight REAL, source TEXT)"
        ))
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS glucose_readings "
            "(id INTEGER PRIMARY KEY, user_id INTEGER, measured_at TEXT, value REAL)"
        ))
        conn.commit()
    yield eng
    Base.metadata.drop_all(bind=eng)


@pytest.fixture
def api_db(engine):
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client(api_db, monkeypatch):
    import database
    from webhook import profile_api
    from webhook.tg_auth import get_tg_user

    monkeypatch.setattr(api_db, "close", lambda: None)
    monkeypatch.setattr(database, "SessionLocal", lambda: api_db)

    app = FastAPI()
    app.include_router(profile_api.router)
    app.dependency_overrides[get_tg_user] = lambda: {"id": 895655}
    return TestClient(app)


def test_data_sources_returns_all_five_services(client):
    r = client.get("/api/profile/data_sources")
    assert r.status_code == 200
    sources = r.json()["sources"]
    ids = {s["id"] for s in sources}
    assert ids == {"garmin", "apple_health", "zepp", "netatmo", "cgm"}


def test_data_sources_response_schema(client):
    sources = client.get("/api/profile/data_sources").json()["sources"]
    for s in sources:
        assert "id" in s
        assert "name" in s
        assert "icon" in s
        assert "connected" in s
        assert "last_updated" in s


def test_garmin_connected_when_recent_activity(client, api_db):
    today = date.today().isoformat()
    api_db.execute(
        text("INSERT INTO activity_log (user_id, date, source, total_calories) VALUES (:uid, :d, :src, 2000)"),
        {"uid": 895655, "d": today, "src": "garmin"},
    )
    api_db.commit()

    sources = {s["id"]: s for s in client.get("/api/profile/data_sources").json()["sources"]}
    assert sources["garmin"]["connected"] is True
    assert sources["garmin"]["last_updated"] == today


def test_garmin_not_connected_when_no_data(client):
    sources = {s["id"]: s for s in client.get("/api/profile/data_sources").json()["sources"]}
    assert sources["garmin"]["connected"] is False
    assert sources["garmin"]["last_updated"] is None


def test_apple_health_connected_when_recent_activity(client, api_db):
    today = date.today().isoformat()
    api_db.execute(
        text("INSERT INTO activity_log (user_id, date, source) VALUES (:uid, :d, :src)"),
        {"uid": 895655, "d": today, "src": "apple_health_v2"},
    )
    api_db.commit()

    sources = {s["id"]: s for s in client.get("/api/profile/data_sources").json()["sources"]}
    assert sources["apple_health"]["connected"] is True


def test_old_data_not_counted_as_connected(client, api_db):
    old_date = (date.today() - timedelta(days=35)).isoformat()
    api_db.execute(
        text("INSERT INTO activity_log (user_id, date, source) VALUES (:uid, :d, :src)"),
        {"uid": 895655, "d": old_date, "src": "garmin"},
    )
    api_db.commit()

    sources = {s["id"]: s for s in client.get("/api/profile/data_sources").json()["sources"]}
    assert sources["garmin"]["connected"] is False


def test_netatmo_not_connected_when_no_file(client, monkeypatch):
    # Netatmo — файловый источник; без файла → not connected
    monkeypatch.setattr(Path, "exists", lambda self: False)
    sources = {s["id"]: s for s in client.get("/api/profile/data_sources").json()["sources"]}
    assert sources["netatmo"]["connected"] is False
