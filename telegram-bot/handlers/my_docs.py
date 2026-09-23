# telegram-bot/handlers/my_docs.py
"""Команда /my_docs (issue #370, фаза 4) — список документов профиля
пользователя (полисы, справки, анализы и т.п. из `documents[]` в
`kb_<user_id>.json`) с кнопкой «Прислать» на каждый.

Метаданные и разрешение id → путь на диске — `core.health.profile_documents`
(та же логика, что и у агентных тулов `list_documents`/`send_document`,
telegram-bot/webhook/agent_tools/documents.py). Здесь — только Telegram-обвязка:
рендер списка и отправка файла обратно через aiogram.
"""

from __future__ import annotations

import html
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, FSInputFile, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.health.profile_documents import (
    DocumentNotFoundError,
    list_documents,
    resolve_document_path,
)

logger = logging.getLogger(__name__)

router = Router()

# Больше не показываем одним списком — новые сверху, до этого числа; если
# документов больше, говорим сколько ещё скрыто (issue #370, фаза 4).
MAX_LISTED = 20

_CATEGORY_LABELS_RU = {
    "insurance": "🛡 Страховка/полис",
    "certificate": "📜 Справка/сертификат",
    "contact": "📇 Контакт",
    "medical": "🏥 Медицинский",
    "other": "📁 Документ",
}

_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif")


class DocSendCallback(CallbackData, prefix="docsnd"):
    """`idx` — позиция документа в свежем `list_documents(user_id)` ЭТОГО
    пользователя на момент нажатия (не хранимый постоянный id) — короткий
    (≤64 байт с запасом) и не может сослаться на чужой документ: список
    всегда перезапрашивается по `callback.from_user.id` нажавшего, поэтому
    даже подделанный idx максимум укажет на СВОЙ ЖЕ документ другого номера
    (issue #370, фаза 4)."""

    idx: int


def _category_label(category: str | None) -> str:
    return _CATEGORY_LABELS_RU.get(category or "other", _CATEGORY_LABELS_RU["other"])


def _format_doc_line(idx: int, doc: dict) -> str:
    title = html.escape(doc.get("title") or "Документ")
    label = _category_label(doc.get("category"))
    added_at = doc.get("added_at") or "?"
    return f"{idx + 1}. <b>{title}</b>\n   {label} · {added_at}"


@router.message(Command("my_docs"))
async def cmd_my_docs(message: Message, user_id: int):
    """Список документов профиля — новые сверху, до `MAX_LISTED`, у каждого
    инлайн-кнопка «Прислать»."""
    docs = list_documents(user_id)

    if not docs:
        await message.answer("Документов пока нет. Пришли фото или PDF с подписью «сохрани» — положу сюда.")
        return

    shown = docs[:MAX_LISTED]
    lines = ["📁 <b>Твои документы:</b>\n"]
    lines.extend(_format_doc_line(i, d) for i, d in enumerate(shown))
    hidden = len(docs) - len(shown)
    if hidden > 0:
        lines.append(f"\n… и ещё {hidden}.")

    builder = InlineKeyboardBuilder()
    for i, d in enumerate(shown):
        title = d.get("title") or "Документ"
        button_text = title if len(title) <= 30 else title[:29] + "…"
        builder.button(text=f"📤 {button_text}", callback_data=DocSendCallback(idx=i).pack())
    builder.adjust(1)

    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=builder.as_markup())


@router.callback_query(DocSendCallback.filter())
async def handle_doc_send(callback: CallbackQuery, callback_data: DocSendCallback):
    """Присылает файл по нажатию «Прислать». `idx` разрешается через свежий
    `list_documents(callback.from_user.id)` — документ гарантированно
    принадлежит нажавшему (issue #370, фаза 4)."""
    user_id = callback.from_user.id
    docs = list_documents(user_id)

    if callback_data.idx < 0 or callback_data.idx >= len(docs):
        await callback.answer("Документ не найден — список мог измениться, открой /my_docs заново.", show_alert=True)
        return

    doc = docs[callback_data.idx]
    doc_id = doc["id"]
    title = doc.get("title") or "Документ"

    try:
        path = resolve_document_path(user_id, doc_id)
    except DocumentNotFoundError as e:
        logger.warning("handle_doc_send: %s", e)
        await callback.answer("Не нашёл файл на диске — сообщи разработчику.", show_alert=True)
        return

    await callback.answer()

    file = FSInputFile(path)
    is_image = path.suffix.lower() in _IMAGE_EXTENSIONS
    try:
        if is_image:
            await callback.message.answer_photo(photo=file, caption=title)
        else:
            await callback.message.answer_document(document=file, caption=title)
    except Exception:
        logger.exception("handle_doc_send: не удалось отправить документ %s пользователю %s", doc_id, user_id)
        await callback.message.answer("⚠️ Не удалось отправить файл. Попробуй ещё раз.")
