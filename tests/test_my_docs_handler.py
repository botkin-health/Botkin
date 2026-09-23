# tests/test_my_docs_handler.py
"""Тесты telegram-bot/handlers/my_docs.py — команда /my_docs (issue #370, фаза 4)."""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOT_ROOT = PROJECT_ROOT / "telegram-bot"
for p in [str(PROJECT_ROOT), str(BOT_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture
def kb_env(tmp_path, monkeypatch):
    import core.health.profile_documents as pd

    kb_dir = tmp_path / "kb"
    uploads_dir = tmp_path / "uploads"
    kb_dir.mkdir()
    uploads_dir.mkdir()
    monkeypatch.setattr(pd, "_KB_DIR", kb_dir)
    monkeypatch.setattr(pd, "_UPLOADS_DIR", uploads_dir)
    return tmp_path


def _write_kb(kb_env, user_id, documents):
    kb_path = kb_env / "kb" / f"kb_{user_id}.json"
    kb_path.write_text(json.dumps({"documents": documents}), encoding="utf-8")


def _make_message():
    msg = AsyncMock()
    msg.answer = AsyncMock()
    return msg


def _make_callback(idx, user_id):
    from handlers.my_docs import DocSendCallback

    callback = AsyncMock()
    callback.from_user = MagicMock()
    callback.from_user.id = user_id
    callback.answer = AsyncMock()
    callback.message = AsyncMock()
    callback.message.answer_photo = AsyncMock()
    callback.message.answer_document = AsyncMock()
    callback.message.answer = AsyncMock()
    return callback, DocSendCallback(idx=idx)


@pytest.mark.asyncio
async def test_my_docs_empty_says_no_documents(kb_env):
    from handlers.my_docs import cmd_my_docs

    msg = _make_message()
    await cmd_my_docs(msg, user_id=1)

    msg.answer.assert_awaited_once()
    text = msg.answer.call_args[0][0]
    assert "нет" in text.lower()
    assert "/my_docs" not in text  # не зацикливаем подсказку на саму команду


@pytest.mark.asyncio
async def test_my_docs_lists_newest_first_with_buttons(kb_env):
    from handlers.my_docs import cmd_my_docs

    _write_kb(
        kb_env,
        2,
        [
            {"added_at": "2026-01-01", "file": "old.pdf", "extracted": {}, "title": "Старый", "category": "other"},
            {
                "added_at": "2026-02-01",
                "file": "new.jpg",
                "extracted": {},
                "title": "Полис ОМС",
                "category": "insurance",
            },
        ],
    )

    msg = _make_message()
    await cmd_my_docs(msg, user_id=2)

    msg.answer.assert_awaited_once()
    text = msg.answer.call_args[0][0]
    kwargs = msg.answer.call_args[1]
    assert "Полис ОМС" in text
    assert text.index("Полис ОМС") < text.index("Старый")  # новые сверху
    markup = kwargs["reply_markup"]
    assert len(markup.inline_keyboard) == 2


@pytest.mark.asyncio
async def test_my_docs_says_how_many_more_when_over_limit(kb_env, monkeypatch):
    import handlers.my_docs as mod

    monkeypatch.setattr(mod, "MAX_LISTED", 2)
    _write_kb(
        kb_env,
        3,
        [{"added_at": f"2026-01-0{i}", "file": f"f{i}.pdf", "extracted": {}, "title": f"Док {i}"} for i in range(1, 4)],
    )

    msg = _make_message()
    await mod.cmd_my_docs(msg, user_id=3)

    text = msg.answer.call_args[0][0]
    assert "и ещё 1" in text


@pytest.mark.asyncio
async def test_handle_doc_send_sends_photo_for_image(kb_env):
    from handlers.my_docs import handle_doc_send

    _write_kb(kb_env, 5, [{"added_at": "2026-01-01", "file": "policy.jpg", "extracted": {}, "title": "Полис"}])
    (kb_env / "uploads" / "5").mkdir(parents=True, exist_ok=True)
    (kb_env / "uploads" / "5" / "policy.jpg").write_bytes(b"jpeg-bytes")

    callback, callback_data = _make_callback(idx=0, user_id=5)
    await handle_doc_send(callback, callback_data)

    callback.message.answer_photo.assert_awaited_once()
    assert callback.message.answer_photo.call_args.kwargs["caption"] == "Полис"
    callback.message.answer_document.assert_not_called()


@pytest.mark.asyncio
async def test_handle_doc_send_sends_document_for_pdf(kb_env):
    from handlers.my_docs import handle_doc_send

    _write_kb(kb_env, 6, [{"added_at": "2026-01-01", "file": "report.pdf", "extracted": {}, "title": "Заключение"}])
    (kb_env / "uploads" / "6").mkdir(parents=True, exist_ok=True)
    (kb_env / "uploads" / "6" / "report.pdf").write_bytes(b"%PDF-fake")

    callback, callback_data = _make_callback(idx=0, user_id=6)
    await handle_doc_send(callback, callback_data)

    callback.message.answer_document.assert_awaited_once()
    assert callback.message.answer_document.call_args.kwargs["caption"] == "Заключение"
    callback.message.answer_photo.assert_not_called()


@pytest.mark.asyncio
async def test_handle_doc_send_rejects_out_of_range_idx(kb_env):
    """idx за пределами текущего списка этого пользователя — отказ, а не IndexError."""
    from handlers.my_docs import handle_doc_send

    _write_kb(kb_env, 7, [{"added_at": "2026-01-01", "file": "a.pdf", "extracted": {}, "title": "А"}])

    callback, callback_data = _make_callback(idx=5, user_id=7)
    await handle_doc_send(callback, callback_data)

    callback.answer.assert_awaited_once()
    assert callback.answer.call_args.kwargs.get("show_alert") is True
    callback.message.answer_photo.assert_not_called()
    callback.message.answer_document.assert_not_called()


@pytest.mark.asyncio
async def test_handle_doc_send_scopes_by_clicking_user_not_by_idx_alone(kb_env):
    """Один и тот же idx=0 у разных пользователей резолвится в ИХ СОБСТВЕННЫЙ
    документ (list_documents всегда перезапрашивается по callback.from_user.id) —
    idx сам по себе не может утечь чужой файл (issue #370, фаза 4)."""
    from handlers.my_docs import handle_doc_send

    _write_kb(kb_env, 10, [{"added_at": "2026-01-01", "file": "mine.jpg", "extracted": {}, "title": "Моё"}])
    (kb_env / "uploads" / "10").mkdir(parents=True, exist_ok=True)
    (kb_env / "uploads" / "10" / "mine.jpg").write_bytes(b"mine")

    _write_kb(kb_env, 11, [{"added_at": "2026-01-01", "file": "theirs.jpg", "extracted": {}, "title": "Чужое"}])
    (kb_env / "uploads" / "11").mkdir(parents=True, exist_ok=True)
    (kb_env / "uploads" / "11" / "theirs.jpg").write_bytes(b"theirs")

    callback, callback_data = _make_callback(idx=0, user_id=10)
    await handle_doc_send(callback, callback_data)

    assert callback.message.answer_photo.call_args.kwargs["caption"] == "Моё"
