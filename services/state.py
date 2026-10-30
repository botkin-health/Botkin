#!/usr/bin/env python3
"""
Модуль для управления состоянием пользователей бота.

Состояние (превью еды перед «Сохранить», ожидание подписи к фото и т.п.)
держится в памяти и дублируется JSON-файлом на пользователя в `data/state/`
(на проде это bind-mount `/opt/botkin/data` → `/app/data`). Рестарт контейнера
от деплоя больше не теряет открытые превью — см. ADR-0012.
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from datetime import time as dtime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# Превью старше суток не восстанавливаем: юзер давно ушёл, а файлы не копятся.
DEFAULT_TTL_SECONDS = 24 * 3600

_DEFAULT_STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "state"
_SAFE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass
class UserState:
    """Состояние пользователя"""

    user_id: str
    state: str  # 'waiting_description', 'waiting_confirmation', и т.д.
    data: Dict = field(default_factory=dict)


class _Unserializable(TypeError):
    pass


def _encode(value: Any) -> Any:
    """Привести data к JSON, помечая типы, которые хендлеры ждут обратно (Path, date…)."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_encode(v) for v in value]
    if isinstance(value, Path):
        return {"__t": "path", "v": str(value)}
    if isinstance(value, datetime):
        return {"__t": "datetime", "v": value.isoformat()}
    if isinstance(value, date):
        return {"__t": "date", "v": value.isoformat()}
    if isinstance(value, dtime):
        return {"__t": "time", "v": value.isoformat()}
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "model_dump"):  # Pydantic-модель, положенная в data как есть
        return _encode(value.model_dump())
    raise _Unserializable(type(value).__name__)


_DECODERS = {
    "path": Path,
    "datetime": datetime.fromisoformat,
    "date": date.fromisoformat,
    "time": dtime.fromisoformat,
}


def _decode(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode(v) for v in value]
    if isinstance(value, dict):
        tag = value.get("__t")
        if tag in _DECODERS and set(value) == {"__t", "v"}:
            return _DECODERS[tag](value["v"])
        return {k: _decode(v) for k, v in value.items()}
    return value


class StateManager:
    """Менеджер состояний пользователей.

    Память — основной кэш (те же объекты, что и раньше), диск — write-through
    копия, переживающая рестарт. `state_dir=None` — только память (тесты).
    Сбой диска никогда не роняет хендлер: состояние остаётся в памяти.

    ⚠️ На диск попадает только то, что прошло через set_state(). Правка
    `user_state.data[...]` на месте без повторного set_state() после рестарта
    потеряется — все текущие хендлеры вызывают set_state() после правки.
    """

    def __init__(
        self,
        state_dir: Optional[Union[str, Path]] = None,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ):
        self._states: Dict[str, UserState] = {}
        self._touched: Dict[str, float] = {}
        self._ttl = ttl_seconds
        self._dir: Optional[Path] = Path(state_dir) if state_dir else None
        if self._dir is not None:
            try:
                self._dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                logger.warning("state: каталог %s недоступен (%s) — только память", self._dir, e)
                self._dir = None
            else:
                self.purge_expired()

    def get_state(self, user_id: str) -> Optional[UserState]:
        """Получить состояние пользователя"""
        if user_id in self._states:
            if self._expired(self._touched.get(user_id, 0)):
                self.clear_state(user_id)
                return None
            return self._states[user_id]
        loaded = self._load(user_id)
        if loaded is None:
            return None
        user_state, updated_at = loaded
        self._states[user_id] = user_state
        self._touched[user_id] = updated_at
        return user_state

    def set_state(self, user_id: str, user_state: UserState):
        """Установить состояние пользователя"""
        now = time.time()
        self._states[user_id] = user_state
        self._touched[user_id] = now
        self._save(user_id, user_state, now)

    def clear_state(self, user_id: str):
        """Очистить состояние пользователя"""
        self._states.pop(user_id, None)
        self._touched.pop(user_id, None)
        self._unlink(self._path(user_id))

    def purge_expired(self) -> int:
        """Удалить с диска состояния старше TTL. Возвращает число удалённых файлов."""
        if self._dir is None:
            return 0
        removed = 0
        for path in self._dir.glob("*.json"):
            try:
                with open(path, encoding="utf-8") as f:
                    updated_at = float(json.load(f).get("updated_at", 0))
            except (OSError, ValueError, TypeError, AttributeError):
                updated_at = 0  # битый файл — тоже мусор
            if self._expired(updated_at):
                self._unlink(path)
                removed += 1
        return removed

    def _expired(self, updated_at: float) -> bool:
        return time.time() - updated_at > self._ttl

    def _path(self, user_id: Any) -> Optional[Path]:
        if self._dir is None:
            return None
        key = str(user_id)
        if not _SAFE_KEY.match(key):
            return None
        return self._dir / f"{key}.json"

    @staticmethod
    def _unlink(path: Optional[Path]):
        if path is None:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError as e:
            logger.warning("state: не удалось удалить %s: %s", path, e)

    def _save(self, user_id: str, user_state: UserState, updated_at: float):
        path = self._path(user_id)
        if path is None:
            return
        try:
            payload = {
                "user_id": _encode(user_state.user_id),
                "state": user_state.state,
                "data": _encode(user_state.data),
                "updated_at": updated_at,
            }
        except _Unserializable as e:
            # В памяти состояние живёт как раньше. Старый файл убираем, чтобы
            # после рестарта не восстановить устаревшую копию.
            logger.warning("state: %s не сериализуется (%s) — без персистентности", user_state.state, e)
            self._unlink(path)
            return
        tmp = path.with_suffix(".json.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError as e:
            logger.warning("state: не удалось записать %s: %s", path, e)

    def _load(self, user_id: str) -> Optional[Tuple[UserState, float]]:
        path = self._path(user_id)
        if path is None or not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
            updated_at = float(payload["updated_at"])
            if self._expired(updated_at):
                self._unlink(path)
                return None
            user_state = UserState(
                user_id=_decode(payload["user_id"]),
                state=payload["state"],
                data=_decode(payload.get("data") or {}),
            )
        except (OSError, ValueError, KeyError, TypeError) as e:
            logger.warning("state: битый файл %s (%s) — удаляю", path, e)
            self._unlink(path)
            return None
        return user_state, updated_at


def _state_dir_from_env() -> Optional[Path]:
    # BOT_STATE_DIR="" выключает персистентность (так делает tests/conftest.py).
    raw = os.environ.get("BOT_STATE_DIR")
    if raw is None:
        return _DEFAULT_STATE_DIR
    return Path(raw) if raw else None


# Глобальный экземпляр менеджера состояний
state_manager = StateManager(state_dir=_state_dir_from_env())
