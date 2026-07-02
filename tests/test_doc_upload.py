"""Тесты /doc — самостоятельная загрузка медицинских документов (#227).

Покрытие: append в KB documents[] (создание/дозапись/битый KB/атомарность),
именование файлов без PII, превью, парсинг JSON-ответа экстрактора.
Спека: docs/architecture/2026-06-28-user-kb-self-onboarding-design.md
"""

import importlib.util
import json
import os

# doc_upload импортирует aiogram и handlers.photo — грузим по пути, как в test_extract_date
_path = os.path.join(os.path.dirname(__file__), "..", "telegram-bot", "handlers", "doc_upload.py")
_spec = importlib.util.spec_from_file_location("doc_upload_for_test", _path)
doc_upload = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(doc_upload)

from core.health.doc_extractor import _parse_json_reply  # noqa: E402


# --- append_document_to_kb ---------------------------------------------------


def _entry(**over):
    e = {
        "added_at": "2026-07-02",
        "file": "2026-07-02_a1b2c3d4.pdf",
        "extracted": {"date": "2026-04-13", "laboratory": "KDL", "values": {"Hb": "165 г/л"}},
        "user_confirmed": True,
    }
    e.update(over)
    return e


def test_append_creates_kb_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(doc_upload, "_PROJECT_ROOT", tmp_path)
    doc_upload.append_document_to_kb(111, _entry())
    kb = json.loads((tmp_path / "data" / "kb" / "kb_111.json").read_text(encoding="utf-8"))
    assert len(kb["documents"]) == 1
    assert kb["documents"][0]["user_confirmed"] is True


def test_append_preserves_existing_kb_sections(tmp_path, monkeypatch):
    monkeypatch.setattr(doc_upload, "_PROJECT_ROOT", tmp_path)
    kb_dir = tmp_path / "data" / "kb"
    kb_dir.mkdir(parents=True)
    (kb_dir / "kb_222.json").write_text(
        json.dumps({"blood_tests": [{"date": "2026-01-01"}], "documents": [_entry(file="old.pdf")]}),
        encoding="utf-8",
    )
    doc_upload.append_document_to_kb(222, _entry())
    kb = json.loads((kb_dir / "kb_222.json").read_text(encoding="utf-8"))
    assert kb["blood_tests"] == [{"date": "2026-01-01"}]  # чужие секции не тронуты
    assert [d["file"] for d in kb["documents"]] == ["old.pdf", "2026-07-02_a1b2c3d4.pdf"]


def test_append_survives_corrupt_kb(tmp_path, monkeypatch):
    monkeypatch.setattr(doc_upload, "_PROJECT_ROOT", tmp_path)
    kb_dir = tmp_path / "data" / "kb"
    kb_dir.mkdir(parents=True)
    (kb_dir / "kb_333.json").write_text("{broken json", encoding="utf-8")
    doc_upload.append_document_to_kb(333, _entry())
    kb = json.loads((kb_dir / "kb_333.json").read_text(encoding="utf-8"))
    assert len(kb["documents"]) == 1


def test_no_tmp_leftover_after_append(tmp_path, monkeypatch):
    monkeypatch.setattr(doc_upload, "_PROJECT_ROOT", tmp_path)
    doc_upload.append_document_to_kb(444, _entry())
    assert not list((tmp_path / "data" / "kb").glob("*.tmp"))


# --- именование файлов --------------------------------------------------------


def test_stored_name_no_pii_and_deterministic():
    name1 = doc_upload._stored_name(b"content", ".pdf")
    name2 = doc_upload._stored_name(b"content", ".pdf")
    assert name1 == name2  # хеш от содержимого
    assert name1.endswith(".pdf")
    # формат <YYYY-MM-DD>_<8 hex>.pdf — без имени пользователя/оригинального файла
    stem = name1[:-4]
    date_part, hash_part = stem.rsplit("_", 1)
    assert len(hash_part) == 8
    assert len(date_part.split("-")) == 3


# --- превью -------------------------------------------------------------------


def test_preview_with_values_lists_them():
    text = doc_upload._preview_text(
        {"date": "2026-04-13", "laboratory": "KDL", "doc_type": "анализ крови", "values": {"Hb": "165 г/л"}}
    )
    assert "2026-04-13" in text and "KDL" in text and "Hb: 165 г/л" in text


def test_preview_without_values_offers_archive():
    text = doc_upload._preview_text({"values": {}})
    assert "архив" in text.lower()


# --- парсинг ответа экстрактора ------------------------------------------------


def test_parse_json_reply_extracts_object_from_noise():
    raw = 'Вот результат:\n{"date": "2026-04-13", "values": {"Hb": "165"}}\nГотово.'
    data = _parse_json_reply(raw)
    assert data["date"] == "2026-04-13"
    assert data["values"] == {"Hb": "165"}


def test_parse_json_reply_bad_input_gives_empty():
    assert _parse_json_reply("никакого json") == {}
    assert _parse_json_reply('{"values": "не dict"}')["values"] == {}
