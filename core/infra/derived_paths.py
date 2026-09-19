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


def ensure_derived_dir(kind: str, user_id: int) -> Path:
    """Куда писать: канон, с созданной директорией. Побочный эффект — в имени.

    Каталог создаётся под uid 10001 внутри bind-mount; если права не дали,
    падаем с подсказкой, а не голым трейсбеком — см. docs/DEPLOYMENT.md,
    раздел про права на bind-mount.
    """
    p = derived_path(kind, user_id)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except PermissionError as e:
        raise SystemExit(
            f"❌ Нет прав создать {p.parent}: {e}\n"
            "   Каталог на bind-mount должен принадлежать uid 10001 (botkin). Разово:\n"
            "   docker exec -u 0 healthvault_bot mkdir -p /app/data/derived "
            "&& docker exec -u 0 healthvault_bot chown 10001:10001 /app/data/derived"
        ) from e
    return p


def write_derived_atomically(kind: str, user_id: int, text: str) -> Path:
    """Запись через временный файл в той же директории + os.replace.

    Файл теперь durable: битый результат прерванной записи не «переживается»
    деплоем, как раньше, и вдобавок затеняет фолбэк на старое место
    (derived_read_path выбирает канон по факту существования).
    """
    target = ensure_derived_dir(kind, user_id)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)
    return target


def derived_glob(kind: str) -> str:
    """Glob по всем пользователям — для проверок свежести в /sync."""
    _check_kind(kind)
    return str(_base_dir() / "*" / f"{kind}.json")
