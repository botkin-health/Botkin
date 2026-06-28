# telegram-bot/handlers/doc_upload.py
"""Handler for /doc command — user uploads medical documents to their KB."""
from __future__ import annotations

import logging
import secrets
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from services.state import UserState, state_manager

logger = logging.getLogger(__name__)

router = Router()

# Корень проекта — два уровня выше telegram-bot/handlers/
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_UPLOADS_DIR = _PROJECT_ROOT / "data" / "uploads"

# Callback data префиксы
_CB_SAVE = "doc_save:"
_CB_SAVE_ARCHIVE = "doc_archive:"
_CB_CANCEL = "doc_cancel:"


def _make_filename(ext: str) -> str:
    """Генерирует имя файла: ГГГГ-ММ-ДД_<8hex>.<ext>."""
    today = date.today().isoformat()
    suffix = secrets.token_hex(4)
    return f"{today}_{suffix}.{ext}"


def _format_preview(extracted: dict[str, Any]) -> str:
    """Форматирует превью найденных данных для показа пользователю."""
    if not extracted or not extracted.get("values"):
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

    values = extracted.get("values", {})
    for key, val in list(values.items())[:15]:
        lines.append(f"• {key}: {val}")

    if len(values) > 15:
        lines.append(f"  <i>...и ещё {len(values) - 15} показателей</i>")

    lines.append("\nСохранить эти данные в твою базу здоровья?")
    return "\n".join(lines)


def _save_keyboard(has_values: bool, state_key: str) -> InlineKeyboardMarkup:
    """Inline-клавиатура подтверждения."""
    if has_values:
        buttons = [
            [
                InlineKeyboardButton(text="Сохранить ✅", callback_data=f"{_CB_SAVE}{state_key}"),
                InlineKeyboardButton(text="Отмена ❌", callback_data=f"{_CB_CANCEL}{state_key}"),
            ]
        ]
    else:
        buttons = [
            [
                InlineKeyboardButton(
                    text="Сохранить как архив 📁",
                    callback_data=f"{_CB_SAVE_ARCHIVE}{state_key}",
                ),
                InlineKeyboardButton(text="Отмена ❌", callback_data=f"{_CB_CANCEL}{state_key}"),
            ]
        ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _download_file(bot_token: str, file_id: str) -> tuple[bytes, str]:
    """Скачивает файл из Telegram. Возвращает (bytes, file_path)."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}")
        r.raise_for_status()
        file_path = r.json()["result"]["file_path"]

        dl = await client.get(f"https://api.telegram.org/file/bot{bot_token}/{file_path}")
        dl.raise_for_status()
        return dl.content, file_path


def _save_file(user_id: int, file_bytes: bytes, ext: str) -> str:
    """Сохраняет файл в data/uploads/<user_id>/. Возвращает имя файла."""
    user_dir = _UPLOADS_DIR / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    filename = _make_filename(ext)
    (user_dir / filename).write_bytes(file_bytes)
    return filename


def _write_to_kb(user_id: int, filename: str, extracted: dict, user_confirmed: bool) -> None:
    """Добавляет документ в kb_<user_id>.json."""
    from core.health.kb_writer import append_document_to_kb

    kb_dir = _PROJECT_ROOT / "data" / "kb"
    kb_path = kb_dir / f"kb_{user_id}.json"
    kb_path.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "added_at": date.today().isoformat(),
        "file": filename,
        "extracted": extracted,
        "user_confirmed": user_confirmed,
    }
    append_document_to_kb(kb_path, entry)


@router.message(Command("doc"))
async def cmd_doc(message: Message) -> None:
    """/doc — начать загрузку медицинского документа."""
    user_id = str(message.from_user.id)
    state_manager.set_state(user_id, UserState(user_id=user_id, state="awaiting_doc", data={}))
    await message.answer(
        "📄 Пришли PDF, фото или скан анализа / заключения врача.\n\n"
        "Поддерживаются: PDF, JPG, PNG.",
        parse_mode="HTML",
    )


@router.message(F.document | F.photo)
async def handle_document_or_photo(message: Message) -> None:
    """Обрабатывает входящий файл если пользователь в состоянии awaiting_doc."""
    user_id = str(message.from_user.id)
    state = state_manager.get_state(user_id)

    if not state or state.state != "awaiting_doc":
        return

    await message.answer("⏳ Читаю документ...")

    from bot_token import resolve_bot_token
    from core.health.doc_extractor import extract_medical_data

    bot_token = resolve_bot_token()

    try:
        if message.document:
            file_id = message.document.file_id
            mime_type = message.document.mime_type or "application/pdf"
            ext = mime_type.split("/")[-1] if "/" in mime_type else "pdf"
            if ext == "jpeg":
                ext = "jpg"
        else:
            file_id = message.photo[-1].file_id
            mime_type = "image/jpeg"
            ext = "jpg"

        file_bytes, _ = await _download_file(bot_token, file_id)
        extracted = await extract_medical_data(file_bytes, mime_type)

        state_key = secrets.token_hex(4)
        state_manager.set_state(
            user_id,
            UserState(
                user_id=user_id,
                state="awaiting_doc_confirm",
                data={
                    "file_bytes": file_bytes,
                    "ext": ext,
                    "extracted": extracted,
                    "state_key": state_key,
                },
            ),
        )

        has_values = bool(extracted.get("values"))
        preview_text = _format_preview(extracted)
        keyboard = _save_keyboard(has_values, state_key)

        await message.answer(preview_text, parse_mode="HTML", reply_markup=keyboard)

    except Exception as e:
        logger.error("doc_upload: ошибка обработки файла от %s: %s", user_id, e)
        state_manager.clear_state(user_id)
        await message.answer(
            "❌ Не удалось прочитать файл. Попробуй ещё раз или пришли в другом формате."
        )


@router.callback_query(F.data.startswith(_CB_SAVE))
@router.callback_query(F.data.startswith(_CB_SAVE_ARCHIVE))
async def callback_save(callback: CallbackQuery) -> None:
    """Пользователь подтвердил сохранение."""
    user_id = str(callback.from_user.id)
    state = state_manager.get_state(user_id)

    if not state or state.state != "awaiting_doc_confirm":
        await callback.answer("Время вышло. Пришли файл заново через /doc.")
        return

    data = state.data
    expected_key = data.get("state_key", "")
    cb_data = callback.data or ""
    actual_key = cb_data.split(":", 1)[1] if ":" in cb_data else ""
    if actual_key != expected_key:
        await callback.answer("Устаревшая кнопка.")
        return

    try:
        filename = _save_file(
            int(user_id),
            data["file_bytes"],
            data["ext"],
        )
        _write_to_kb(int(user_id), filename, data["extracted"], user_confirmed=True)

        state_manager.clear_state(user_id)
        await callback.message.edit_text(
            "✅ Сохранено в твою базу здоровья.\n\n"
            "Можешь прислать ещё документ или написать /doc в любой момент.",
            parse_mode="HTML",
        )
        await callback.answer()
    except Exception as e:
        logger.error("doc_upload: ошибка сохранения для %s: %s", user_id, e)
        await callback.answer("Ошибка сохранения. Попробуй позже.")


@router.callback_query(F.data.startswith(_CB_CANCEL))
async def callback_cancel(callback: CallbackQuery) -> None:
    """Пользователь отменил сохранение."""
    user_id = str(callback.from_user.id)
    state_manager.clear_state(user_id)
    await callback.message.edit_text("❌ Отменено. Ничего не сохранено.")
    await callback.answer()
