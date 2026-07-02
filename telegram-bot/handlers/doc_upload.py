"""Команда /doc — самостоятельная загрузка медицинских документов в KB (#227).

Флоу (спека docs/architecture/2026-06-28-user-kb-self-onboarding-design.md):
/doc → пользователь шлёт PDF/фото/скан → Claude извлекает показатели →
превью с кнопками [Сохранить ✅] [Отмена ❌] → файл в data/uploads/<id>/,
данные в kb_<id>.json documents[]. Батч: после сохранения state остаётся
активным, можно слать следующий документ. Выход — /cancel или любая команда.

Роутер регистрируется ДО photo_router (bot.py): вне состояния DocUpload
хендлеры не срабатывают (StateFilter), обычный пайплайн фото/PDF не меняется.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

logger = logging.getLogger(__name__)

router = Router()

MSK = ZoneInfo("Europe/Moscow")
MAX_FILE_MB = 20  # лимит Telegram Bot API
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

IMAGE_MIME = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic", "image/heif"}


class DocUpload(StatesGroup):
    waiting = State()


# ---------------------------------------------------------------------------
# Хранение
# ---------------------------------------------------------------------------


def _uploads_dir(user_id: int) -> Path:
    d = _PROJECT_ROOT / "data" / "uploads" / str(user_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _stored_name(content: bytes, ext: str) -> str:
    """<дата>_<8 символов хеша>.<ext> — без PII в имени (спека)."""
    h = hashlib.sha256(content).hexdigest()[:8]
    return f"{datetime.now(MSK).strftime('%Y-%m-%d')}_{h}{ext}"


def _kb_path(user_id: int) -> Path:
    return _PROJECT_ROOT / "data" / "kb" / f"kb_{user_id}.json"


def append_document_to_kb(user_id: int, entry: dict) -> None:
    """Append в kb_<id>.json documents[]; атомарная замена через tmp (спека).

    KB может отсутствовать (новый пользователь) — создаём минимальный.
    """
    path = _kb_path(user_id)
    kb: dict = {}
    if path.exists():
        try:
            kb = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.exception("KB %s не читается — документ добавлю в новый файл", path)
            kb = {}
    if not isinstance(kb, dict):
        kb = {}
    kb.setdefault("documents", []).append(entry)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(kb, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Превью
# ---------------------------------------------------------------------------


def _preview_text(extracted: dict) -> str:
    values = extracted.get("values") or {}
    if not values:
        return (
            "Не нашёл числовых значений в документе.\n"
            "Это всё равно можно сохранить как архив — запомню, что такой документ есть."
        )
    lines = ["Нашёл в документе:"]
    if extracted.get("date"):
        lines.append(f"• Дата: {extracted['date']}")
    if extracted.get("laboratory"):
        lines.append(f"• Лаборатория: {extracted['laboratory']}")
    if extracted.get("doc_type"):
        lines.append(f"• Тип: {extracted['doc_type']}")
    for name, val in list(values.items())[:25]:
        lines.append(f"• {name}: {val}")
    if len(values) > 25:
        lines.append(f"…и ещё {len(values) - 25} показателей")
    return "\n".join(lines)


def _preview_keyboard(has_values: bool) -> InlineKeyboardMarkup:
    save_label = "Сохранить ✅" if has_values else "Сохранить как архив 📁"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=save_label, callback_data="docup_save"),
                InlineKeyboardButton(text="Отмена ❌", callback_data="docup_cancel"),
            ]
        ]
    )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


@router.message(Command("doc"))
async def cmd_doc(message: Message, state: FSMContext):
    await state.set_state(DocUpload.waiting)
    await state.update_data(pending=None)
    await message.answer(
        "📂 Пришли PDF, фото или скан анализа/заключения — разберу и сохраню "
        "в твою историю здоровья.\n\nВыйти — /cancel."
    )


@router.message(DocUpload.waiting, Command("cancel"))
async def cmd_doc_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Ок, вышел из режима загрузки документов.")


@router.message(DocUpload.waiting, F.text & F.text.startswith("/"))
async def doc_other_command(message: Message, state: FSMContext):
    """Любая другая команда выходит из режима; пользователь повторяет её штатно."""
    await state.clear()
    await message.answer("Вышел из режима загрузки документов. Повтори команду ещё раз.")


@router.message(DocUpload.waiting, F.document | F.photo)
async def doc_received(message: Message, state: FSMContext):
    from core.health.doc_extractor import extract_from_image, extract_from_text
    from handlers.photo import _extract_pdf_text

    user_id = message.from_user.id

    # --- скачиваем файл ---
    if message.document:
        doc = message.document
        if (doc.file_size or 0) > MAX_FILE_MB * 1024 * 1024:
            await message.answer(
                f"⚠️ Файл больше {MAX_FILE_MB} МБ (лимит Telegram). Пришли PDF полегче или скриншоты страниц."
            )
            return
        mime = (doc.mime_type or "").lower()
        fname = (doc.file_name or "").lower()
        is_pdf = mime == "application/pdf" or fname.endswith(".pdf")
        is_image = mime in IMAGE_MIME or fname.endswith((".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"))
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
        import io

        tg_file = await message.bot.get_file(file_id)
        buf = io.BytesIO()
        await message.bot.download_file(tg_file.file_path, buf)
        content = buf.getvalue()
    except Exception:
        logger.exception("doc_upload: не удалось скачать файл от %s", user_id)
        await processing.edit_text("⚠️ Не удалось скачать файл. Попробуй ещё раз.")
        return

    # --- временный файл; подтверждение переносит его в uploads ---
    stored_name = _stored_name(content, ext)
    tmp_path = _uploads_dir(user_id) / f".pending_{stored_name}"
    tmp_path.write_bytes(content)

    # --- извлекаем показатели ---
    loop = asyncio.get_event_loop()
    try:
        if is_pdf:
            pdf_text = _extract_pdf_text(tmp_path)
            if pdf_text:
                extracted = await loop.run_in_executor(None, lambda: extract_from_text(pdf_text))
            else:
                # сканированный PDF: первую страницу — в vision
                from handlers.photo import _pdf_to_images

                pages = _pdf_to_images(tmp_path, max_pages=1)
                extracted = (
                    await loop.run_in_executor(None, lambda: extract_from_image(pages[0].read_bytes())) if pages else {}
                )
        else:
            media_type = "image/png" if ext == ".png" else "image/jpeg"
            extracted = await loop.run_in_executor(None, lambda: extract_from_image(content, media_type))
    except Exception:
        logger.exception("doc_upload: экстракция не удалась (user %s)", user_id)
        extracted = {}

    await state.update_data(pending={"tmp_path": str(tmp_path), "stored_name": stored_name, "extracted": extracted})
    await processing.edit_text(_preview_text(extracted), reply_markup=_preview_keyboard(bool(extracted.get("values"))))


@router.callback_query(DocUpload.waiting, F.data.in_({"docup_save", "docup_cancel"}))
async def doc_confirm(callback: CallbackQuery, state: FSMContext):
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

    # --- save ---
    final_path = _uploads_dir(user_id) / pending["stored_name"]
    try:
        if tmp_path.exists():
            tmp_path.replace(final_path)
        entry = {
            "added_at": datetime.now(MSK).strftime("%Y-%m-%d"),
            "file": pending["stored_name"],
            "extracted": pending.get("extracted") or {},
            "user_confirmed": True,
        }
        append_document_to_kb(user_id, entry)
    except Exception:
        logger.exception("doc_upload: сохранение не удалось (user %s)", user_id)
        await callback.message.edit_text("⚠️ Не получилось сохранить, попробуй ещё раз.")
        await callback.answer()
        return

    await state.update_data(pending=None)
    await callback.message.edit_text("✅ Сохранено. Можешь прислать ещё документ или /cancel.")
    await callback.answer("Сохранено")


@router.message(DocUpload.waiting)
async def doc_wrong_content(message: Message):
    await message.answer("Жду PDF, фото или скан документа. Выйти — /cancel.")
