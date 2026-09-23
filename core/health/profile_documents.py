# core/health/profile_documents.py
"""Метаданные документов профиля (issue #370): title/category поверх `documents[]`
в `kb_<user_id>.json`, читаемые и Telegram-хендлерами, и агентными тулами.

Без Telegram-зависимостей — только KB-файл и файлы в `data/uploads/<user_id>/`.
Атомарная запись переиспользует `core.health.kb_writer` (read_kb/write_kb).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from core.health.kb_writer import read_kb, write_kb

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_UPLOADS_DIR = _PROJECT_ROOT / "data" / "uploads"
_KB_DIR = _PROJECT_ROOT / "data" / "kb"

# Категории документов профиля — фиксированный список (issue #370, фаза 1).
CATEGORIES = ("insurance", "certificate", "contact", "medical", "other")


class DocumentNotFoundError(Exception):
    """Документ с таким id не найден среди документов пользователя."""


def _kb_path(user_id: int) -> Path:
    return _KB_DIR / f"kb_{user_id}.json"


def uploads_dir(user_id: int) -> Path:
    """Каталог загруженных файлов пользователя — та же схема, что
    `handlers.doc_upload._uploads_dir`, без создания директории (только чтение)."""
    return _UPLOADS_DIR / str(user_id)


def _fallback_title(entry: dict[str, Any]) -> str:
    """Человекочитаемое название для старых записей без `title` — из типа/
    лаборатории/даты в `extracted`, иначе «Документ от <дата>» (issue #370)."""
    extracted = entry.get("extracted") or {}
    parts = [p for p in (extracted.get("doc_type"), extracted.get("laboratory")) if p]
    doc_date = extracted.get("date") or entry.get("added_at")
    if parts:
        label = " — ".join(parts)
        return f"{label} ({doc_date})" if doc_date else label
    return f"Документ от {entry.get('added_at')}" if entry.get("added_at") else "Документ"


def _is_lab(entry: dict[str, Any]) -> bool:
    """Есть ли у документа извлечённые лабораторные показатели."""
    extracted = entry.get("extracted") or {}
    return bool(extracted.get("values"))


def _documents_list(kb: dict[str, Any]) -> list[dict[str, Any]]:
    documents = kb.get("documents")
    return documents if isinstance(documents, list) else []


def _to_summary(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": entry.get("file"),
        "title": entry.get("title") or _fallback_title(entry),
        "category": entry.get("category"),
        "added_at": entry.get("added_at"),
        "is_lab": _is_lab(entry),
    }


def list_documents(user_id: int) -> list[dict[str, Any]]:
    """Документы профиля пользователя, новые сверху.

    Каждый элемент: {id, title, category, added_at, is_lab}. `id` — имя
    сохранённого файла (`entry["file"]`) — используется для `update_document`
    и для поиска файла на диске (`resolve_document_path`).
    """
    kb = read_kb(_kb_path(user_id))
    entries = [e for e in _documents_list(kb) if isinstance(e, dict) and e.get("file")]
    entries.reverse()  # append_document_to_kb дописывает в конец — новые сверху
    return [_to_summary(e) for e in entries]


def update_document(
    user_id: int,
    file_id: str,
    *,
    title: Optional[str] = None,
    category: Optional[str] = None,
) -> dict[str, Any]:
    """Обновляет `title`/`category` документа пользователя. Атомарно, только
    своя запись (KB читается и пишется по `user_id` — RLS обеспечивает вызывающий).

    `file_id` — id из `list_documents` (basename сохранённого файла).
    Неизвестный id → `DocumentNotFoundError`. Незнакомая `category` →
    `ValueError` (список фиксирован — `CATEGORIES`).
    """
    if category is not None and category not in CATEGORIES:
        raise ValueError(f"unknown category {category!r}, expected one of {CATEGORIES}")

    # #370: id всегда сверяется как basename — не доверяем вводу вызывающего
    # (агент/callback_data), защита от path traversal.
    safe_id = Path(file_id).name

    kb_path = _kb_path(user_id)
    kb = read_kb(kb_path)
    entries = _documents_list(kb)

    for entry in entries:
        if isinstance(entry, dict) and entry.get("file") == safe_id:
            if title is not None:
                entry["title"] = title
            if category is not None:
                entry["category"] = category
            write_kb(kb_path, kb)
            return _to_summary(entry)

    raise DocumentNotFoundError(f"документ {safe_id!r} не найден у пользователя {user_id}")


def resolve_document_path(user_id: int, file_id: str) -> Path:
    """Путь к файлу на диске по id — строго внутри `uploads_dir(user_id)`.

    Проверяет принадлежность id списку документов ЭТОГО пользователя (не
    просто существование файла на диске) — защита от path traversal и от
    подстановки чужого id (issue #370, фаза 1).
    """
    safe_id = Path(file_id).name
    kb = read_kb(_kb_path(user_id))
    known_ids = {e.get("file") for e in _documents_list(kb) if isinstance(e, dict)}
    if safe_id not in known_ids:
        raise DocumentNotFoundError(f"документ {safe_id!r} не найден у пользователя {user_id}")

    path = uploads_dir(user_id) / safe_id
    if not path.is_file():
        raise DocumentNotFoundError(f"файл документа {safe_id!r} отсутствует на диске (user {user_id})")
    return path
