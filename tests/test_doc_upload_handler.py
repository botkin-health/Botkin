# tests/test_doc_upload_handler.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_message(text=None, document=None, photo=None, from_id=12345, chat_id=12345):
    msg = MagicMock()
    msg.from_user.id = from_id
    msg.chat.id = chat_id
    msg.text = text
    msg.document = document
    msg.photo = photo
    msg.answer = AsyncMock()
    msg.reply = AsyncMock()
    return msg


def test_format_preview_with_values():
    """Превью содержит найденные значения."""
    from handlers.doc_upload import _format_preview

    extracted = {
        "date": "2026-04-13",
        "laboratory": "KDL",
        "values": {"Hb": 165, "ferritin": 112},
    }
    text = _format_preview(extracted)
    assert "2026-04-13" in text
    assert "KDL" in text
    assert "Hb" in text
    assert "165" in text


def test_format_preview_empty_extracted():
    """Превью для пустого extracted сообщает что числа не найдены."""
    from handlers.doc_upload import _format_preview

    text = _format_preview({})
    assert "не нашёл" in text.lower() or "не найд" in text.lower()


def test_format_preview_values_only_no_date():
    """Если date отсутствует — превью не падает."""
    from handlers.doc_upload import _format_preview

    extracted = {"values": {"ALT": 24}}
    text = _format_preview(extracted)
    assert "ALT" in text
    assert "24" in text


def test_make_filename_format():
    """Имя файла соответствует шаблону ГГГГ-ММ-ДД_<8hex>.<ext>."""
    import re
    from handlers.doc_upload import _make_filename

    name = _make_filename("pdf")
    assert re.match(r"^\d{4}-\d{2}-\d{2}_[0-9a-f]{8}\.pdf$", name)


@pytest.mark.asyncio
async def test_cmd_doc_sets_state():
    """Команда /doc ставит состояние awaiting_doc."""
    from services.state import state_manager

    state_manager.clear_state("12345")
    msg = _make_message(text="/doc", from_id=12345)

    with patch("handlers.doc_upload.state_manager", state_manager):
        from handlers.doc_upload import cmd_doc
        await cmd_doc(msg)

    state = state_manager.get_state("12345")
    assert state is not None
    assert state.state == "awaiting_doc"
    msg.answer.assert_called_once()
