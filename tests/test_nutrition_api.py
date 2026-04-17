import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

import pytest
from datetime import date, time
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import Base
from database.crud import create_nutrition_log


@pytest.fixture
def api_db():
    """Separate in-memory SQLite DB using StaticPool — safe for threaded TestClient."""
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
    """Build a FastAPI app with only the nutrition router, stub auth + SessionLocal."""
    from fastapi import FastAPI
    from webhook import nutrition_api

    # Patch close() on the session so production code's db.close() is a no-op
    monkeypatch.setattr(api_db, "close", lambda: None)
    monkeypatch.setattr(nutrition_api, "SessionLocal", lambda: api_db)
    app = FastAPI()
    app.include_router(nutrition_api.router)
    from webhook.apple_health import get_tg_user

    app.dependency_overrides[get_tg_user] = lambda: {"id": 895655}
    return TestClient(app)


def test_get_day_empty(client):
    r = client.get("/api/day?date=2026-04-17")
    assert r.status_code == 200
    body = r.json()
    assert body["date"] == "2026-04-17"
    assert body["meals"] == []
    assert body["totals_day"] == {"kcal": 0, "p": 0, "f": 0, "c": 0, "fib": 0}
    assert set(body["goals"].keys()) == {"kcal", "protein", "fats", "carbs", "fiber"}


def test_get_day_with_meals(client, api_db):
    create_nutrition_log(
        db=api_db,
        user_id=895655,
        date=date(2026, 4, 17),
        meal_time=time(13, 0),
        meal_name="Обед",
        items=[
            {
                "product": "Курица",
                "weight_g": 100,
                "calories": 165,
                "protein": 31,
                "fats": 3.6,
                "carbs": 0,
                "fiber": 0,
            }
        ],
        totals={"calories": 165, "protein": 31, "fats": 3.6, "carbs": 0, "fiber": 0},
    )
    r = client.get("/api/day?date=2026-04-17")
    assert r.status_code == 200
    body = r.json()
    assert len(body["meals"]) == 1
    meal = body["meals"][0]
    assert meal["slot"] == "lunch"
    assert meal["meal_name"] == "Обед"
    assert meal["meal_time"] == "13:00"
    assert len(meal["items"]) == 1
    item = meal["items"][0]
    assert item == {
        "idx": 0,
        "name": "Курица",
        "weight": 100,
        "kcal": 165,
        "p": 31,
        "f": 3.6,
        "c": 0,
        "fib": 0,
    }
    assert body["totals_day"]["kcal"] == 165


def test_get_day_invalid_date(client):
    r = client.get("/api/day?date=not-a-date")
    assert r.status_code == 400


def test_get_day_user_scoped(client, api_db):
    create_nutrition_log(
        db=api_db,
        user_id=111,
        date=date(2026, 4, 17),
        meal_time=time(13, 0),
        meal_name="Обед",
        items=[
            {
                "product": "Пицца",
                "weight_g": 300,
                "calories": 800,
                "protein": 30,
                "fats": 30,
                "carbs": 90,
                "fiber": 4,
            }
        ],
        totals={"calories": 800, "protein": 30, "fats": 30, "carbs": 90, "fiber": 4},
    )
    r = client.get("/api/day?date=2026-04-17")
    assert r.json()["meals"] == []
