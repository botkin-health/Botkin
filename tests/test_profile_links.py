"""Tests for GET /api/profile/links endpoint."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from database.models import Base, User
from webhook.profile_api import router


# ── App fixture ───────────────────────────────────────────────────────────────

@pytest.fixture
def app_client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    app = FastAPI()
    app.include_router(router)

    with Session() as db:
        user = User(
            telegram_id=895655,
            first_name="Sasha",
            cohort="owner",
            is_active=True,
            share_token=None,
        )
        db.add(user)
        db.commit()

    def override_session():
        with Session() as s:
            yield s

    # Patch auth so tests don't need real Telegram initData
    with patch("webhook.profile_api.get_tg_user", return_value={"id": 895655}):
        # Patch SessionLocal used inside the endpoint
        with patch("webhook.profile_api.SessionLocal", Session):
            client = TestClient(app, raise_server_exceptions=True)
            yield client, Session

    Base.metadata.drop_all(bind=engine)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_links_creates_share_token_if_missing(app_client):
    """Endpoint auto-creates share_token when user has none; returns dashboard URL."""
    client, Session = app_client
    r = client.get("/api/profile/links")
    assert r.status_code == 200
    data = r.json()
    assert data["dashboard_url"] is not None
    assert "botkin.health/mc/" in data["dashboard_url"]

    # Token must be persisted in DB
    with Session() as db:
        user = db.query(User).filter_by(telegram_id=895655).first()
        assert user.share_token is not None


def test_links_returns_existing_token(app_client):
    """Endpoint returns the existing token without regenerating it."""
    client, Session = app_client

    # Pre-set a token
    with Session() as db:
        user = db.query(User).filter_by(telegram_id=895655).first()
        user.share_token = "preset-token-abc"
        db.commit()

    r = client.get("/api/profile/links")
    assert r.status_code == 200
    assert r.json()["dashboard_url"] == "https://botkin.health/mc/preset-token-abc"


def test_links_unknown_user_returns_null(app_client):
    """Endpoint returns null dashboard_url when user is not found."""
    client, _ = app_client
    with patch("webhook.profile_api.get_tg_user", return_value={"id": 999999}):
        r = client.get("/api/profile/links")
    assert r.status_code == 200
    assert r.json()["dashboard_url"] is None
