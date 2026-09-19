"""Пути к производным per-user файлам дашборда и агента (#480).

Эти файлы собирает ночной синк из сырых данных: тренировки с зонами и пульсом,
сводка по воздуху, снимок биомаркеров. Исторически они лежали в
``telegram-bot/<kind>_<id>.json`` — то есть **внутри образа**, и каждый деплой
пересоздавал контейнер вместе с ними. Между выкатом и ближайшим прогоном cron
(каждые 30 минут, но только в окне 04–20 UTC) агент и дашборд молча
деградировали к обеднённым источникам: без пульса, зон и training load. Именно
так #474 прожил месяц, а #477 родился из его последствий.

Теперь канон — bind-mount ``data/derived/<telegram_id>/<kind>.json``
(в контейнере ``/app/data`` смонтирован с хоста, как уже сделано для KB).
Чтение умеет фолбэк на старое место, чтобы выкат не создавал провала.
"""

from __future__ import annotations

import os
from pathlib import Path

# kind → как файл назывался в старой раскладке
DERIVED_KINDS = ("workouts_log", "env_data", "biomarkers")

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _base_dir() -> Path:
    """Корень производных файлов. Переопределяется BOTKIN_DERIVED_DIR (тесты, dev)."""
    env = os.getenv("BOTKIN_DERIVED_DIR")
    return Path(env) if env else _REPO_ROOT / "data" / "derived"


def _check_kind(kind: str) -> None:
    if kind not in DERIVED_KINDS:
        raise ValueError(f"неизвестный вид производного файла: {kind!r} (есть {', '.join(DERIVED_KINDS)})")


def derived_path(kind: str, user_id: int) -> Path:
    """Канонический путь: data/derived/<user_id>/<kind>.json."""
    _check_kind(kind)
    return _base_dir() / str(user_id) / f"{kind}.json"


def legacy_derived_path(kind: str, user_id: int) -> Path:
    """Старое место внутри образа — только для чтения и миграции."""
    _check_kind(kind)
    return _REPO_ROOT / "telegram-bot" / f"{kind}_{user_id}.json"


def derived_read_path(kind: str, user_id: int) -> Path:
    """Откуда читать: канон, если он есть; иначе старое место (если есть).

    Возвращает канонический путь и когда ни одного файла нет — вызывающий сам
    решает, что делать с отсутствием (обычно «источник недоступен»).
    """
    canonical = derived_path(kind, user_id)
    if canonical.exists():
        return canonical
    legacy = legacy_derived_path(kind, user_id)
    return legacy if legacy.exists() else canonical


def derived_write_path(kind: str, user_id: int) -> Path:
    """Куда писать: канон, с созданной директорией."""
    p = derived_path(kind, user_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def derived_glob(kind: str) -> str:
    """Glob по всем пользователям — для проверок свежести в /sync."""
    _check_kind(kind)
    return str(_base_dir() / "*" / f"{kind}.json")
