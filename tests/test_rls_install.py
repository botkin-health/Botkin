"""database.rls.install(): слушатель обязан встать на КАЖДУЮ новую фабрику сессий.

Регрессия CI 15–23.11.2026: install() проверял «уже установлен?» через
``event.contains()``. Реестр событий SQLAlchemy ключуется по ``id()`` цели, а
запись о мёртвой фабрике в нём остаётся. Новая фабрика, получившая тот же
адрес в памяти, считалась «уже со слушателем» → слушатель не вешался →
транзакции шли без ``app.user_id`` (под hv_app это ноль строк).

Postgres не нужен: проверяем сам факт срабатывания ``after_begin``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from database import rls


@pytest.fixture
def begin_calls(monkeypatch):
    """Счётчик срабатываний слушателя (его первый шаг — проверка диалекта)."""
    calls: list[int] = []

    def _spy(conn) -> bool:
        calls.append(1)
        return False  # sqlite: до set_config дело не дойдёт

    monkeypatch.setattr(rls, "_is_postgres", _spy)
    return calls


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    yield eng
    eng.dispose()


def _begin_once(factory) -> None:
    with factory() as db:
        db.execute(text("SELECT 1"))


def test_listener_installed_on_every_fresh_factory(engine, begin_calls):
    """Фабрики живут недолго (как function-фикстура) — адреса переиспользуются."""
    for i in range(200):
        factory = sessionmaker(bind=engine)
        rls.install(factory)
        before = len(begin_calls)
        _begin_once(factory)
        assert len(begin_calls) == before + 1, f"фабрика #{i}: слушатель after_begin не сработал"
        del factory


def test_install_is_idempotent(engine, begin_calls):
    factory = sessionmaker(bind=engine)
    rls.install(factory)
    rls.install(factory)
    _begin_once(factory)
    assert len(begin_calls) == 1
