"""Контекст пользователя для RLS Postgres (ADR-0013).

Рантайм-роль ``hv_app`` видит только строки, у которых владелец равен
``app.user_id`` текущей транзакции. Здесь — единственное место, где эта
переменная выставляется:

* :func:`user_context` — контекст-менеджер на границе запроса (aiogram-update,
  HTTP-запрос). Кладёт ``telegram_id`` в contextvar.
* :func:`bind_user` — привязать уже открытую сессию к пользователю (когда
  пользователь стал известен посреди запроса: после bootstrap-аутентификации).
* слушатель ``after_begin`` — в начале КАЖДОЙ транзакции ORM-сессии выполняет
  ``set_config('app.user_id', …, true)``. Значение берётся из
  ``session.info['app_user_id']``, иначе из contextvar. Поэтому контекст
  переживает ``commit()`` — новая транзакция получает его заново.

``set_config(…, true)`` = ``SET LOCAL``: живёт до конца транзакции и не
прилипает к соединению в пуле. Не заменять на ``SET`` без ``LOCAL``.

Нет контекста → переменная пустая → RLS не отдаёт ни одной строки (fail-closed).
"""

from __future__ import annotations

import contextvars
import logging
import os
from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import event, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_current_user_id: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar("botkin_rls_user_id", default=None)

_SET_SQL = text("SELECT set_config('app.user_id', :uid, true)")

# Ключ в Session.info: явная привязка сессии к пользователю (bind_user) и
# пометка system-сессии (system_session), которой контекст не нужен.
INFO_USER_KEY = "app_user_id"
INFO_SYSTEM_KEY = "app_system"


def current_user_id() -> Optional[int]:
    """telegram_id из contextvar текущего запроса (или None)."""
    return _current_user_id.get()


def set_current_user(user_id: Optional[int]) -> contextvars.Token:
    """Выставить contextvar без контекст-менеджера (для middleware). Вернуть token для reset."""
    return _current_user_id.set(int(user_id) if user_id is not None else None)


def reset_current_user(token: contextvars.Token) -> None:
    _current_user_id.reset(token)


@contextmanager
def user_context(user_id: Optional[int]) -> Iterator[None]:
    """Все сессии, открытые внутри блока, работают от имени ``user_id``."""
    token = set_current_user(user_id)
    try:
        yield
    finally:
        reset_current_user(token)


def _is_postgres(conn) -> bool:
    try:
        return conn.dialect.name == "postgresql"
    except Exception:
        return False


def _apply(conn, user_id: Optional[int]) -> None:
    conn.execute(_SET_SQL, {"uid": "" if user_id is None else str(int(user_id))})


def bind_user(db: Session, user_id: int) -> None:
    """Привязать сессию ``db`` к пользователю ``user_id``.

    Действует на текущую транзакцию (если открыта) и на все следующие в этой
    сессии. Заодно выставляет contextvar — чтобы сессии, которые код откроет
    глубже по стеку в этом же запросе, тоже получили контекст.
    """
    uid = int(user_id)
    db.info[INFO_USER_KEY] = uid
    set_current_user(uid)
    if db.in_transaction():
        conn = db.connection()
        if _is_postgres(conn):
            _apply(conn, uid)


def _resolve_uid(session: Session) -> Optional[int]:
    uid = session.info.get(INFO_USER_KEY)
    if uid is not None:
        return uid
    return _current_user_id.get()


def _after_begin(session: Session, transaction, connection) -> None:
    if session.info.get(INFO_SYSTEM_KEY):
        return
    if not _is_postgres(connection):
        return
    uid = _resolve_uid(session)
    if uid is None:
        # Fail-closed: под hv_app такая транзакция не увидит пользовательских
        # строк. Под healthvault (до переключения ролей) — увидит всё, как раньше.
        # Лог — чтобы на деве найти места, где контекст забыли поставить.
        if os.getenv("RLS_WARN_NO_CONTEXT"):
            logger.warning("RLS: транзакция без контекста пользователя", stack_info=True, stacklevel=3)
    _apply(connection, uid)


def install(session_factory) -> None:
    """Повесить слушатель на фабрику сессий (идемпотентно)."""
    if not event.contains(session_factory, "after_begin", _after_begin):
        event.listen(session_factory, "after_begin", _after_begin)
