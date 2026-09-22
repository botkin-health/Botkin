# telegram-bot/handlers/doc_queue.py
"""Очередь документов для /doc (issue #499).

Раньше FSM-state `pending` в doc_upload.py хранил ровно один файл — альбом из
нескольких файлов одним сообщением явно отбивался, а ZIP-архив (так Windows
всегда упаковывает группу файлов для пересылки) не распознавался вовсе. Обе
двери были закрыты по одной причине: некуда было положить больше одного файла.

Этот модуль собирает входящие файлы (из альбома, из ZIP или из одного
сообщения) в плоский список — очередь, которую doc_upload.py разбирает по
одному с подтверждением каждого («документ N из M»).

Дедупликация по содержимому (issue #503 → #499): один и тот же файл, будь то
случайный дубль внутри архива или повторная отправка того же документа —
пропускается с понятной причиной, а не даёт лишний LLM-разбор.
"""

from __future__ import annotations

import io
import logging
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from aiogram.types import Message

from handlers import doc_dedup
from handlers.doc_archive import MAX_ARCHIVE_BYTES, MAX_FILES_IN_ARCHIVE, extract_zip_safely

logger = logging.getLogger(__name__)

MAX_FILE_MB = 20
_IMAGE_MIME = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic", "image/heif"}
_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif")
# Windows-«Отправить как ZIP» шлёт application/x-zip-compressed, не
# application/zip — учитываем оба (issue #499).
_ZIP_MIME = {"application/zip", "application/x-zip-compressed"}

# Тексты для сводки «что пропустил и почему» — спокойные, без жаргона
# (пользователь — 73-летний Павел Леонидович).
_REASON_TEXT = {
    "unsupported_type": "не подходящий формат",
    "unsafe_path": "небезопасный путь внутри архива",
    "symlink": "ссылка внутри архива вместо файла",
    "nested_archive": "архив внутри архива",
    "too_large_entry": "слишком большой файл",
    "suspicious_ratio": "файл выглядит подозрительно (слишком сильно сжат)",
    "duplicate_content": "точный повтор уже разобранного файла",
    "too_large": "файл больше лимита Telegram",
    "download_failed": "не получилось скачать",
}

_ARCHIVE_ERROR_TEXT = {
    "archive_too_large": "архив больше {mb} МБ",
    "corrupt_archive": "не смог открыть — архив повреждён или это не zip",
    "too_many_files": "в архиве больше {limit} файлов",
    "zip_bomb": "после распаковки архив оказался подозрительно большим",
}


def _make_item(content: bytes, ext: str, is_pdf: bool, label: str) -> dict[str, Any]:
    """Плоский dict — совместим с тем, как doc_upload.py хранит `pending` в
    FSM (простые сериализуемые словари, без кастомных классов)."""
    return {"content": content, "ext": ext, "is_pdf": is_pdf, "label": label}


class GatherResult:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []
        self.skip_counts: Counter = Counter()
        self.archive_notes: list[str] = []


def _classify_document(mime_type: str, file_name: str) -> tuple[bool, bool, bool]:
    """Возвращает (is_zip, is_pdf, is_image) по mime/расширению."""
    mime = (mime_type or "").lower()
    fname = (file_name or "").lower()
    is_zip = mime in _ZIP_MIME or fname.endswith(".zip")
    is_pdf = mime == "application/pdf" or fname.endswith(".pdf")
    is_image = mime in _IMAGE_MIME or fname.endswith(_IMAGE_EXTENSIONS)
    return is_zip, is_pdf, is_image


async def _download(message: Message, file_id: str) -> Optional[bytes]:
    try:
        tg_file = await message.bot.get_file(file_id)
        buf = io.BytesIO()
        await message.bot.download_file(tg_file.file_path, buf)
        return buf.getvalue()
    except Exception:
        logger.exception("doc_queue: не удалось скачать файл (file_id=%s)", file_id)
        return None


