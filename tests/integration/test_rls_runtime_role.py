"""RLS как второй рубеж (ADR-0013): рантайм-роль hv_app не видит чужих строк
даже при забытом ``WHERE user_id``.

Нужен настоящий Postgres со схемой на ревизии head (``alembic upgrade head``)
и URL роли-владельца в ``RLS_TEST_DATABASE_URL``. В CI — шаг job «alembic».
Тест сам выдаёт ролям hv_app / hv_system LOGIN и одноразовый пароль, поэтому
против стенда его НЕ запускать.

    RLS_TEST_DATABASE_URL=postgresql://healthvault:postgres@localhost:5432/healthvault \\
      pytest tests/integration/test_rls_runtime_role.py -v
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

OWNER_URL = os.getenv("RLS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not OWNER_URL, reason="RLS_TEST_DATABASE_URL не задан (нужен Postgres)")

A = 900_000_001
B = 900_000_002
TEST_PASSWORD = "rls_test_only"


def _role_url(role: str) -> str:
    return make_url(OWNER_URL).set(username=role, password=TEST_PASSWORD).render_as_string(hide_password=False)


@pytest.fixture(scope="module")
def owner_engine():
    eng = create_engine(OWNER_URL)
    with eng.begin() as c:
        for role in ("hv_app", "hv_system"):
            c.execute(text(f"ALTER ROLE {role} LOGIN PASSWORD '{TEST_PASSWORD}'"))
        c.execute(text("DELETE FROM nutrition_log WHERE user_id IN (:a, :b)"), {"a": A, "b": B})
        c.execute(text("DELETE FROM blood_tests WHERE user_id IN (:a, :b)"), {"a": A, "b": B})
        c.execute(text("DELETE FROM agent_conversations WHERE user_id IN (:a, :b)"), {"a": A, "b": B})
        c.execute(text("DELETE FROM funnel_events WHERE user_id IN (:a, :b)"), {"a": A, "b": B})
        c.execute(text("DELETE FROM users WHERE telegram_id IN (:a, :b)"), {"a": A, "b": B})
        for uid in (A, B):
            c.execute(
                text("INSERT INTO users (telegram_id, first_name, is_active) VALUES (:u, 'rls', true)"), {"u": uid}
            )
            c.execute(
                text(
                    "INSERT INTO nutrition_log (user_id, date, items, totals) "
                    "VALUES (:u, :d, '[]'::jsonb, '{\"calories\": 1}'::jsonb)"
                ),
                {"u": uid, "d": date(2026, 11, 1)},
            )
            c.execute(
                text("INSERT INTO blood_tests (user_id, test_date, values) VALUES (:u, :d, '{\"ldl\": 3}'::jsonb)"),
                {"u": uid, "d": date(2026, 11, 1)},
            )
            c.execute(
                text("INSERT INTO agent_conversations (user_id, role, content) VALUES (:u, 'user', '{}'::jsonb)"),
                {"u": uid},
            )
    yield eng
    with eng.begin() as c:
        for t, col in (
            ("nutrition_log", "user_id"),
            ("blood_tests", "user_id"),
            ("agent_conversations", "user_id"),
            ("funnel_events", "user_id"),
            ("users", "telegram_id"),
        ):
            c.execute(text(f"DELETE FROM {t} WHERE {col} IN (:a, :b)"), {"a": A, "b": B})
    eng.dispose()


@pytest.fixture(scope="module")
def app_engine(owner_engine):
    eng = create_engine(_role_url("hv_app"))
    yield eng
    eng.dispose()


@pytest.fixture(scope="module")
def system_engine(owner_engine):
    eng = create_engine(_role_url("hv_system"))
    yield eng
    eng.dispose()


@pytest.fixture
def AppSession(app_engine):
    from database import rls

    factory = sessionmaker(bind=app_engine)
    rls.install(factory)
    return factory


def _owners(rows) -> set[int]:
    return {r[0] for r in rows}


def test_runtime_role_is_not_privileged(app_engine):
    with app_engine.connect() as c:
        su, bypass = c.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")).one()
    assert (su, bypass) == (False, False)


def test_runtime_role_cannot_ddl(app_engine):
    with pytest.raises(DBAPIError):
        with app_engine.begin() as c:
            c.execute(text("ALTER TABLE nutrition_log DISABLE ROW LEVEL SECURITY"))


@pytest.mark.parametrize(
    "table,col",
    [
        ("nutrition_log", "user_id"),
        ("blood_tests", "user_id"),
        ("agent_conversations", "user_id"),
        ("users", "telegram_id"),
    ],
)
def test_forgotten_filter_sees_only_own_rows(AppSession, table, col):
    """Главный сценарий: запрос БЕЗ WHERE user_id в контексте A видит только A."""
    from database.rls import user_context

    with user_context(A), AppSession() as db:
        rows = db.execute(text(f"SELECT {col} FROM {table} WHERE {col} IN (:a, :b)"), {"a": A, "b": B}).all()
    assert _owners(rows) == {A}


def test_no_context_sees_nothing(AppSession):
    """Fail-closed: в т.ч. agent_conversations (раньше пустой контекст = всё)."""
    with AppSession() as db:
        for table in ("nutrition_log", "blood_tests", "agent_conversations", "users"):
            assert db.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0, table


def test_context_survives_commit(AppSession):
    """Контекст ставится в начале КАЖДОЙ транзакции, а не одним SET LOCAL."""
    from database.rls import bind_user

    db = AppSession()
    try:
        bind_user(db, B)
        assert _owners(db.execute(text("SELECT user_id FROM blood_tests")).all()) == {B}
        db.commit()
        assert _owners(db.execute(text("SELECT user_id FROM blood_tests")).all()) == {B}
    finally:
        db.close()


def test_orm_query_without_filter(AppSession):
    from database.models import NutritionLog
    from database.rls import user_context

    with user_context(A), AppSession() as db:
        owners = {r.user_id for r in db.query(NutritionLog).all()}
    assert owners == {A}


def test_cannot_write_foreign_rows(AppSession):
    from database.rls import user_context

    with user_context(A), AppSession() as db:
        with pytest.raises(DBAPIError):
            db.execute(
                text("INSERT INTO blood_tests (user_id, test_date, values) VALUES (:u, :d, '{}'::jsonb)"),
                {"u": B, "d": date(2026, 11, 2)},
            )
            db.flush()
        db.rollback()
        updated = db.execute(text("UPDATE blood_tests SET values = '{}'::jsonb WHERE user_id = :b"), {"b": B}).rowcount
        assert updated == 0
        db.rollback()


def test_context_does_not_stick_to_pooled_connection(app_engine):
    """set_config(..., true) — только на транзакцию: соединение из пула чистое."""
    from database import rls

    factory = sessionmaker(bind=app_engine)
    rls.install(factory)
    with rls.user_context(A), factory() as db:
        db.execute(text("SELECT 1")).all()
        db.commit()
    with app_engine.connect() as c:
        assert (c.execute(text("SELECT current_setting('app.user_id', true)")).scalar() or "") == ""


def test_funnel_events_write_only(AppSession):
    from database.rls import user_context

    with user_context(A), AppSession() as db:
        db.execute(
            text("INSERT INTO funnel_events (user_id, event, meta, ts) VALUES (:u, 'rls_test', '{}'::jsonb, :t)"),
            {"u": A, "t": datetime.now(timezone.utc)},
        )
        db.commit()
        assert db.execute(text("SELECT count(*) FROM funnel_events")).scalar() == 0


def test_system_role_sees_everyone(system_engine):
    with system_engine.connect() as c:
        su = c.execute(text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")).scalar()
        rows = c.execute(text("SELECT user_id FROM blood_tests WHERE user_id IN (:a, :b)"), {"a": A, "b": B}).all()
    assert su is False
    assert _owners(rows) == {A, B}
