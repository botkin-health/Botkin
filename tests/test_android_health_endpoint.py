"""Тесты записи в БД для эндпоинта Health Connect (`/android_health_v1`).

Покрывает:
- #525.2 — active_calories пишутся в activity_log.active_calories (колонку),
  когда нет Garmin; Garmin не перетирается.
- #525.5 (доп. решение Александра) — законченный прошедший день из Health
  Connect ЗАМЕЩАЕТ сохранённое значение интервальных метрик (steps,
  distance_km, active_calories), а не берёт максимум: история искажена
  багом #525.1 (день N лёг на N+1, значения завышены), и простой ре-синк
  не исправит это через monotonic-max (старое завышенное больше нового
  верного). Сегодняшний (незаконченный) день по-прежнему монотонен.
  Garmin/другие источники по-прежнему не перетираются вовсе.
"""

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.models import Base, User
from database.crud import create_or_update_activity, get_activity_by_date
from webhook.android_health import _resolve_hc_active_calories

TEST_UID = 895700
TOKEN = "hc_test_token"


# ── Unit: чистый резолвер active_calories (#525.2) ──────────────────────────


def _row(active_calories, source):
    return SimpleNamespace(active_calories=active_calories, source=source)


def test_resolve_active_calories_first_write_when_no_row():
    assert _resolve_hc_active_calories(None, 350.0) == 350.0


def test_resolve_active_calories_none_input_returns_none():
    assert _resolve_hc_active_calories(None, None) is None
    assert _resolve_hc_active_calories(_row(200.0, "health_connect"), None) is None


def test_resolve_active_calories_passes_through_for_hc_row():
    row = _row(200.0, "health_connect")
    assert _resolve_hc_active_calories(row, 350.0) == 350.0


def test_resolve_active_calories_preserves_garmin():
    row = _row(600.0, "garmin")
    assert _resolve_hc_active_calories(row, 350.0) is None
    row_slash = _row(600.0, "garmin/connect")
    assert _resolve_hc_active_calories(row_slash, 350.0) is None


def test_resolve_active_calories_writes_when_garmin_row_has_no_active_calories():
    row = _row(None, "garmin")
    assert _resolve_hc_active_calories(row, 350.0) == 350.0


# ── Integration: /android_health_v1 через TestClient ────────────────────────


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
    db.add(User(telegram_id=TEST_UID, health_token=TOKEN, timezone="Europe/Moscow"))
    db.commit()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client(api_db, monkeypatch):
    import database
    from webhook import android_health

    monkeypatch.setattr(api_db, "close", lambda: None)
    monkeypatch.setattr(database, "SessionLocal", lambda: api_db)

    return TestClient(android_health.app)


def _post(client, **fields):
    return client.post("/android_health_v1", json=fields, headers={"Authorization": f"Bearer {TOKEN}"})


def _completed_day_window(d: date):
    """[полночь d МСК, полночь d+1 МСК) в UTC ISO-строках — законченный день."""
    start_utc = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) - timedelta(hours=3)
    end_utc = start_utc + timedelta(days=1)
    return start_utc.isoformat().replace("+00:00", "Z"), end_utc.isoformat().replace("+00:00", "Z")


def test_active_calories_written_to_column_without_garmin(client, api_db):
    """#525.2 — без Garmin активные калории должны дойти до колонки."""
    r = _post(
        client,
        active_calories=[
            {"calories": 350.0, "start_time": "2026-07-01T08:00:00Z", "end_time": "2026-07-01T09:00:00Z"},
        ],
    )
    assert r.status_code == 200
    row = get_activity_by_date(api_db, TEST_UID, date(2026, 7, 1))
    assert row is not None
    assert row.active_calories == 350.0
    # raw_data по-прежнему хранит hc_active_calories (обратная совместимость)
    assert (row.raw_data or {}).get("hc_active_calories") == 350.0


def test_active_calories_not_overwritten_when_garmin_owns_row(client, api_db):
    """#525.2 — Garmin приоритетнее: HC не перетирает существующее значение Garmin."""
    d = date(2026, 7, 1)
    create_or_update_activity(
        db=api_db,
        user_id=TEST_UID,
        date=d,
        steps=1000,
        active_calories=600.0,
        source="garmin",
    )

    r = _post(
        client,
        active_calories=[
            {"calories": 350.0, "start_time": "2026-07-01T08:00:00Z", "end_time": "2026-07-01T09:00:00Z"},
        ],
    )
    assert r.status_code == 200
    row = get_activity_by_date(api_db, TEST_UID, d)
    assert row.active_calories == 600.0
    assert row.source == "garmin"


# ── #525.5: законченный день замещает, сегодняшний остаётся монотонным ─────


def test_completed_past_day_replaces_inflated_stored_value(client, api_db):
    """
    В БД лежит завышенное значение бага #525.1 (22 257 — весь день N + N+1 суммой).
    Приходит законченный день (полный интервал [полночь, полночь+1)) с правильным
    меньшим значением 11 000 — должно ЗАМЕСТИТЬ, а не остаться максимумом.
    """
    past_day = date(2026, 7, 1)  # заведомо раньше "сегодня" в системных часах теста
    create_or_update_activity(
        db=api_db,
        user_id=TEST_UID,
        date=past_day,
        steps=22257,
        source="health_connect",
    )

    start_iso, end_iso = _completed_day_window(past_day)
    r = _post(client, steps=[{"count": 11000, "start_time": start_iso, "end_time": end_iso}])
    assert r.status_code == 200
    row = get_activity_by_date(api_db, TEST_UID, past_day)
    assert row.steps == 11000, f"Законченный день должен заместить завышенное значение, получили {row.steps}"


