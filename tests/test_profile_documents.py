# tests/test_profile_documents.py
"""Тесты core/health/profile_documents.py (issue #370, фаза 1)."""

import json

import pytest


@pytest.fixture
def kb_dir(tmp_path, monkeypatch):
    """Подменяет _KB_DIR/_UPLOADS_DIR на временную директорию."""
    import core.health.profile_documents as pd

    kb_dir = tmp_path / "kb"
    uploads_dir = tmp_path / "uploads"
    kb_dir.mkdir()
    uploads_dir.mkdir()
    monkeypatch.setattr(pd, "_KB_DIR", kb_dir)
    monkeypatch.setattr(pd, "_UPLOADS_DIR", uploads_dir)
    return tmp_path


def _write_kb(kb_dir_path, user_id, documents):
    kb_path = kb_dir_path / "kb" / f"kb_{user_id}.json"
    kb_path.write_text(json.dumps({"documents": documents}), encoding="utf-8")


def test_list_documents_empty_when_no_kb(kb_dir):
    from core.health.profile_documents import list_documents

    assert list_documents(999) == []


def test_list_documents_newest_first(kb_dir):
    from core.health.profile_documents import list_documents

    _write_kb(
        kb_dir,
        1,
        [
            {"added_at": "2026-01-01", "file": "old.pdf", "extracted": {}},
            {"added_at": "2026-02-01", "file": "new.pdf", "extracted": {}, "title": "Полис ОМС"},
        ],
    )

    docs = list_documents(1)
    assert [d["id"] for d in docs] == ["new.pdf", "old.pdf"]
    assert docs[0]["title"] == "Полис ОМС"


def test_list_documents_fallback_title_from_extracted(kb_dir):
    from core.health.profile_documents import list_documents

    _write_kb(
        kb_dir,
        1,
        [
            {
                "added_at": "2026-01-01",
                "file": "a.pdf",
                "extracted": {"doc_type": "УЗИ ОБП", "laboratory": "МЕДСИ", "date": "2026-01-01"},
            }
        ],
    )
    docs = list_documents(1)
    assert docs[0]["title"] == "УЗИ ОБП — МЕДСИ (2026-01-01)"


def test_list_documents_fallback_title_generic(kb_dir):
    from core.health.profile_documents import list_documents

    _write_kb(kb_dir, 1, [{"added_at": "2026-01-01", "file": "a.pdf", "extracted": {}}])
    docs = list_documents(1)
    assert docs[0]["title"] == "Документ от 2026-01-01"


def test_list_documents_is_lab_flag(kb_dir):
    from core.health.profile_documents import list_documents

    _write_kb(
        kb_dir,
        1,
        [
            {"added_at": "2026-01-01", "file": "lab.pdf", "extracted": {"values": {"Hb": 150}}},
            {"added_at": "2026-01-01", "file": "nolab.pdf", "extracted": {}},
        ],
    )
    docs = {d["id"]: d for d in list_documents(1)}
    assert docs["lab.pdf"]["is_lab"] is True
    assert docs["nolab.pdf"]["is_lab"] is False


def test_update_document_sets_title_and_category(kb_dir):
    from core.health.profile_documents import list_documents, update_document

    _write_kb(kb_dir, 1, [{"added_at": "2026-01-01", "file": "a.pdf", "extracted": {}}])

    result = update_document(1, "a.pdf", title="Полис ОМС", category="insurance")
    assert result["title"] == "Полис ОМС"
    assert result["category"] == "insurance"

    docs = list_documents(1)
    assert docs[0]["title"] == "Полис ОМС"
    assert docs[0]["category"] == "insurance"


def test_update_document_partial_update_keeps_other_field(kb_dir):
    from core.health.profile_documents import update_document

    _write_kb(kb_dir, 1, [{"added_at": "2026-01-01", "file": "a.pdf", "extracted": {}, "title": "Старое"}])

    result = update_document(1, "a.pdf", category="medical")
    assert result["title"] == "Старое"
    assert result["category"] == "medical"


def test_update_document_unknown_category_raises(kb_dir):
    from core.health.profile_documents import update_document

    _write_kb(kb_dir, 1, [{"added_at": "2026-01-01", "file": "a.pdf", "extracted": {}}])
    with pytest.raises(ValueError):
        update_document(1, "a.pdf", category="not_a_real_category")


def test_update_document_unknown_id_raises(kb_dir):
    from core.health.profile_documents import DocumentNotFoundError, update_document

    _write_kb(kb_dir, 1, [{"added_at": "2026-01-01", "file": "a.pdf", "extracted": {}}])
    with pytest.raises(DocumentNotFoundError):
        update_document(1, "does-not-exist.pdf", title="x")


def test_update_document_does_not_touch_other_users(kb_dir):
    from core.health.profile_documents import DocumentNotFoundError, update_document

    _write_kb(kb_dir, 1, [{"added_at": "2026-01-01", "file": "a.pdf", "extracted": {}}])
    # user 2 has no kb file at all
    with pytest.raises(DocumentNotFoundError):
        update_document(2, "a.pdf", title="hacked")


def test_resolve_document_path_traversal_blocked(kb_dir):
    from core.health.profile_documents import DocumentNotFoundError, resolve_document_path

    _write_kb(kb_dir, 1, [{"added_at": "2026-01-01", "file": "a.pdf", "extracted": {}}])
    (kb_dir / "uploads" / "1").mkdir(parents=True, exist_ok=True)
    (kb_dir / "uploads" / "1" / "a.pdf").write_bytes(b"content")

    # Attempted traversal — resolved to basename, which isn't in this user's KB.
    with pytest.raises(DocumentNotFoundError):
        resolve_document_path(1, "../../etc/passwd")


def test_resolve_document_path_ok(kb_dir):
    from core.health.profile_documents import resolve_document_path

    _write_kb(kb_dir, 1, [{"added_at": "2026-01-01", "file": "a.pdf", "extracted": {}}])
    (kb_dir / "uploads" / "1").mkdir(parents=True, exist_ok=True)
    (kb_dir / "uploads" / "1" / "a.pdf").write_bytes(b"content")

    path = resolve_document_path(1, "a.pdf")
    assert path.read_bytes() == b"content"


def test_resolve_document_path_missing_on_disk(kb_dir):
    from core.health.profile_documents import DocumentNotFoundError, resolve_document_path

    _write_kb(kb_dir, 1, [{"added_at": "2026-01-01", "file": "a.pdf", "extracted": {}}])
    # no file on disk
    with pytest.raises(DocumentNotFoundError):
        resolve_document_path(1, "a.pdf")
