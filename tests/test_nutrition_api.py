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


def test_post_item_creates_new_meal(client, api_db, monkeypatch):
    def fake_process(description, **kwargs):
        return (
            [
                {
                    "product": description,
                    "weight_g": 180,
                    "calories": 220,
                    "protein": 38,
                    "fats": 6,
                    "carbs": 0,
                    "fiber": 0,
                }
            ],
            {"calories": 220, "protein": 38, "fats": 6, "carbs": 0, "fiber": 0},
        )

    from webhook import nutrition_api

    monkeypatch.setattr(nutrition_api, "process_meal_description", fake_process)

    r = client.post(
        "/api/meal/item",
        json={
            "date": "2026-04-17",
            "slot": "lunch",
            "name": "Курица грудка",
            "weight": 180,
            "source": "manual",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["item"]["name"] == "Курица грудка"
    assert body["item"]["weight"] == 180
    assert body["item"]["kcal"] == 220
    assert "meal_id" in body

    day = client.get("/api/day?date=2026-04-17").json()
    assert len(day["meals"]) == 1
    assert day["meals"][0]["slot"] == "lunch"
    assert day["meals"][0]["meal_name"] == "Обед"
    assert day["meals"][0]["meal_time"] == "13:00"


def test_post_item_appends_to_existing_slot(client, api_db, monkeypatch):
    from webhook import nutrition_api

    monkeypatch.setattr(
        nutrition_api,
        "process_meal_description",
        lambda desc, **_: (
            [{"product": desc, "weight_g": 100, "calories": 50, "protein": 1, "fats": 0, "carbs": 12, "fiber": 0}],
            {"calories": 50, "protein": 1, "fats": 0, "carbs": 12, "fiber": 0},
        ),
    )
    create_nutrition_log(
        db=api_db,
        user_id=895655,
        date=date(2026, 4, 17),
        meal_time=time(13, 0),
        meal_name="Обед",
        items=[
            {"product": "Рис", "weight_g": 150, "calories": 195, "protein": 4.5, "fats": 1.5, "carbs": 42, "fiber": 2}
        ],
        totals={"calories": 195, "protein": 4.5, "fats": 1.5, "carbs": 42, "fiber": 2},
    )
    r = client.post(
        "/api/meal/item",
        json={
            "date": "2026-04-17",
            "slot": "lunch",
            "name": "Яблоко",
            "weight": 100,
            "source": "manual",
        },
    )
    assert r.status_code == 201
    day = client.get("/api/day?date=2026-04-17").json()
    assert len(day["meals"]) == 1
    assert len(day["meals"][0]["items"]) == 2
    assert day["meals"][0]["totals"]["kcal"] == 245


def test_post_item_bad_slot_400(client):
    r = client.post(
        "/api/meal/item",
        json={
            "date": "2026-04-17",
            "slot": "brunch",
            "name": "x",
            "weight": 100,
            "source": "manual",
        },
    )
    assert r.status_code == 400


def test_patch_item_rescales(client, api_db):
    row = create_nutrition_log(
        db=api_db,
        user_id=895655,
        date=date(2026, 4, 17),
        meal_time=time(13, 0),
        meal_name="Обед",
        items=[
            {"product": "Курица", "weight_g": 100, "calories": 165, "protein": 31, "fats": 3.6, "carbs": 0, "fiber": 0}
        ],
        totals={"calories": 165, "protein": 31, "fats": 3.6, "carbs": 0, "fiber": 0},
    )
    r = client.patch("/api/meal/item", json={"meal_id": row.id, "idx": 0, "weight": 200})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["item"]["weight"] == 200
    assert body["item"]["kcal"] == 330
    assert body["totals"]["kcal"] == 330


def test_patch_item_wrong_user_404(client, api_db):
    row = create_nutrition_log(
        db=api_db,
        user_id=111,
        date=date(2026, 4, 17),
        meal_time=time(13, 0),
        meal_name="Обед",
        items=[{"product": "X", "weight_g": 100, "calories": 100, "protein": 0, "fats": 0, "carbs": 0, "fiber": 0}],
        totals={"calories": 100, "protein": 0, "fats": 0, "carbs": 0, "fiber": 0},
    )
    r = client.patch("/api/meal/item", json={"meal_id": row.id, "idx": 0, "weight": 200})
    assert r.status_code == 404


def test_patch_meal_fields(client, api_db):
    row = create_nutrition_log(
        db=api_db,
        user_id=895655,
        date=date(2026, 4, 17),
        meal_time=time(13, 0),
        meal_name="Обед",
        items=[{"product": "X", "weight_g": 100, "calories": 100, "protein": 1, "fats": 1, "carbs": 1, "fiber": 0}],
        totals={"calories": 100, "protein": 1, "fats": 1, "carbs": 1, "fiber": 0},
    )
    r = client.patch("/api/meal", json={"meal_id": row.id, "meal_name": "Поздний обед", "meal_time": "15:30"})
    assert r.status_code == 200
    day = client.get("/api/day?date=2026-04-17").json()
    assert day["meals"][0]["meal_name"] == "Поздний обед"
    assert day["meals"][0]["meal_time"] == "15:30"
    assert day["meals"][0]["slot"] == "snack"


def test_delete_meal_item(client, api_db):
    row = create_nutrition_log(
        db=api_db,
        user_id=895655,
        date=date(2026, 4, 17),
        meal_time=time(13, 0),
        meal_name="Обед",
        items=[
            {"product": "A", "weight_g": 100, "calories": 100, "protein": 1, "fats": 1, "carbs": 1, "fiber": 0},
            {"product": "B", "weight_g": 100, "calories": 50, "protein": 0, "fats": 0, "carbs": 10, "fiber": 0},
        ],
        totals={"calories": 150, "protein": 1, "fats": 1, "carbs": 11, "fiber": 0},
    )
    r = client.delete(f"/api/meal/item?meal_id={row.id}&idx=0")
    assert r.status_code == 200
    assert r.json()["removed"]["name"] == "A"
    day = client.get("/api/day?date=2026-04-17").json()
    assert len(day["meals"][0]["items"]) == 1


def test_delete_last_item_removes_meal_api(client, api_db):
    row = create_nutrition_log(
        db=api_db,
        user_id=895655,
        date=date(2026, 4, 17),
        meal_time=time(13, 0),
        meal_name="Обед",
        items=[{"product": "A", "weight_g": 100, "calories": 100, "protein": 1, "fats": 1, "carbs": 1, "fiber": 0}],
        totals={"calories": 100, "protein": 1, "fats": 1, "carbs": 1, "fiber": 0},
    )
    r = client.delete(f"/api/meal/item?meal_id={row.id}&idx=0")
    assert r.status_code == 200
    day = client.get("/api/day?date=2026-04-17").json()
    assert day["meals"] == []


def test_delete_meal_whole(client, api_db):
    row = create_nutrition_log(
        db=api_db,
        user_id=895655,
        date=date(2026, 4, 17),
        meal_time=time(13, 0),
        meal_name="Обед",
        items=[{"product": "A", "weight_g": 100, "calories": 100, "protein": 1, "fats": 1, "carbs": 1, "fiber": 0}],
        totals={"calories": 100, "protein": 1, "fats": 1, "carbs": 1, "fiber": 0},
    )
    r = client.delete(f"/api/meal?meal_id={row.id}")
    assert r.status_code == 204
    day = client.get("/api/day?date=2026-04-17").json()
    assert day["meals"] == []


def test_get_favorites(client, api_db):
    from datetime import timedelta

    today = date(2026, 4, 17)
    create_nutrition_log(
        db=api_db,
        user_id=895655,
        date=today - timedelta(days=1),
        meal_time=time(9, 0),
        meal_name="Завтрак",
        items=[
            {"product": "Кофе", "weight_g": 200, "calories": 10, "protein": 0, "fats": 0, "carbs": 2, "fiber": 0},
            {"product": "Овсянка", "weight_g": 60, "calories": 240, "protein": 8, "fats": 5, "carbs": 42, "fiber": 6},
        ],
        totals={"calories": 250, "protein": 8, "fats": 5, "carbs": 44, "fiber": 6},
    )
    r = client.get("/api/favorites?limit=15")
    assert r.status_code == 200
    body = r.json()
    names = [x["name"] for x in body]
    assert "Кофе" in names
    assert "Овсянка" in names
    for rec in body:
        assert set(rec.keys()) >= {"name", "default_weight", "last_used", "per_100"}
        assert set(rec["per_100"].keys()) == {"kcal", "p", "f", "c", "fib"}


def test_get_favorites_respects_limit(client, api_db):
    r = client.get("/api/favorites?limit=0")
    assert r.status_code == 422
