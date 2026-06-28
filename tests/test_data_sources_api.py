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


def test_data_sources_returns_all_services(client):
    r = client.get("/api/profile/data_sources")
    assert r.status_code == 200
    sources = r.json()["sources"]
    ids = {s["id"] for s in sources}
    assert ids == {"garmin", "apple_health", "health_connect", "zepp", "netatmo", "cgm"}


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


def test_health_connect_connected_when_recent_activity(client, api_db):
    today = date.today().isoformat()
    api_db.execute(
        text("INSERT INTO activity_log (user_id, date, source) VALUES (:uid, :d, :src)"),
        {"uid": 895655, "d": today, "src": "health_connect"},
    )
    api_db.commit()

    sources = {s["id"]: s for s in client.get("/api/profile/data_sources").json()["sources"]}
    assert sources["health_connect"]["connected"] is True
    assert sources["health_connect"]["last_updated"] == today


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


VALID_FLOWS = {"inline_token", "tg_deeplink", "coming_soon"}


def test_connect_info_schema(client):
    """Каждый источник возвращает connect_info с допустимым flow."""
    sources = client.get("/api/profile/data_sources").json()["sources"]
    for s in sources:
        assert "connect_info" in s, f"no connect_info for {s['id']}"
        assert s["connect_info"]["flow"] in VALID_FLOWS, f"bad flow for {s['id']}"


def test_garmin_zepp_netatmo_flow_coming_soon(client):
    """Garmin, Zepp, Netatmo всегда coming_soon."""
    sources = {s["id"]: s for s in client.get("/api/profile/data_sources").json()["sources"]}
    for src_id in ("garmin", "zepp", "netatmo"):
        assert sources[src_id]["connect_info"]["flow"] == "coming_soon"


def test_cgm_flow_tg_deeplink(client):
    """CGM возвращает tg_deeplink с командой connect_cgm."""
    sources = {s["id"]: s for s in client.get("/api/profile/data_sources").json()["sources"]}
    info = sources["cgm"]["connect_info"]
    assert info["flow"] == "tg_deeplink"
    assert "connect_cgm" in info["deeplink"]


def test_apple_health_returns_token_when_disconnected(client, monkeypatch):
    """Apple Health возвращает health_token когда не подключён."""
    monkeypatch.setattr(
        "database.crud.get_or_create_health_token",
        lambda db, uid: "hvt_test_token",
    )
    sources = {s["id"]: s for s in client.get("/api/profile/data_sources").json()["sources"]}
    info = sources["apple_health"]["connect_info"]
    assert info["flow"] == "inline_token"
    assert info["health_token"] == "hvt_test_token"


def test_apple_health_no_token_when_connected(client, api_db, monkeypatch):
    """Apple Health не возвращает health_token когда подключён."""
    from datetime import date
    from sqlalchemy import text

    today = date.today().isoformat()
    api_db.execute(
        text("INSERT INTO activity_log (user_id, date, source) VALUES (:uid, :d, :src)"),
        {"uid": 895655, "d": today, "src": "apple_health_v2"},
    )
    api_db.commit()
    monkeypatch.setattr(
        "database.crud.get_or_create_health_token",
        lambda db, uid: "hvt_test_token",
    )
    sources = {s["id"]: s for s in client.get("/api/profile/data_sources").json()["sources"]}
    info = sources["apple_health"]["connect_info"]
    assert info["flow"] == "inline_token"
    assert info["health_token"] is None


def test_health_connect_returns_token_when_disconnected(client, monkeypatch):
    """Health Connect возвращает health_token когда не подключён."""
    monkeypatch.setattr(
        "database.crud.get_or_create_health_token",
        lambda db, uid: "hvt_test_token",
    )
    sources = {s["id"]: s for s in client.get("/api/profile/data_sources").json()["sources"]}
    info = sources["health_connect"]["connect_info"]
    assert info["flow"] == "inline_token"
    assert info["health_token"] == "hvt_test_token"
