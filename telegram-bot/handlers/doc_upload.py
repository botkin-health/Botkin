# telegram-bot/handlers/doc_upload.py
"""Handler for /doc command — user uploads medical documents to their KB."""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
from datetime import date
from pathlib import Path
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

logger = logging.getLogger(__name__)

router = Router()

# Корень проекта — два уровня выше telegram-bot/handlers/
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_UPLOADS_DIR = _PROJECT_ROOT / "data" / "uploads"

_MAX_FILE_MB = 20
_IMAGE_MIME = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic", "image/heif"}


class DocUpload(StatesGroup):
    waiting = State()


def _uploads_dir(user_id: int) -> Path:
    d = _UPLOADS_DIR / str(user_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _stored_name(content: bytes, ext: str) -> str:
    """Имя файла: ГГГГ-ММ-ДД_<8 hex от содержимого>.<ext>. Детерминировано, без PII."""
    h = hashlib.sha256(content).hexdigest()[:8]
    return f"{date.today().isoformat()}_{h}{ext}"


def _preview_text(extracted: dict[str, Any]) -> str:
    """Форматирует превью найденных данных для показа пользователю."""
    values = extracted.get("values") if extracted else None
    if not values:
        return (
            "⚠️ Не нашёл числовых значений в документе.\n\n"
            "Это всё равно можно сохранить как архив — "
            "запомню что такой документ есть, и смогу перечитать его при разговоре."
        )

    lines = ["📋 <b>Нашёл в документе:</b>"]

    doc_date = extracted.get("date")
    if doc_date:
        lines.append(f"• <b>Дата:</b> {doc_date}")

    lab = extracted.get("laboratory")
    if lab:
        lines.append(f"• <b>Лаборатория:</b> {lab}")

    doc_type = extracted.get("doc_type")
    if doc_type:
        lines.append(f"• <b>Тип:</b> {doc_type}")

    for key, val in list(values.items())[:15]:
        lines.append(f"• {key}: {str(val)[:50]}")

    if len(values) > 15:
        lines.append(f"  <i>...и ещё {len(values) - 15} показателей</i>")

    lines.append("\nСохранить эти данные в твою базу здоровья?")
    return "\n".join(lines)


def _preview_keyboard(has_values: bool) -> InlineKeyboardMarkup:
    """Inline-клавиатура подтверждения."""
    if has_values:
        buttons = [
            [
                InlineKeyboardButton(text="Сохранить ✅", callback_data="docup_save"),
                InlineKeyboardButton(text="Отмена ❌", callback_data="docup_cancel"),
            ]
        ]
    else:
        buttons = [
            [
                InlineKeyboardButton(text="Сохранить как архив 📁", callback_data="docup_save"),
                InlineKeyboardButton(text="Отмена ❌", callback_data="docup_cancel"),
            ]
        ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _append_document_to_kb(user_id: int, entry: dict[str, Any]) -> None:
    """Делегирует запись в documents[] → core/health/kb_writer (DRY)."""
    from core.health.kb_writer import append_document_to_kb

    kb_path = _PROJECT_ROOT / "data" / "kb" / f"kb_{user_id}.json"
    kb_path.parent.mkdir(parents=True, exist_ok=True)
    append_document_to_kb(kb_path, entry)


@router.message(Command("doc"))
async def cmd_doc(message: Message, state: FSMContext) -> None:
    """/doc — начать загрузку медицинского документа."""
    await state.set_state(DocUpload.waiting)
    await message.answer(
        "📄 Пришли PDF, фото или скан анализа / заключения врача.\n\n"
        "Поддерживаются: PDF, JPG, PNG, HEIC.\n"
        "Выйти из режима загрузки — /cancel.",
        parse_mode="HTML",
    )


@router.message(Command("cancel"), DocUpload.waiting)
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """Выход из режима загрузки по /cancel."""
    await state.clear()
    await message.answer("Вышел из режима загрузки документов.")


@router.message(DocUpload.waiting, F.document | F.photo)
async def doc_received(message: Message, state: FSMContext) -> None:
    """Обрабатывает входящий файл в режиме /doc."""
    from core.health.doc_extractor import extract_medical_data
    from handlers.photo import _extract_pdf_text, _pdf_to_images

    user_id = message.from_user.id

    # Защита от двойной отправки: если предыдущий документ ещё не подтверждён — напоминаем.
    data = await state.get_data()
    if data.get("pending"):
        await message.answer(
            "⏳ Сначала ответь на предыдущий документ — нажми «Сохранить» или «Отмена».\n"
            "Или напиши /cancel чтобы отменить и начать заново."
        )
        return

    # Определяем тип и скачиваем
    if message.document:
        doc = message.document
        if (doc.file_size or 0) > _MAX_FILE_MB * 1024 * 1024:
            await message.answer(
                f"⚠️ Файл больше {_MAX_FILE_MB} МБ (лимит Telegram). Пришли PDF полегче или скриншоты страниц."
            )
            return
        mime = (doc.mime_type or "").lower()
        fname = (doc.file_name or "").lower()
        is_pdf = mime == "application/pdf" or fname.endswith(".pdf")
        is_image = mime in _IMAGE_MIME or fname.endswith((".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"))
        if not is_pdf and not is_image:
            await message.answer(
                "📎 Такой формат пока не умею. Поддерживаю PDF, JPG/PNG/HEIC.\n"
                "Если это .doc/.docx — сохрани как PDF или пришли фото страниц."
            )
            return
        file_id = doc.file_id
        ext = ".pdf" if is_pdf else (Path(fname).suffix or ".jpg")
    else:
        is_pdf = False
        file_id = message.photo[-1].file_id
        ext = ".jpg"

    processing = await message.answer("⏳ Читаю…")

    try:
        tg_file = await message.bot.get_file(file_id)
        buf = io.BytesIO()
        await message.bot.download_file(tg_file.file_path, buf)
        content = buf.getvalue()
    except Exception:
        logger.exception("doc_upload: не удалось скачать файл от %s", user_id)
        await processing.edit_text("⚠️ Не удалось скачать файл. Попробуй ещё раз.")
        return

    # Сохраняем как .pending до подтверждения
    stored_name = _stored_name(content, ext)
    tmp_path = _uploads_dir(user_id) / f".pending_{stored_name}"
    tmp_path.write_bytes(content)

    # Извлекаем показатели
    loop = asyncio.get_event_loop()
    try:
        if is_pdf:
            pdf_text = await loop.run_in_executor(None, lambda: _extract_pdf_text(tmp_path))
            if pdf_text:
                extracted = await extract_medical_data(pdf_text.encode(), "text/plain")
            else:
                # Сканированный PDF — берём первую страницу как изображение
                pages = await loop.run_in_executor(None, lambda: _pdf_to_images(tmp_path, max_pages=1))
                if pages:
                    extracted = await extract_medical_data(pages[0].read_bytes(), "image/jpeg")
                else:
                    extracted = {}
        else:
            media_type = "image/png" if ext == ".png" else "image/jpeg"
            extracted = await extract_medical_data(content, media_type)
    except Exception:
        logger.exception("doc_upload: экстракция не удалась (user %s)", user_id)
        extracted = {}

    await state.update_data(pending={"tmp_path": str(tmp_path), "stored_name": stored_name, "extracted": extracted})
    await processing.edit_text(
        _preview_text(extracted),
        reply_markup=_preview_keyboard(bool(extracted.get("values"))),
        parse_mode="HTML",
    )


@router.callback_query(DocUpload.waiting, F.data.in_({"docup_save", "docup_cancel"}))
async def doc_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    """Пользователь подтвердил или отменил сохранение."""
    data = await state.get_data()
    pending = data.get("pending")
    if not pending:
        await callback.answer("Нет документа в обработке", show_alert=True)
        return

    tmp_path = Path(pending["tmp_path"])
    user_id = callback.from_user.id

    if callback.data == "docup_cancel":
        tmp_path.unlink(missing_ok=True)
        await state.update_data(pending=None)
        await callback.message.edit_text("❌ Не сохранил. Пришли другой документ или /cancel.")
        await callback.answer()
        return

    # Сохранение
    final_path = _uploads_dir(user_id) / pending["stored_name"]
    try:
        if tmp_path.exists():
            tmp_path.replace(final_path)
        entry = {
            "added_at": date.today().isoformat(),
            "file": pending["stored_name"],
            "extracted": pending.get("extracted") or {},
            "user_confirmed": True,
        }
        _append_document_to_kb(user_id, entry)
    except Exception:
        logger.exception("doc_upload: сохранение не удалось (user %s)", user_id)
        await callback.message.edit_text("⚠️ Не получилось сохранить, попробуй ещё раз.")
        await callback.answer()
        return

    await state.update_data(pending=None)
    await callback.message.edit_text(
        "✅ Сохранено в твою базу здоровья.\n\nМожешь прислать ещё документ или /cancel.",
        parse_mode="HTML",
    )
    await callback.answer("Сохранено")


@router.message(DocUpload.waiting)
async def doc_wrong_content(message: Message) -> None:
    """Напоминание если прислали не файл в режиме /doc."""
    await message.answer("Жду PDF, фото или скан документа. Выйти — /cancel.")
