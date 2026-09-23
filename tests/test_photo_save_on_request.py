"""Тесты фазы 3 (issue #370): «сохрани фото/PDF про запас» по подписи —
telegram-bot/handlers/photo.py: handle_photo_message / handle_document_image.

Патчим save_photo/_download_pdf (сеть) и handlers.doc_upload.save_files_on_request
(файловая система/KB — своя логика уже покрыта tests/test_doc_upload_handler.py).
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOT_ROOT = PROJECT_ROOT / "telegram-bot"
for p in [str(PROJECT_ROOT), str(BOT_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)


def _make_photo_message(caption: str, user_id: int = 111222):
    msg = AsyncMock()
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.caption = caption
    msg.media_group_id = None
    msg.photo = [MagicMock(file_id="fake_file_id")]
    msg.answer = AsyncMock()
    msg.bot = AsyncMock()
    return msg


@pytest.mark.asyncio
async def test_handle_photo_message_saves_on_request_and_skips_food_pipeline(tmp_path):
    from handlers.photo import handle_photo_message

    fake_path = tmp_path / "policy.jpg"
    fake_path.write_bytes(b"fake")

    msg = _make_photo_message("сохрани, пожалуйста, полис ОМС")

    with (
        patch("handlers.photo.save_photo", AsyncMock(return_value=fake_path)),
        patch("handlers.doc_upload.save_files_on_request", MagicMock(return_value=["полис ОМС"])) as save_mock,
        patch("handlers.photo.process_photos_list", AsyncMock()) as process_mock,
    ):
        await handle_photo_message(msg, bot=AsyncMock(), user_id=msg.from_user.id, state=None)

    save_mock.assert_called_once()
    called_user_id, called_paths, called_caption = save_mock.call_args[0]
    assert called_user_id == msg.from_user.id
    assert called_paths == [fake_path]
    assert "сохрани" in called_caption.lower()

    process_mock.assert_not_called()
    msg.answer.assert_awaited_once()
    reply_text = msg.answer.call_args[0][0]
    assert "полис ОМС" in reply_text
    assert "/my_docs" in reply_text


@pytest.mark.asyncio
async def test_handle_photo_message_dedup_all_skipped_replies_short(tmp_path):
    from handlers.photo import handle_photo_message

    fake_path = tmp_path / "dup.jpg"
    fake_path.write_bytes(b"fake")

    msg = _make_photo_message("на всякий случай сохрани")

    with (
        patch("handlers.photo.save_photo", AsyncMock(return_value=fake_path)),
        patch("handlers.doc_upload.save_files_on_request", MagicMock(return_value=[])),
        patch("handlers.photo.process_photos_list", AsyncMock()) as process_mock,
    ):
        await handle_photo_message(msg, bot=AsyncMock(), user_id=msg.from_user.id, state=None)

    process_mock.assert_not_called()
    msg.answer.assert_awaited_once()
    reply_text = msg.answer.call_args[0][0]
    assert "уже сохранил" in reply_text.lower()


def _make_pdf_document_message(caption: str, user_id: int = 333444, file_name: str = "insurance.pdf"):
    doc = MagicMock()
    doc.mime_type = "application/pdf"
    doc.file_name = file_name

    processing_msg = AsyncMock()
    processing_msg.edit_text = AsyncMock()
    processing_msg.delete = AsyncMock()

    msg = AsyncMock()
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.document = doc
    msg.caption = caption
    msg.media_group_id = None
    msg.answer = AsyncMock(return_value=processing_msg)
    return msg, processing_msg


@pytest.mark.asyncio
async def test_handle_document_image_pdf_saves_on_request_before_medical_check(tmp_path):
    """PDF с подписью «сохрани» — сохраняется как есть, эвристика «похоже на
    анализ» и ask_agent даже не запускаются (issue #370, фаза 3)."""
    from handlers.photo import handle_document_image

    msg, processing_msg = _make_pdf_document_message("сохрани полис ОМС на всякий случай")
    fake_pdf_path = tmp_path / "insurance.pdf"
    fake_pdf_path.write_bytes(b"%PDF-fake-content")

    mock_run_pipeline = AsyncMock()
    mock_ask_agent = MagicMock(return_value="не должно вызываться")

    with (
        patch("handlers.photo._download_pdf", AsyncMock(return_value=fake_pdf_path)),
        patch("handlers.photo._extract_pdf_text", return_value="Полис ОМС серия 1234"),
        patch("handlers.doc_upload.run_doc_pipeline", mock_run_pipeline),
        patch("core.agent_chat.ask_agent", mock_ask_agent),
        patch("handlers.doc_upload.save_files_on_request", MagicMock(return_value=["полис ОМС"])) as save_mock,
    ):
        await handle_document_image(msg, album=None, state=AsyncMock())

    assert not mock_run_pipeline.called
    assert not mock_ask_agent.called
    save_mock.assert_called_once()
    called_user_id, called_paths, called_caption = save_mock.call_args[0]
    assert called_user_id == msg.from_user.id
    assert called_paths == [fake_pdf_path]
    assert "сохрани" in called_caption.lower()

    reply_text = processing_msg.edit_text.call_args.args[0]
    assert "полис ОМС" in reply_text
    assert "/my_docs" in reply_text


@pytest.mark.asyncio
async def test_handle_photo_message_without_save_caption_goes_to_normal_pipeline(tmp_path):
    """Фото без явной просьбы сохранить — поведение не меняется (обычный пайплайн)."""
    from handlers.photo import handle_photo_message

    fake_path = tmp_path / "food.jpg"
    fake_path.write_bytes(b"fake")

    msg = _make_photo_message("омлет с сыром")

    with (
        patch("handlers.photo.save_photo", AsyncMock(return_value=fake_path)),
        patch("handlers.doc_upload.save_files_on_request", MagicMock()) as save_mock,
        patch("handlers.photo.process_photos_list", AsyncMock()) as process_mock,
    ):
        await handle_photo_message(msg, bot=AsyncMock(), user_id=msg.from_user.id, state=None)

    save_mock.assert_not_called()
    process_mock.assert_called_once()
