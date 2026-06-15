"""Tests for GET /api/dashboard_url — mini-app dashboard tab token endpoint.

The endpoint hands the authenticated Telegram user their share_token so the
mini-app can embed /mc/{token} in an iframe. It must be idempotent (reuse the
existing token) and 404 when the user row doesn't exist yet.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import Base, User


@pytest.fixture
def api_db():
    """In-memory SQLite using StaticPool — safe for threaded TestClient."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(api_db, monkeypatch):
    """FastAPI app with only the profile router, stub auth (id=895655) + SessionLocal."""
    import database
    from webhook import profile_api
    from webhook.tg_auth import get_tg_user

    # Endpoint calls `from database import SessionLocal` at call time → patch the source.
    monkeypatch.setattr(api_db, "close", lambda: None)
    monkeypatch.setattr(database, "SessionLocal", lambda: api_db)

    app = FastAPI()
    app.include_router(profile_api.router)
    app.dependency_overrides[get_tg_user] = lambda: {"id": 895655}
    return TestClient(app)


def test_dashboard_url_generates_token_for_user_without_one(client, api_db):
    # Arrange — user exists but has no share_token yet
    api_db.add(User(telegram_id=895655, first_name="Test"))
    api_db.commit()

    # Act
    r = client.get("/api/dashboard_url")

    # Assert
    assert r.status_code == 200
    token = r.json()["token"]
    assert token  # non-empty


def test_dashboard_url_returns_existing_token(client, api_db):
    api_db.add(User(telegram_id=895655, first_name="Test", share_token="preset-token-xyz"))
    api_db.commit()

    r = client.get("/api/dashboard_url")

    assert r.status_code == 200
    assert r.json()["token"] == "preset-token-xyz"


def test_dashboard_url_is_idempotent(client, api_db):
    api_db.add(User(telegram_id=895655, first_name="Test"))
    api_db.commit()

    first = client.get("/api/dashboard_url").json()["token"]
    second = client.get("/api/dashboard_url").json()["token"]

    assert first == second  # token generated once, reused thereafter


def test_dashboard_url_404_when_no_user(client):
    # No user row inserted — mini-app opened before /start
    r = client.get("/api/dashboard_url")
    assert r.status_code == 404
