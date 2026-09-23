"""Тесты парсера тренировок Health Connect (#525.3).

Приложение шлёт `exercise` (ExerciseSessionRecord), сервер его молча
отбрасывал — в модели HealthConnectPayload поля не было, pydantic его
игнорировал. `_hc_exercise_to_rows` превращает `exercise[]` в строки таблицы
`workouts`, повторяя паттерн `_hae_workouts_to_rows` (apple_health.py):
дедуп через переиспользуемый `_insert_new_workouts` (ON CONFLICT DO NOTHING
на реальном UNIQUE(user_id, start_time) — чужой источник не перетирается).

Коды exerciseType — androidx.health.connect.client.records.ExerciseSessionRecord
(сверено по исходнику androidx/androidx, EXERCISE_TYPE_*): 56=running,
79=walking, 8=biking, 83=yoga, 48=pilates, 70=strength_training,
74=swimming_pool. Приложение шлёт `exerciseType.toString()` — Int как строка.
"""

import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import Base
from webhook.android_health import HCExerciseRecord, HealthConnectPayload, _hc_exercise_to_rows
from webhook.apple_health import _insert_new_workouts

USER = 895700


# ── HealthConnectPayload принимает exercise (было молча отброшено) ──────────


def test_payload_accepts_exercise_field():
    payload = HealthConnectPayload(
        exercise=[
            {"type": "56", "start_time": "2026-07-01T08:00:00Z", "end_time": "2026-07-01T08:45:00Z"},
        ]
    )
    assert len(payload.exercise) == 1
    assert isinstance(payload.exercise[0], HCExerciseRecord)


def test_payload_exercise_defaults_to_empty_list():
    payload = HealthConnectPayload()
    assert payload.exercise == []


# ── _hc_exercise_to_rows: маппинг типа, длительность, source-дедуп ──────────


def test_running_type_mapped_to_readable_name():
    rows = _hc_exercise_to_rows(
        [{"type": "56", "start_time": "2026-07-01T08:00:00Z", "end_time": "2026-07-01T08:45:00Z"}], USER
    )
    assert len(rows) == 1
    assert rows[0]["workout_type"] == "бег"
    assert rows[0]["duration_minutes"] == 45
    assert rows[0]["user_id"] == USER
    assert rows[0]["date"] == "2026-07-01"
    assert isinstance(rows[0]["start_time"], datetime)
    assert isinstance(rows[0]["end_time"], datetime)


@pytest.mark.parametrize(
    "code,name",
    [
        ("79", "ходьба"),
        ("8", "велосипед"),
        ("9", "велотренажёр"),
        ("83", "йога"),
        ("48", "пилатес"),
        ("70", "силовая тренировка"),
        ("74", "плавание в бассейне"),
        ("57", "бег на дорожке"),
    ],
)
def test_known_exercise_type_codes_mapped(code, name):
    rows = _hc_exercise_to_rows(
        [{"type": code, "start_time": "2026-07-01T08:00:00Z", "end_time": "2026-07-01T08:30:00Z"}], USER
    )
    assert rows[0]["workout_type"] == name


def test_unknown_exercise_type_code_not_dropped():
    """Неизвестный код не выбрасывается — читаемое имя с кодом внутри."""
    rows = _hc_exercise_to_rows(
        [{"type": "9999", "start_time": "2026-07-01T08:00:00Z", "end_time": "2026-07-01T08:30:00Z"}], USER
    )
    assert len(rows) == 1
    assert "9999" in rows[0]["workout_type"]


def test_exercise_without_start_or_end_skipped():
    rows = _hc_exercise_to_rows([{"type": "56", "start_time": "not-a-date", "end_time": "2026-07-01T08:45:00Z"}], USER)
    assert rows == []


def test_exercise_distance_meters_converted_to_km():
    rows = _hc_exercise_to_rows(
        [
            {
                "type": "56",
                "start_time": "2026-07-01T08:00:00Z",
                "end_time": "2026-07-01T08:45:00Z",
                "distance_meters": 7500.0,
            }
        ],
        USER,
    )
    assert rows[0]["distance_km"] == pytest.approx(7.5, rel=0.001)


def test_source_stable_for_repeat_payload():
    """Тот же payload дважды → одинаковый source (нужно для дедупа при повторном синке)."""
    rec = {"type": "56", "start_time": "2026-07-01T08:00:00Z", "end_time": "2026-07-01T08:45:00Z"}
    rows_a = _hc_exercise_to_rows([rec], USER)
    rows_b = _hc_exercise_to_rows([rec], USER)
    assert rows_a[0]["source"] == rows_b[0]["source"]
    assert rows_a[0]["source"].startswith("hc_")


# ── Вставка в реальную (SQLite) БД: дедуп + чужой источник не перетирается ──


@pytest.fixture
def db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=eng)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=eng)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=eng)


