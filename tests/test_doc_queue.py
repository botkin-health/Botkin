"""Тесты сборки очереди документов для /doc (issue #499)."""

import io
import zipfile

import pytest
from unittest.mock import AsyncMock, MagicMock

from handlers import doc_dedup


@pytest.fixture(autouse=True)
def _reset_dedup_cache():
    doc_dedup.reset()
    yield
    doc_dedup.reset()


def _make_zip(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _make_doc_message(*, file_name, mime_type, file_size, content, from_id=1):
    doc = MagicMock()
    doc.file_name = file_name
    doc.mime_type = mime_type
    doc.file_size = file_size
    doc.file_id = f"file-{file_name}"

    msg = MagicMock()
    msg.document = doc
    msg.photo = None
    msg.from_user.id = from_id
    msg.bot = AsyncMock()
    msg.bot.get_file = AsyncMock(return_value=MagicMock(file_path="path/on/tg"))

    async def fake_download(file_path, buf):
        buf.write(content)

    msg.bot.download_file = AsyncMock(side_effect=fake_download)
    return msg


def _make_photo_message(content: bytes, from_id=1):
    photo = MagicMock()
    photo.file_id = "photo-file-id"

    msg = MagicMock()
    msg.document = None
    msg.photo = [photo]
    msg.from_user.id = from_id
    msg.bot = AsyncMock()
    msg.bot.get_file = AsyncMock(return_value=MagicMock(file_path="path/on/tg"))

    async def fake_download(file_path, buf):
        buf.write(content)

    msg.bot.download_file = AsyncMock(side_effect=fake_download)
    return msg


@pytest.mark.asyncio
async def test_gather_single_pdf_document():
    from handlers.doc_queue import gather_source_files

    msg = _make_doc_message(file_name="a.pdf", mime_type="application/pdf", file_size=100, content=b"%PDF-a")
    result = await gather_source_files(1, [msg])

    assert len(result.items) == 1
    assert result.items[0]["is_pdf"] is True
    assert result.items[0]["ext"] == ".pdf"
    assert not result.skip_counts


@pytest.mark.asyncio
async def test_gather_album_of_multiple_files_no_longer_rejected():
    """Раньше альбом >1 файл отбивался целиком — теперь оба файла в очереди."""
    from handlers.doc_queue import gather_source_files

    msg1 = _make_doc_message(file_name="a.pdf", mime_type="application/pdf", file_size=100, content=b"%PDF-a")
    msg2 = _make_doc_message(file_name="b.jpg", mime_type="image/jpeg", file_size=100, content=b"\xff\xd8-b")
    result = await gather_source_files(1, [msg1, msg2])

    assert len(result.items) == 2
    labels = {item["label"] for item in result.items}
    assert labels == {"a.pdf", "b.jpg"}


@pytest.mark.asyncio
async def test_gather_expands_zip_into_queue_items():
    from handlers.doc_queue import gather_source_files

    zip_bytes = _make_zip({"biopsy.pdf": b"%PDF-biopsy", "scan.jpg": b"\xff\xd8-scan"})
    msg = _make_doc_message(
        file_name="docs.zip", mime_type="application/x-zip-compressed", file_size=len(zip_bytes), content=zip_bytes
    )
    result = await gather_source_files(1, [msg])

    assert len(result.items) == 2
    names = {item["label"] for item in result.items}
    assert names == {"biopsy.pdf", "scan.jpg"}


@pytest.mark.asyncio
async def test_gather_zip_windows_mime_x_zip_compressed_accepted():
    """Windows шлёт application/x-zip-compressed — обязательный кейс issue #499."""
    from handlers.doc_queue import gather_source_files

    zip_bytes = _make_zip({"a.pdf": b"%PDF-a"})
    msg = _make_doc_message(
        file_name="pack.zip", mime_type="application/x-zip-compressed", file_size=len(zip_bytes), content=zip_bytes
    )
    result = await gather_source_files(1, [msg])
    assert len(result.items) == 1


@pytest.mark.asyncio
async def test_gather_zip_extension_fallback_when_mime_missing():
    from handlers.doc_queue import gather_source_files

    zip_bytes = _make_zip({"a.pdf": b"%PDF-a"})
    msg = _make_doc_message(
        file_name="pack.zip", mime_type="application/octet-stream", file_size=len(zip_bytes), content=zip_bytes
    )
    result = await gather_source_files(1, [msg])
    assert len(result.items) == 1


@pytest.mark.asyncio
async def test_gather_zip_mixed_content_reports_skipped():
    from handlers.doc_queue import gather_source_files

    zip_bytes = _make_zip({"a.pdf": b"%PDF-a", "readme.txt": b"not medical"})
    msg = _make_doc_message(
        file_name="pack.zip", mime_type="application/zip", file_size=len(zip_bytes), content=zip_bytes
    )
    result = await gather_source_files(1, [msg])

    assert len(result.items) == 1
    assert result.skip_counts["unsupported_type"] == 1


@pytest.mark.asyncio
async def test_gather_corrupt_zip_reported_as_archive_note_not_crash():
    from handlers.doc_queue import gather_source_files

    msg = _make_doc_message(
        file_name="broken.zip", mime_type="application/zip", file_size=20, content=b"not a real zip"
    )
    result = await gather_source_files(1, [msg])

    assert result.items == []
    assert len(result.archive_notes) == 1
    assert "broken.zip" in result.archive_notes[0]


@pytest.mark.asyncio
async def test_gather_duplicate_within_same_zip_deduped():
    """Два одинаковых по содержимому файла внутри архива — второй считается
    дублем и не идёт в очередь дважды (issue #503)."""
    from handlers.doc_queue import gather_source_files

    zip_bytes = _make_zip({"scan1.pdf": b"%PDF-same-content", "scan2.pdf": b"%PDF-same-content"})
    msg = _make_doc_message(
        file_name="pack.zip", mime_type="application/zip", file_size=len(zip_bytes), content=zip_bytes
    )
    result = await gather_source_files(42, [msg])

    assert len(result.items) == 1
    assert result.skip_counts["duplicate_content"] == 1


@pytest.mark.asyncio
async def test_gather_duplicate_across_calls_within_ttl():
    """Тот же файл, присланный отдельным сообщением после того как уже был
    поставлен в очередь ранее для этого юзера — считается дублем (issue #503:
    один и тот же PDF пятью разными сообщениями)."""
    from handlers.doc_queue import gather_source_files

    content = b"%PDF-repeat-me"
    msg1 = _make_doc_message(file_name="a.pdf", mime_type="application/pdf", file_size=10, content=content)
    msg2 = _make_doc_message(file_name="a.pdf", mime_type="application/pdf", file_size=10, content=content)

    result1 = await gather_source_files(7, [msg1])
    result2 = await gather_source_files(7, [msg2])

    assert len(result1.items) == 1
    assert len(result2.items) == 0
    assert result2.skip_counts["duplicate_content"] == 1


@pytest.mark.asyncio
async def test_gather_unsupported_top_level_file_skipped():
    from handlers.doc_queue import gather_source_files

    msg = _make_doc_message(file_name="report.docx", mime_type="application/msword", file_size=10, content=b"x")
    result = await gather_source_files(1, [msg])
    assert result.items == []
    assert result.skip_counts["unsupported_type"] == 1


@pytest.mark.asyncio
async def test_gather_photo_message():
    from handlers.doc_queue import gather_source_files

    msg = _make_photo_message(b"\xff\xd8-photo")
    result = await gather_source_files(1, [msg])
    assert len(result.items) == 1
    assert result.items[0]["is_pdf"] is False


def test_format_skip_summary_empty():
    from handlers.doc_queue import format_skip_summary
    from collections import Counter

    assert format_skip_summary(Counter()) == ""


def test_format_skip_summary_lists_reasons():
    from handlers.doc_queue import format_skip_summary
    from collections import Counter

    text = format_skip_summary(Counter({"unsupported_type": 2, "duplicate_content": 1}))
    assert "3" in text
    assert "не подходящий формат" in text
    assert "повтор" in text


def test_format_progress_prefix():
    from handlers.doc_queue import format_progress_prefix

    assert format_progress_prefix(2, 5) == "📄 Документ 2 из 5"
