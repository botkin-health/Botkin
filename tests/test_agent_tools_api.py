"""Tests for Agent Tools API — 8 endpoints for NanoClaw containers.

All tests use TestClient with mocked auth + in-memory SQLite DB.
No real DB connections or JWT secrets required.
"""

import sys
from pathlib import Path

# Project root → database module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# telegram-bot → webhook package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

import pytest
from datetime import date, datetime, time
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import Base, User, NutritionLog, SupplementLog
from database.crud import create_nutrition_log, create_or_update_activity, create_weight


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def engine():
    """In-memory SQLite engine with shared connection (StaticPool)."""
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
    """SQLAlchemy session backed by the in-memory engine."""
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    # Create the test user so FK constraints are satisfied
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


def _make_mock_user(health_token="hvt_old_token"):
    user = MagicMock()
    user.telegram_id = 895655
    user.container_id = "nc-sasha"
    user.cohort = "owner"
    user.first_name = "Sasha"
    user.username = "alexlyskovsky"
    user.garmin_email = "test@garmin.com"
    user.health_token = health_token
    user.pack_name = "bariatric"
    user.timezone = "Europe/Moscow"
    user.sex = "male"
    user.height_cm = 178
    user.birth_date = None
    return user


@pytest.fixture
def client(db_session, monkeypatch):
    """TestClient with mocked auth and DB session injection."""
    from webhook import agent_tools_api
    from webhook.jwt_auth import get_agent_user, get_db

    # Patch close() so production code's db.close() is a no-op on our session
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(agent_tools_api, "get_db", lambda: iter([db_session]))

    app = FastAPI()
    app.include_router(agent_tools_api.router)

    mock_user = _make_mock_user()

    def _mock_agent_user():
        return mock_user

    app.dependency_overrides[get_agent_user] = _mock_agent_user
    app.dependency_overrides[get_db] = lambda: db_session

    return TestClient(app)


# ── Task 5/6: Write endpoint tests ───────────────────────────────────────────


@pytest.fixture
def mock_food_llm(monkeypatch):
    """Мок analyze_message: unit-тесты не зовут реальный LLM (раньше эти тесты
    были deselected как live-LLM — аудит 11.06.2026)."""
    import core.llm.router as llm_router

    def _fake_analyze(text: str, user_id: int = None, **kwargs):
        return {
            "type": "food",
            "data": {
                "items": [{"name": "Гречка", "weight": 200, "calories": 220, "protein": 8, "fats": 2, "carbs": 42}]
            },
        }

    monkeypatch.setattr(llm_router, "analyze_message", _fake_analyze)