def test_today_partial_sync_stays_monotonic(client, api_db):
    """Сегодняшний (незаконченный) день — монотонность сохранена: меньшее не затирает большее."""
    today_local = datetime.now(timezone(timedelta(hours=3))).date()  # МСК
    create_or_update_activity(
        db=api_db,
        user_id=TEST_UID,
        date=today_local,
        steps=5000,
        source="health_connect",
    )

    # Частичный дневной интервал [полночь сегодня, сейчас) — НЕ полные сутки.
    start_utc = datetime(today_local.year, today_local.month, today_local.day, tzinfo=timezone.utc) - timedelta(hours=3)
    now_utc = datetime.now(timezone.utc)
    r = _post(
        client,
        steps=[
            {
                "count": 3000,
                "start_time": start_utc.isoformat().replace("+00:00", "Z"),
                "end_time": now_utc.isoformat().replace("+00:00", "Z"),
            }
        ],
    )
    assert r.status_code == 200
    row = get_activity_by_date(api_db, TEST_UID, today_local)
    assert row.steps == 5000, f"Незаконченный день не должен уменьшаться, получили {row.steps}"


def test_completed_day_does_not_force_replace_garmin_steps(client, api_db):
    """
    Garmin по-прежнему приоритетнее: замещение (в т.ч. регрессия вниз) применяется
    только к строкам health_connect. У Garmin-строки бОльшее значение (15000) не
    должно быть заменено МЕНЬШИМ значением из HC (11000) — если бы replace-режим
    ошибочно применился к чужой строке, 15000 → 11000 (потеря данных). Правильное
    поведение — обычный monotonic-max, как и раньше: max(15000, 11000) = 15000.
    """
    past_day = date(2026, 7, 1)
    create_or_update_activity(
        db=api_db,
        user_id=TEST_UID,
        date=past_day,
        steps=15000,
        source="garmin",
    )

    start_iso, end_iso = _completed_day_window(past_day)
    r = _post(client, steps=[{"count": 11000, "start_time": start_iso, "end_time": end_iso}])
    assert r.status_code == 200
    row = get_activity_by_date(api_db, TEST_UID, past_day)
    assert row.steps == 15000, f"Garmin-строка не должна быть заменена меньшим HC-значением, получили {row.steps}"
    assert row.source == "garmin"


def test_partial_past_day_does_not_replace_full_value(client, api_db):
    """Ревью координатора #525: прошедший день может прийти ЧАСТИЧНО —
    (1) самый старый день окна синка приложение обрезает границей окна
    (LOOKBACK_HOURS=48, см. readDailyStepsData и issue #72 приложения);
    (2) в режимах raw/bucketed приложение шлёт только записи после lastSync.
    Частичный интервал не должен замещать полное значение дня: потеря шагов."""
    past_day = date(2026, 7, 1)
    create_or_update_activity(db=api_db, user_id=TEST_UID, date=past_day, steps=11000, source="health_connect")

    # Хвост дня: [15:00, полночь+1) по МСК — НЕ полные сутки
    msk = timezone(timedelta(hours=3))
    tail_start = datetime(past_day.year, past_day.month, past_day.day, 15, 0, tzinfo=msk)
    day_end = datetime(past_day.year, past_day.month, past_day.day, tzinfo=msk) + timedelta(days=1)
    r = _post(
        client,
        steps=[{"count": 2500, "start_time": tail_start.isoformat(), "end_time": day_end.isoformat()}],
    )
    assert r.status_code == 200
    row = get_activity_by_date(api_db, TEST_UID, past_day)
    assert row.steps == 11000, f"Частичный хвост прошедшего дня заместил полный день: {row.steps}"


def test_mixed_full_steps_partial_distance_stays_monotonic(client, api_db):
    """У каждого типа данных в приложении своё разрешение: шаги пришли полными
    сутками, а дистанция — инкрементом. Замещение применяется ко всему вызову,
    поэтому при любой частичной метрике — монотонно, иначе потеряем дистанцию."""
    past_day = date(2026, 7, 2)
    create_or_update_activity(
        db=api_db, user_id=TEST_UID, date=past_day, steps=20000, distance_km=8.0, source="health_connect"
    )
    start_iso, end_iso = _completed_day_window(past_day)
    msk = timezone(timedelta(hours=3))
    tail_start = datetime(past_day.year, past_day.month, past_day.day, 18, 0, tzinfo=msk)
    r = _post(
        client,
        steps=[{"count": 11000, "start_time": start_iso, "end_time": end_iso}],
        distance=[{"meters": 900.0, "start_time": tail_start.isoformat(), "end_time": end_iso}],
    )
    assert r.status_code == 200
    row = get_activity_by_date(api_db, TEST_UID, past_day)
    assert float(row.distance_km) == 8.0, f"Частичная дистанция заместила полную: {row.distance_km}"
