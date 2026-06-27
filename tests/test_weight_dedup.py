"""#170 (часть 1): дедуп веса за календарный день для ручных источников.

Повторный ручной ввод веса в тот же день не должен плодить ряды в `weights`
(measured_at=now с микросекундами не коллизит UniqueConstraint). Device-синки
(apple_health/garmin/zepp) с реальными intraday-таймстампами НЕ дедупятся.
"""

import sys
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.models import Base, User, Weight
from database.crud import upsert_manual_weight


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
def db(engine):
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    s = Session()
    s.add(User(telegram_id=895655, first_name="Sasha", cohort="owner", jwt_secret="x", is_active=True))
    s.commit()
    try:
        yield s
    finally:
        s.close()


def _count(db, user_id=895655):
    return db.query(Weight).filter(Weight.user_id == user_id).count()


def test_same_day_manual_updates_single_row(db):
    """Два ручных ввода в один календарный день → 1 ряд, последнее значение."""
    upsert_manual_weight(db, user_id=895655, measured_at=datetime(2026, 6, 23, 11, 8), weight=54.0, source="manual")
    upsert_manual_weight(db, user_id=895655, measured_at=datetime(2026, 6, 23, 11, 10), weight=54.5, source="manual")

    assert _count(db) == 1
    row = db.query(Weight).filter(Weight.user_id == 895655).one()
    assert row.weight == 54.5


def test_llm_text_source_also_dedups_against_manual(db):
    """llm_text и manual — оба «ручные», дедупятся между собой за день."""
    upsert_manual_weight(db, user_id=895655, measured_at=datetime(2026, 6, 23, 9, 0), weight=80.0, source="manual")
    upsert_manual_weight(db, user_id=895655, measured_at=datetime(2026, 6, 23, 20, 0), weight=80.4, source="llm_text")

    assert _count(db) == 1
    assert db.query(Weight).filter(Weight.user_id == 895655).one().weight == 80.4


def test_different_days_two_rows(db):
    upsert_manual_weight(db, user_id=895655, measured_at=datetime(2026, 6, 22, 11, 0), weight=54.0, source="manual")
    upsert_manual_weight(db, user_id=895655, measured_at=datetime(2026, 6, 23, 11, 0), weight=54.5, source="manual")

    assert _count(db) == 2


def test_device_source_not_deduped(db):
    """Device-источник (apple_health) пишет реальные замеры — не дедупим, даже в один день."""
    upsert_manual_weight(
        db, user_id=895655, measured_at=datetime(2026, 6, 23, 7, 0), weight=82.0, source="apple_health"
    )
    upsert_manual_weight(
        db, user_id=895655, measured_at=datetime(2026, 6, 23, 7, 5), weight=82.1, source="apple_health"
    )

    assert _count(db) == 2


def test_manual_does_not_overwrite_device_row(db):
    """Ручной ввод в день, где уже есть device-замер, добавляет ряд, device не трогает."""
    upsert_manual_weight(
        db, user_id=895655, measured_at=datetime(2026, 6, 23, 7, 0), weight=82.0, source="apple_health"
    )
    upsert_manual_weight(db, user_id=895655, measured_at=datetime(2026, 6, 23, 12, 0), weight=81.5, source="manual")

    assert _count(db) == 2
    device = db.query(Weight).filter(Weight.source == "apple_health").one()
    assert device.weight == 82.0