def test_exercise_inserted_into_workouts(db):
    rows = _hc_exercise_to_rows(
        [{"type": "56", "start_time": "2026-07-01T08:00:00Z", "end_time": "2026-07-01T08:45:00Z"}], USER
    )
    inserted = _insert_new_workouts(db, USER, rows)
    db.commit()
    assert inserted == 1
    result = db.execute(text("SELECT workout_type, source FROM workouts WHERE user_id = :uid"), {"uid": USER}).all()
    assert len(result) == 1
    assert result[0][0] == "бег"


def test_repeat_payload_no_duplicate(db):
    rec = {"type": "56", "start_time": "2026-07-01T08:00:00Z", "end_time": "2026-07-01T08:45:00Z"}
    rows = _hc_exercise_to_rows([rec], USER)
    _insert_new_workouts(db, USER, rows)
    db.commit()

    # Повтор того же payload (пере-синк) — не должно создать вторую строку.
    rows_again = _hc_exercise_to_rows([rec], USER)
    inserted_again = _insert_new_workouts(db, USER, rows_again)
    db.commit()
    assert inserted_again == 0
    count = db.execute(text("SELECT COUNT(*) FROM workouts WHERE user_id = :uid"), {"uid": USER}).scalar()
    assert count == 1


def test_other_source_same_start_time_not_overwritten(db):
    """UNIQUE(user_id, start_time): Garmin-строка на то же время не перетирается HC (прецедент #500)."""
    # tz-aware, чтобы совпасть по значению с start_time из _hc_exercise_to_rows
    # (тот тоже tz-aware, через _parse_utc) — иначе SQLite сравнивает наивную и
    # осведомлённую строки как РАЗНЫЕ значения и UNIQUE-конфликта не будет,
    # хотя на Postgres (timestamptz) это один и тот же момент времени.
    start_dt = datetime(2026, 7, 1, 8, 0, 0, tzinfo=timezone.utc)
    db.execute(
        text(
            """INSERT INTO workouts (user_id, date, workout_type, start_time, source)
               VALUES (:uid, :d, 'Running', :st, 'garmin_123')"""
        ),
        {"uid": USER, "d": date(2026, 7, 1), "st": start_dt},
    )
    db.commit()

    rows = _hc_exercise_to_rows(
        [{"type": "56", "start_time": "2026-07-01T08:00:00Z", "end_time": "2026-07-01T08:45:00Z"}], USER
    )
    _insert_new_workouts(db, USER, rows)
    db.commit()

    # ON CONFLICT DO NOTHING защищает данные на реальном UNIQUE(user_id, start_time) —
    # именно это гарантия из #500, не значение счётчика `inserted` (он не проверяет
    # rowcount после ON CONFLICT DO NOTHING и это не предмет данного тикета).
    result = db.execute(
        text("SELECT workout_type, source FROM workouts WHERE user_id = :uid AND start_time = :st"),
        {"uid": USER, "st": start_dt},
    ).all()
    assert len(result) == 1, "На это start_time должна остаться ровно одна строка — чужая"
    assert result[0][1] == "garmin_123", "Чужая запись на то же start_time не должна быть перетёрта HC"


# ── Endpoint: exercise-only payload (без daily-метрик) не должен пропасть ───


def test_exercise_only_payload_still_inserts_workout():
    """
    Payload без steps/distance/etc, только exercise — daily-агрегат пуст, но
    тренировка всё равно должна попасть в workouts (#525.3). Ранний return
    по `if not daily` не должен резать exercise-путь.
    """
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "telegram-bot"))

    from fastapi.testclient import TestClient
    from sqlalchemy import text as _text
    from sqlalchemy.orm import sessionmaker as _sessionmaker
    from sqlalchemy.pool import StaticPool as _StaticPool
    from sqlalchemy import create_engine as _create_engine

    from database.models import Base as _Base, User as _User
    import database as _database
    from webhook import android_health as _android_health

    eng = _create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=_StaticPool)
    _Base.metadata.create_all(bind=eng)
    Session = _sessionmaker(autocommit=False, autoflush=False, bind=eng)
    db = Session()
    db.add(_User(telegram_id=USER, health_token="exonly", timezone="Europe/Moscow"))
    db.commit()

    db.close = lambda: None  # держим сессию открытой между "запросами" в тесте

    orig_session_local = _database.SessionLocal
    _database.SessionLocal = lambda: db
    try:
        client = TestClient(_android_health.app)
        r = client.post(
            "/android_health_v1",
            json={
                "exercise": [{"type": "56", "start_time": "2026-07-01T08:00:00Z", "end_time": "2026-07-01T08:45:00Z"}]
            },
            headers={"Authorization": "Bearer exonly"},
        )
        assert r.status_code == 200
        assert r.json().get("workouts_inserted") == 1
        rows = db.execute(_text("SELECT workout_type FROM workouts WHERE user_id = :uid"), {"uid": USER}).all()
        assert len(rows) == 1
        assert rows[0][0] == "бег"
    finally:
        _database.SessionLocal = orig_session_local