def _format_archive_error(error: str, filename: str) -> str:
    template = _ARCHIVE_ERROR_TEXT.get(error, "не смог обработать архив")
    detail = template.format(mb=MAX_ARCHIVE_BYTES // (1024 * 1024), limit=MAX_FILES_IN_ARCHIVE)
    label = filename or "архив"
    return f"«{label}»: {detail}"


async def gather_source_files(user_id: int, sources: list[Message]) -> GatherResult:
    """Собирает файлы из альбома/одного сообщения в плоский список очереди.

    Разворачивает ZIP-архивы (`handlers.doc_archive`), отбрасывает дубли по
    содержимому (`handlers.doc_dedup`, issue #503) и считает, что и почему
    пропущено — для понятной сводки пользователю.
    """
    result = GatherResult()

    for msg in sources:
        if msg.document:
            doc = msg.document
            fname = doc.file_name or ""
            if (doc.file_size or 0) > MAX_FILE_MB * 1024 * 1024:
                result.skip_counts["too_large"] += 1
                continue

            is_zip, is_pdf, is_image = _classify_document(doc.mime_type or "", fname)
            if not (is_zip or is_pdf or is_image):
                result.skip_counts["unsupported_type"] += 1
                continue

            content = await _download(msg, doc.file_id)
            if content is None:
                result.skip_counts["download_failed"] += 1
                continue

            if is_zip:
                archive_result = extract_zip_safely(content)
                if archive_result.error:
                    result.archive_notes.append(_format_archive_error(archive_result.error, fname))
                    continue
                result.skip_counts.update(archive_result.skipped)
                for extracted in archive_result.files:
                    if doc_dedup.is_duplicate(user_id, extracted.content):
                        result.skip_counts["duplicate_content"] += 1
                        continue
                    result.items.append(_make_item(extracted.content, extracted.ext, extracted.is_pdf, extracted.name))
                continue

            if doc_dedup.is_duplicate(user_id, content):
                result.skip_counts["duplicate_content"] += 1
                continue
            ext = ".pdf" if is_pdf else (Path(fname).suffix or ".jpg")
            result.items.append(_make_item(content, ext, is_pdf, fname or "документ"))

        elif msg.photo:
            file_id = msg.photo[-1].file_id
            content = await _download(msg, file_id)
            if content is None:
                result.skip_counts["download_failed"] += 1
                continue
            if doc_dedup.is_duplicate(user_id, content):
                result.skip_counts["duplicate_content"] += 1
                continue
            result.items.append(_make_item(content, ".jpg", False, "фото"))

    return result


def format_skip_summary(skip_counts: Counter) -> str:
    """Спокойная сводка «что пропустил и почему» — без жаргона."""
    if not skip_counts:
        return ""
    parts = [f"{_REASON_TEXT.get(reason, reason)} — {count}" for reason, count in skip_counts.items()]
    total = sum(skip_counts.values())
    word = "файл" if total == 1 else "файла" if 2 <= total % 10 <= 4 and not (11 <= total % 100 <= 14) else "файлов"
    return f"Пропустил {total} {word}: " + "; ".join(parts) + "."


def format_progress_prefix(pos: int, total: int) -> str:
    """«Документ 2 из 5» — простыми словами, без канцелярита."""
    return f"📄 Документ {pos} из {total}"


# ── FSM-хранение и продолжение очереди ──────────────────────────────────────
#
# Функции ниже используют примитивы из `handlers.doc_upload`
# (`_uploads_dir`/`_stored_name`/`append_document_to_kb`/`run_doc_pipeline`) —
# импортируются лениво внутри функций, а не на уровне модуля: `doc_upload.py`
# импортирует этот модуль на уровне модуля (см. его шапку), так что импорт в
# обратную сторону на уровне модуля дал бы цикл. К моменту вызова этих
# функций оба модуля уже полностью загружены, так что ленивый импорт здесь
# безопасен и не создаёт цикл.


def stage_queue_item(user_id: int, item: dict[str, Any]) -> dict[str, Any]:
    """Кладёт ещё не начатый элемент очереди на диск как `.queued_*` (issue #499).

    Гарантия issue #370 («документ никогда просто не исчезает») должна
    держаться и для файлов, которые пользователь ещё не увидел на
    подтверждении — если он бросит /doc на середине или нажмёт /cancel, эти
    файлы не должны пропасть бесследно вместе с памятью процесса. Возвращает
    компактную запись очереди без сырых байт (`tmp_path` вместо `content`).
    """
    from handlers.doc_upload import _stored_name, _uploads_dir

    content: bytes = item["content"]
    stored_name = _stored_name(content, item["ext"])
    path = _uploads_dir(user_id) / f".queued_{stored_name}"
    path.write_bytes(content)
    return {"tmp_path": str(path), "ext": item["ext"], "is_pdf": item["is_pdf"], "label": item["label"]}


def _load_staged_item(staged: dict[str, Any]) -> tuple[bytes, str, bool, str]:
    """Читает файл очереди обратно с диска и удаляет `.queued_*` — следующий
    шаг (`run_doc_pipeline`) сам запишет свежий `.pending_*`."""
    path = Path(staged["tmp_path"])
    content = path.read_bytes()
    path.unlink(missing_ok=True)
    return content, staged["ext"], staged["is_pdf"], staged.get("label", "документ")


def archive_leftover_documents(user_id: int, data: dict[str, Any]) -> int:
    """Архивирует всё, что осталось незавершённым в /doc-сессии: текущий
    pending и весь хвост очереди (issue #499, гарантия issue #370 — файл
    никогда просто не исчезает, включая брошенные посреди батча).

    Вызывается при явном /cancel — раньше он просто чистил FSM, оставляя
    текущий `.pending_*` гнить как орфан на 24ч (issue #441 п.7б), а хвост
    очереди из issue #499 вообще нигде не появлялся на диске до этого метода.
    Возвращает число заархивированных файлов (для лога/сообщения).
    """
    from datetime import date

    from handlers.doc_upload import _uploads_dir, append_document_to_kb

    archived = 0

    pending = data.get("pending")
    if pending:
        tmp_path = Path(pending["tmp_path"])
        if tmp_path.exists():
            final_path = _uploads_dir(user_id) / pending["stored_name"]
            try:
                tmp_path.replace(final_path)
                append_document_to_kb(
                    user_id,
                    {
                        "added_at": date.today().isoformat(),
                        "file": pending["stored_name"],
                        "extracted": pending.get("extracted") or {},
                        "user_confirmed": False,
                        "auto_archived": True,
                        "reason": "пользователь вышел из /doc, документ не разобран",
                    },
                )
                archived += 1
            except Exception:
                logger.exception("doc_queue: не удалось заархивировать текущий pending при /cancel (user %s)", user_id)

    for staged in data.get("queue") or []:
        tmp_path = Path(staged["tmp_path"])
        if not tmp_path.exists():
            continue
        stored_name = tmp_path.name.removeprefix(".queued_")
        final_path = _uploads_dir(user_id) / stored_name
        try:
            tmp_path.replace(final_path)
            append_document_to_kb(
                user_id,
                {
                    "added_at": date.today().isoformat(),
                    "file": stored_name,
                    "extracted": {},
                    "user_confirmed": False,
                    "auto_archived": True,
                    "reason": "пользователь вышел из /doc, документ из очереди не разобран",
                },
            )
            archived += 1
        except Exception:
            logger.exception("doc_queue: не удалось заархивировать файл очереди при /cancel (user %s)", user_id)

    return archived


async def finish_step_or_advance(
    callback,
    state,
    close_text: str,
    *,
    is_auto: bool,
    parse_mode: Optional[str] = None,
    answer_text: Optional[str] = None,
    done_hint: str = "",
) -> bool:
    """Общий хвост docup_save/docup_cancel (issue #499).

    Если в очереди есть следующий не начатый элемент — сразу запускает его
    разбор (с пометкой прогресса «Документ N из M»), не дожидаясь нового
    сообщения от пользователя. Иначе закрывает шаг как раньше (auto — очищает
    FSM целиком, /doc — сбрасывает `pending` и подсказывает что дальше).
    Возвращает True, если очередь продолжилась.
    """
    from handlers.doc_upload import run_doc_pipeline

    data = await state.get_data()
    queue = data.get("queue") or []

    if not is_auto and queue:
        queue_total = data.get("queue_total") or (len(queue) + 1)
        staged, rest = queue[0], queue[1:]
        pos = queue_total - len(rest)
        content, ext, is_pdf, _label = _load_staged_item(staged)

        await callback.message.edit_text(close_text, parse_mode=parse_mode)
        if answer_text:
            await callback.answer(answer_text)
        else:
            await callback.answer()

        await state.update_data(queue=rest)
        await run_doc_pipeline(
            callback.message,
            state,
            content=content,
            ext=ext,
            is_pdf=is_pdf,
            intro=f"{format_progress_prefix(pos, queue_total)} — читаю…",
            auto=False,
            user_id=callback.from_user.id,
            progress=(pos, queue_total),
        )
        return True

    if is_auto:
        await state.clear()
    else:
        await state.update_data(pending=None)
        if done_hint:
            close_text += f"\n\n{done_hint}"
    await callback.message.edit_text(close_text, parse_mode=parse_mode)
    if answer_text:
        await callback.answer(answer_text)
    else:
        await callback.answer()
    return False