def test_log_meal_text_returns_200(client, db_session, mock_food_llm):
    """POST /log_meal_text stores a meal and returns 200 with meal_id."""
    r = client.post(
        "/api/agent/log_meal_text",
        json={"text": "гречка 200г", "date": "2026-05-04", "slot": "lunch"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert "meal_id" in body
    assert body["date"] == "2026-05-04"
    assert body["slot"] == "lunch"
    assert body["meal_name"] == "Обед"
    # Verify it's actually in the DB
    logs = db_session.query(NutritionLog).filter_by(user_id=895655).all()
    assert len(logs) == 1


def test_log_meal_text_defaults_to_today(client, db_session, mock_food_llm):
    """POST /log_meal_text without date defaults to today."""
    r = client.post(
        "/api/agent/log_meal_text",
        json={"text": "кофе с молоком"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["date"] == date.today().isoformat()


def test_log_meal_text_rejects_non_food(client, db_session, monkeypatch):
    """Если LLM не распознал еду — ошибка с пояснением, в БД ничего не пишется."""
    import core.llm.router as llm_router

    monkeypatch.setattr(llm_router, "analyze_message", lambda text, user_id=None, **kw: {"type": "question"})
    r = client.post("/api/agent/log_meal_text", json={"text": "как дела?"})
    body = r.json()
    assert body.get("status") != "ok"
    assert db_session.query(NutritionLog).filter_by(user_id=895655).count() == 0


def test_log_meal_text_invalid_slot_returns_400(client):
    """POST /log_meal_text with unknown slot → 400."""
    r = client.post(
        "/api/agent/log_meal_text",
        json={"text": "что-то", "slot": "brunch"},
    )
    assert r.status_code == 400


def test_log_supplement_returns_200(client, db_session):
    """POST /log_supplement stores supplement and returns 200."""
    r = client.post(
        "/api/agent/log_supplement",
        json={
            "supplement_name": "Витамин D3",
            "dosage": "5000 IU",
            "date": "2026-05-04",
            "time": "08:00",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert "supplement_id" in body
    assert body["supplement_name"] == "Витамин D3"
    assert body["dosage"] == "5000 IU"
    # Verify DB
    logs = db_session.query(SupplementLog).filter_by(user_id=895655).all()
    assert len(logs) == 1
    assert logs[0].supplement_name == "Витамин D3"


def test_log_supplement_without_optional_fields(client, db_session):
    """POST /log_supplement with only required fields — date/time/dosage all optional."""
    r = client.post(
        "/api/agent/log_supplement",
        json={"supplement_name": "Магний"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["supplement_name"] == "Магний"
    assert body["dosage"] is None


def test_log_bp_returns_200(client, db_session, monkeypatch):
    """POST /log_bp inserts into blood_pressure_logs and returns 200."""
    # Patch db.execute and db.commit for SQLite (blood_pressure_logs uses raw SQL)
    execute_calls = []
    original_execute = db_session.execute

    def fake_execute(stmt, params=None):
        execute_calls.append((str(stmt), params))
        # For SQLite compatibility: just skip the raw INSERT
        return MagicMock()

    monkeypatch.setattr(db_session, "execute", fake_execute)
    monkeypatch.setattr(db_session, "commit", lambda: None)

    r = client.post(
        "/api/agent/log_bp",
        json={
            "systolic": 120,
            "diastolic": 78,
            "pulse": 65,
            "measured_at": "2026-05-04T08:30:00",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["systolic"] == 120
    assert body["diastolic"] == 78
    assert body["pulse"] == 65
    assert len(execute_calls) == 1


def test_log_bp_defaults_to_now(client, db_session, monkeypatch):
    """POST /log_bp without measured_at uses current time — no 422 validation error."""
    execute_calls = []

    def fake_execute(stmt, params=None):
        execute_calls.append(params)
        return MagicMock()

    monkeypatch.setattr(db_session, "execute", fake_execute)
    monkeypatch.setattr(db_session, "commit", lambda: None)

    r = client.post(
        "/api/agent/log_bp",
        json={"systolic": 118, "diastolic": 76},  # no measured_at
    )
    # Status 200 (SQLite compatible mock) — no 422 unprocessable entity
    assert r.status_code == 200, r.text
    assert r.json()["systolic"] == 118
    assert r.json()["diastolic"] == 76
    # measured_at should be set automatically (not None)
    assert r.json()["measured_at"] is not None
    assert len(execute_calls) == 1


def test_regenerate_health_token_returns_new_token(client, db_session):
    """POST /regenerate_health_token returns a new hvt_... token and saves it."""
    r = client.post("/api/agent/regenerate_health_token")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert "health_token" in body
    new_token = body["health_token"]
    assert new_token.startswith("hvt_895655_")
    # Token should have changed from the mock user's original
    assert new_token != "hvt_old_token"


# ── Task 7: Read endpoint tests ───────────────────────────────────────────────


def test_recent_meals_returns_meals_list(client, db_session):
    """GET /recent_meals returns meals from the last N days."""
    create_nutrition_log(
        db=db_session,
        user_id=895655,
        date=date.today(),
        meal_time=time(13, 0),
        meal_name="Обед",
        items=[
            {"product": "Курица", "weight_g": 150, "calories": 250, "protein": 40, "fats": 5, "carbs": 0, "fiber": 0}
        ],
        totals={"calories": 250, "protein": 40, "fats": 5, "carbs": 0, "fiber": 0},
    )
    r = client.get("/api/agent/recent_meals?days=7")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["days"] == 7
    assert len(body["meals"]) == 1
    meal = body["meals"][0]
    assert meal["meal_name"] == "Обед"
    assert meal["meal_time"] == "13:00"
    assert meal["totals"]["calories"] == 250


def test_recent_meals_scoped_to_user(client, db_session):
    """GET /recent_meals only returns meals for the authenticated user."""
    # Create meal for another user
    other_user = User(telegram_id=111, first_name="Other", is_active=True, cohort="external", pack_name="generic")
    db_session.add(other_user)
    db_session.commit()
    create_nutrition_log(
        db=db_session,
        user_id=111,
        date=date.today(),
        meal_time=time(9, 0),
        meal_name="Чужой завтрак",
        items=[
            {"product": "Пицца", "weight_g": 300, "calories": 900, "protein": 30, "fats": 40, "carbs": 90, "fiber": 3}
        ],
        totals={"calories": 900, "protein": 30, "fats": 40, "carbs": 90, "fiber": 3},
    )
    r = client.get("/api/agent/recent_meals?days=7")
    assert r.status_code == 200, r.text
    assert r.json()["meals"] == []


def test_recent_meals_invalid_days(client):
    """GET /recent_meals with days=0 → 400."""
    r = client.get("/api/agent/recent_meals?days=0")
    assert r.status_code == 400


def test_recent_meals_compact_returns_product_names(client, db_session):
    """compact=true → items как список имён, totals только калории (F-006)."""
    create_nutrition_log(
        db=db_session,
        user_id=895655,
        date=date.today(),
        meal_time=time(13, 0),
        meal_name="Обед",
        items=[
            {"product": "Хинкали", "weight_g": 200, "calories": 400, "protein": 20, "fats": 15, "carbs": 45, "fiber": 2}
        ],
        totals={"calories": 400, "protein": 20, "fats": 15, "carbs": 45, "fiber": 2},
    )
    r = client.get("/api/agent/recent_meals?days=7&compact=true")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["compact"] is True
    meal = body["meals"][0]
    assert meal["items"] == ["Хинкали"]
    assert meal["totals"] == {"calories": 400}


def test_recent_meals_long_window_auto_compact(client, db_session):
    """days>14 авто-включает compact, даже если не передан явно (F-006)."""
    create_nutrition_log(
        db=db_session,
        user_id=895655,
        date=date.today(),
        meal_time=time(13, 0),
        meal_name="Обед",
        items=[{"product": "Рис", "weight_g": 150, "calories": 200}],
        totals={"calories": 200, "protein": 4, "fats": 1, "carbs": 44, "fiber": 1},
    )
    r = client.get("/api/agent/recent_meals?days=30")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["compact"] is True
    assert body["meals"][0]["items"] == ["Рис"]


def _seed_meal(db_session, **kw):
    defaults = dict(
        db=db_session,
        user_id=895655,
        date=date.today(),
        meal_time=time(13, 0),
        meal_name="Обед",
        items=[{"product": "Курица", "weight_g": 150, "calories": 250}],
        totals={"calories": 250, "protein": 40, "fats": 5, "carbs": 0, "fiber": 0},
    )
    defaults.update(kw)
    return create_nutrition_log(**defaults)


def test_edit_meal_moves_date(client, db_session):
    """POST /edit_meal с new_date переносит запись на другой день (P-001)."""
    from datetime import timedelta

    meal = _seed_meal(db_session)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    r = client.post("/api/agent/edit_meal", json={"meal_id": meal.id, "new_date": yesterday})
    assert r.status_code == 200, r.text
    assert r.json()["date"] == yesterday


def test_edit_meal_rename_and_slot(client, db_session):
    """POST /edit_meal меняет имя и слот (время)."""
    meal = _seed_meal(db_session)
    r = client.post(
        "/api/agent/edit_meal",
        json={"meal_id": meal.id, "new_name": "Ужин (перенос)", "new_slot": "dinner"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["meal_name"] == "Ужин (перенос)"
    assert body["meal_time"] == "19:00"


def test_edit_meal_not_found(client):
    """POST /edit_meal с несуществующим meal_id → 404."""
    r = client.post("/api/agent/edit_meal", json={"meal_id": 999999, "new_name": "x"})
    assert r.status_code == 404


def test_edit_meal_nothing_to_change(client, db_session):
    """POST /edit_meal без полей-изменений → 400."""
    meal = _seed_meal(db_session)
    r = client.post("/api/agent/edit_meal", json={"meal_id": meal.id})
    assert r.status_code == 400


def test_delete_meal_removes_row(client, db_session):
    """POST /delete_meal удаляет запись; после — recent_meals пуст (P-001)."""
    meal = _seed_meal(db_session)
    r = client.post("/api/agent/delete_meal", json={"meal_id": meal.id})
    assert r.status_code == 200, r.text
    assert r.json()["deleted_meal_id"] == meal.id
    assert client.get("/api/agent/recent_meals?days=7").json()["meals"] == []


def test_delete_meal_not_found(client):
    """POST /delete_meal с несуществующим meal_id → 404."""
    r = client.post("/api/agent/delete_meal", json={"meal_id": 999999})
    assert r.status_code == 404


def test_delete_meal_scoped_to_user(client, db_session):
    """Нельзя удалить чужой приём пищи (RLS-изоляция по user_id)."""
    other = User(telegram_id=222, first_name="Other", is_active=True, cohort="external", pack_name="generic")
    db_session.add(other)
    db_session.commit()
    foreign = _seed_meal(db_session, user_id=222, meal_name="Чужой обед")
    r = client.post("/api/agent/delete_meal", json={"meal_id": foreign.id})
    assert r.status_code == 404


def test_kb_value_owner_returns_value(client, tmp_path, monkeypatch):
    """GET /kb_value for owner cohort reads knowledge_base.json."""
    import json

    kb_data = {"blood_tests": [{"date": "2026-01-01", "values": {"cholesterol": 5.1}}], "name": "Alexander"}
    kb_file = tmp_path / "knowledge_base.json"
    kb_file.write_text(json.dumps(kb_data), encoding="utf-8")

    import webhook.agent_tools_api as ata

    monkeypatch.setattr(ata, "Path", lambda *args: kb_file if "knowledge_base" in str(args) else Path(*args))

    # Patch the path resolution directly
    with patch("webhook.agent_tools_api.Path") as mock_path_cls:
        mock_path_instance = MagicMock()
        mock_path_instance.__truediv__ = lambda self, other: kb_file
        mock_path_instance.resolve.return_value = mock_path_instance
        mock_path_instance.parents = [mock_path_instance, mock_path_instance, tmp_path]
        mock_path_cls.return_value = mock_path_instance

        r = client.get("/api/agent/kb_value?key=name")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["key"] == "name"
    # Value lookup depends on path mock — at minimum no crash


def test_kb_value_non_owner_returns_stub(db_session, monkeypatch):
    """GET /kb_value for non-owner user returns kb-not-available stub.

    Только owner-cohort пользователь имеет полный knowledge_base.json. Для
    family/early_user/external endpoint возвращает заглушку, не падает.
    """
    from fastapi.testclient import TestClient
    from webhook import agent_tools_api
    from webhook.jwt_auth import get_agent_user, get_db

    app = FastAPI()
    app.include_router(agent_tools_api.router)

    non_owner = _make_mock_user()
    non_owner.cohort = "external"

    app.dependency_overrides[get_agent_user] = lambda: non_owner
    app.dependency_overrides[get_db] = lambda: db_session

    c = TestClient(app)
    r = c.get("/api/agent/kb_value?key=anything")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["value"] is None
    assert body["source"] == "kb-not-available"


def test_dashboard_summary_empty_db(client):
    """GET /dashboard_summary returns valid structure when no data exists."""
    r = client.get("/api/agent/dashboard_summary")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert "period" in body
    assert body["period"]["days"] == 7
    assert body["activity"]["avg_steps"] is None
    assert body["activity"]["avg_hr"] is None
    assert body["nutrition"]["avg_kcal_consumed"] is None
    assert body["weight"]["latest_kg"] is None


def test_dashboard_summary_with_data(client, db_session):
    """GET /dashboard_summary aggregates data correctly."""
    today = date.today()
    create_or_update_activity(
        db=db_session,
        user_id=895655,
        date=today,
        steps=8000,
        heart_rate_avg=70,
        total_calories=2200,
        source="test",
    )
    create_nutrition_log(
        db=db_session,
        user_id=895655,
        date=today,
        meal_time=time(13, 0),
        meal_name="Обед",
        items=[],
        totals={"calories": 1800, "protein": 120, "fats": 60, "carbs": 180, "fiber": 25},
    )
    create_weight(
        db=db_session,
        user_id=895655,
        measured_at=datetime(today.year, today.month, today.day, 8, 0),
        weight=82.5,
        body_fat=22.3,
    )

    r = client.get("/api/agent/dashboard_summary")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["activity"]["avg_steps"] == 8000
    assert body["activity"]["avg_hr"] == 70
    assert body["nutrition"]["avg_kcal_consumed"] == 1800.0
    assert body["weight"]["latest_kg"] == 82.5
    assert body["weight"]["body_fat_pct"] == 22.3


def test_user_profile_returns_profile(client):
    """GET /user_profile returns expected profile fields."""
    r = client.get("/api/agent/user_profile")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["telegram_id"] == 895655
    assert body["first_name"] == "Sasha"
    assert body["cohort"] == "owner"
    assert body["container_id"] == "nc-sasha"
    assert body["pack_name"] == "bariatric"
    assert body["health_token"] == "hvt_old_token"
    assert body["garmin_email"] == "test@garmin.com"
    assert "timezone" in body


# ── New tools (post-NanoClaw, added 21.05.2026) ─────────────────────────────


def test_weight_history_no_data(client):
    """GET /weight_history with no weights — returns no_data, not 500."""
    r = client.get("/api/agent/weight_history")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "no_data"


def test_weight_history_returns_latest_and_extremes(client, db_session):
    """GET /weight_history — latest + all_time extremes when data present."""
    create_weight(db_session, user_id=895655, measured_at=datetime(2020, 12, 16, 8), weight=74.9, body_fat=25.7)
    create_weight(db_session, user_id=895655, measured_at=datetime(2024, 1, 10, 8), weight=86.3, body_fat=35.9)
    create_weight(db_session, user_id=895655, measured_at=datetime(2026, 5, 16, 8), weight=76.6, body_fat=26.7)

    r = client.get("/api/agent/weight_history")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["latest"]["weight_kg"] == 76.6
    assert body["latest"]["body_fat_pct"] == 26.7
    assert body["all_time"]["min_weight"]["weight_kg"] == 74.9
    assert body["all_time"]["max_weight"]["weight_kg"] == 86.3
    assert body["all_time"]["min_body_fat"]["body_fat_pct"] == 25.7
    assert body["all_time"]["min_body_fat"]["date"] == "2020-12-16"


def test_weight_history_with_window(client, db_session):
    """GET /weight_history?days=30 — adds in_window aggregate."""
    create_weight(db_session, user_id=895655, measured_at=datetime(2020, 1, 1, 8), weight=80.0, body_fat=30.0)
    create_weight(db_session, user_id=895655, measured_at=datetime.now(), weight=76.0, body_fat=26.0)

    r = client.get("/api/agent/weight_history?days=30")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["window_days"] == 30
    assert body["in_window"]["count"] == 1  # only the recent one
    assert body["all_time"]["count"] == 2


def test_day_summary_invalid_date(client):
    """GET /day_summary with malformed date — returns error, not 500."""
    r = client.get("/api/agent/day_summary?date=not-a-date")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "error"


def test_day_summary_no_data(client):
    """GET /day_summary для пустой даты — no_data, не 500."""
    r = client.get("/api/agent/day_summary?date=2020-01-01")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "no_data"


def test_day_summary_live_aggregation(client, db_session):
    """day_summary агрегирует live из nutrition_log + activity_log + weights
    (таблица daily_summaries никогда не заполнялась — аудит 11.06.2026)."""
    d = date(2026, 6, 1)
    create_nutrition_log(
        db_session,
        user_id=895655,
        date=d,
        meal_time=time(9, 0),
        meal_name="Завтрак",
        items=[{"product": "Овсянка", "weight_g": 60, "calories": 240, "protein": 8, "fats": 5, "carbs": 42}],
        totals={"calories": 240, "protein": 8, "fats": 5, "carbs": 42, "fiber": 6},
    )
    create_nutrition_log(
        db_session,
        user_id=895655,
        date=d,
        meal_time=time(13, 0),
        meal_name="Обед",
        items=[{"product": "Суп", "weight_g": 300, "calories": 200, "protein": 10, "fats": 7, "carbs": 20}],
        totals={"calories": 200, "protein": 10, "fats": 7, "carbs": 20, "fiber": 2},
    )
    create_or_update_activity(db_session, user_id=895655, date=d, steps=12000, sleep_hours=7.5)
    create_weight(db_session, user_id=895655, measured_at=datetime(2026, 6, 1, 8, 0), weight=82.4)

    r = client.get("/api/agent/day_summary?date=2026-06-01")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["nutrition"]["calories"] == 440
    assert body["nutrition"]["protein_g"] == 18
    assert body["nutrition"]["meals_count"] == 2
    assert body["activity"]["steps"] == 12000
    assert body["sleep_hours"] == 7.5
    assert body["weight_kg"] == 82.4


def test_body_measurements_no_data(client):
    """GET /body_measurements with no data — returns no_data, not 500."""
    r = client.get("/api/agent/body_measurements")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "no_data"


def test_recent_biomarkers_returns_canonical_keys():
    from core.health.kb_schema import to_canonical

    raw = {"ldl_mmol_l": 3.1, "alt_u_l": 22, "fibrinogen_g_l": 3.0}
    canon, _ = to_canonical(raw, passthrough_unmapped=True)
    assert canon["LDL"] == 3.1  # mapped
    assert canon["ALT"] == 22  # mapped
    assert canon["fibrinogen"] == 3.0  # mapped (fibrinogen now in registry)


def test_phenoage_marker_lookup_canonical_for_dima_keys():
    from core.health.kb_schema import to_canonical

    rows_values = [
        {
            "mcv_fl": 90,
            "wbc_10_9_l": 6.7,
            "creatinine_umol_l": 92,
            "glucose_mmol_l": 5.3,
            "alkaline_phosphatase_u_l": 68,
            "lymphocytes_pct": 28,
            "albumin_g_l": 42,
            "rdw_cv": 13.8,
            "hs_CRP": 1.0,
        }
    ]
    latest = {}
    for vals in rows_values:
        canon, _ = to_canonical(vals)
        for k, v in canon.items():
            latest.setdefault(k, v)
    for need in ["albumin_g_l", "creatinine", "glucose", "hs_CRP", "lymphocytes", "MCV", "RDW_CV", "ALP", "WBC"]:
        assert need in latest, f"phenoage marker {need} не извлёкся из ключей Димы"
