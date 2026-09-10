# telegram-bot/handlers/doc_upload.py
"""Handler for /doc command — user uploads medical documents to their KB."""

from __future__ import annotations

import asyncio
import hashlib
import html
import io
import json
import logging
import re
import tempfile
import time
from datetime import date
from pathlib import Path
from typing import Any, Optional

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from core.health.onboarding_lists import ALLERGY_KEYS, CONDITION_KEYS, onboarding_list
from database import SessionLocal
from database.crud import merge_onboarding_lists

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


def _has_content(extracted: dict) -> bool:
    """Есть ли что сохранять: числа ИЛИ аллергии ИЛИ диагнозы."""
    if not extracted:
        return False
    return bool(extracted.get("values") or extracted.get("allergies") or extracted.get("conditions"))


_STALE_PENDING_SECONDS = 24 * 3600


def _cleanup_stale_pending(user_id: int) -> None:
    """Удаляет зависшие `.pending_*` файлы старше 24ч (issue #441 п.7б).

    Если пайплайн упал где-то между записью `.pending_*` и подтверждением
    (docup_save/docup_cancel) — например, edit превью не удался и оба ретрая
    из `run_doc_pipeline` тоже упали — файл остаётся в uploads/ навсегда,
    ничем не отличаясь от настоящих сохранённых документов на диске. Чистим
    такие огрызки при каждом новом запуске пайплайна для этого юзера.
    """
    try:
        uploads = _uploads_dir(user_id)
        cutoff = time.time() - _STALE_PENDING_SECONDS
        for f in uploads.glob(".pending_*"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
            except OSError:
                continue
    except OSError:
        logger.debug("doc_upload: не удалось прибрать зависшие .pending_* для user %s", user_id)


def is_medical_document(router_result: Optional[dict]) -> bool:
    """LLM-роутер (core/llm/router.py) распознал фото/PDF как медицинский документ,
    достойный doc-пайплайна — issue #439/#441 (KapWelding-стиль: единая точка
    правды вместо трёх скопированных копий этой проверки в handlers/photo.py).

    Правило: в doc-пайплайн — всё `type == "medical"`, КРОМЕ упаковки лекарства
    (`subtype == "medication_package"` — там нужен агентский путь с уже
    прочитанным vision-текстом, а не разбор в blood_tests). Отсутствие subtype
    (LLM забыл его выставить) тоже считаем документом — doc-пайплайн сам
    покажет «ничего не нашёл» с опцией архивации, так что дефолт безопасен.
    """
    if not isinstance(router_result, dict) or router_result.get("type") != "medical":
        return False
    data = router_result.get("data")
    subtype = data.get("subtype") if isinstance(data, dict) else None
    return subtype != "medication_package"


def log_doc_routing_decision(router_result: Optional[dict], routed: bool) -> None:
    """Единая точка для лога `#439: type=... subtype=... → ...` (issue #441 п.8)."""
    router_type = router_result.get("type") if isinstance(router_result, dict) else None
    data = router_result.get("data") if isinstance(router_result, dict) else None
    router_subtype = data.get("subtype") if isinstance(data, dict) else None
    logger.info(
        "#439: type=%s subtype=%s → %s",
        router_type,
        router_subtype,
        "doc_pipeline" if routed else "stock fallback",
    )


def _read_existing_profile(user_id: int) -> dict[str, list[str]]:
    """Текущие аллергии/диагнозы юзера из onboarding_data (для превью-пометок)."""
    from database.crud import get_user_by_telegram_id

    db = SessionLocal()
    try:
        user = get_user_by_telegram_id(db, user_id)
        onboarding = (user.onboarding_data or {}) if user else {}
        return {
            "allergies": onboarding_list(onboarding, ALLERGY_KEYS),
            "chronic_conditions": onboarding_list(onboarding, CONDITION_KEYS),
        }
    finally:
        db.close()


def _preview_text(extracted: dict[str, Any], existing: Optional[dict] = None) -> str:
    """Форматирует превью найденных данных. existing — текущий onboarding_data юзера
    (для пометки «новое» vs «уже в профиле»)."""
    existing = existing or {}
    existing_allergies = {s.lower() for s in onboarding_list(existing, ALLERGY_KEYS)}
    existing_conditions = {s.lower() for s in onboarding_list(existing, CONDITION_KEYS)}

    if not _has_content(extracted):
        return (
            "⚠️ Не нашёл данных для сохранения в документе.\n\n"
            "Это всё равно можно сохранить как архив — "
            "запомню что такой документ есть, и смогу перечитать его при разговоре."
        )

    lines: list[str] = ["📋 <b>Нашёл в документе:</b>"]

    # Issue #441 п.2: значения из extracted приходят из LLM-экстрактора и могут
    # содержать «<», «>», «&» (например «< 0.5» — часто встречается в лабораторных
    # бланках у показателей ниже порога чувствительности метода). Без экранирования
    # это ломает Telegram HTML-парсинг (TelegramBadRequest) и превью не показывается
    # вообще — экранируем каждую подставляемую динамическую строку.
    def _esc(value: Any) -> str:
        return html.escape(str(value), quote=False)

    doc_date = extracted.get("date")
    if doc_date:
        lines.append(f"• <b>Дата:</b> {_esc(doc_date)}")
    lab = extracted.get("laboratory")
    if lab:
        lines.append(f"• <b>Лаборатория:</b> {_esc(lab)}")

    doc_type = extracted.get("doc_type")
    if doc_type:
        lines.append(f"• <b>Тип:</b> {_esc(doc_type)}")

    values = extracted.get("values") or {}
    for key, val in list(values.items())[:15]:
        lines.append(f"• {_esc(key)}: {_esc(str(val)[:50])}")
    if len(values) > 15:
        lines.append(f"  <i>...и ещё {len(values) - 15} показателей</i>")

    def _mark(item: str, existing_set: set) -> str:
        marker = "✓ уже в профиле" if item.lower() in existing_set else "🆕"
        return f"• {_esc(item)} — {marker}"

    allergies = extracted.get("allergies") or []
    if allergies:
        lines.append("\n🤧 <b>Аллергии:</b>")
        lines.extend(_mark(a, existing_allergies) for a in allergies)

    conditions = extracted.get("conditions") or []
    if conditions:
        lines.append("\n🩺 <b>Диагнозы:</b>")
        lines.extend(_mark(c, existing_conditions) for c in conditions)

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


def append_document_to_kb(user_id: int, entry: dict[str, Any]) -> None:
    """Атомарная запись записи в documents[] в kb_<user_id>.json."""
    kb_path = _PROJECT_ROOT / "data" / "kb" / f"kb_{user_id}.json"
    kb_path.parent.mkdir(parents=True, exist_ok=True)

    if kb_path.exists():
        try:
            kb = json.loads(kb_path.read_text(encoding="utf-8"))
        except Exception:
            kb = {}
    else:
        kb = {}

    if not isinstance(kb.get("documents"), list):
        kb["documents"] = []
    kb["documents"].append(entry)

    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=kb_path.parent,
        suffix=".tmp",
        delete=False,
    )
    try:
        json.dump(kb, tmp, ensure_ascii=False, indent=2)
        tmp.flush()
        tmp.close()
        Path(tmp.name).replace(kb_path)
    except Exception:
        Path(tmp.name).unlink(missing_ok=True)
        raise


# Что сказать пользователю, когда лабораторной строки из документа не вышло.
# Документ при этом всё равно сохранён в documents[] — молчать нельзя, но и
# «сохранено» без оговорки вводило бы в заблуждение (данных в динамике нет).
_NO_ROW_NOTES = {
    "no_values": "\n📊 Числовых показателей не нашёл — документ лежит в карте здоровья.",
    "not_lab": "\n📊 Лабораторных показателей не нашёл — документ лежит в карте здоровья.",
    "no_date": "\n📊 Дату в документе не распознал — показатели не попали в динамику.",
}

# Ключ из "unknown key 'BandCells': not in canonical registry, skipped"
# (см. core.health.kb_schema.to_canonical) — вытаскиваем имя для пользователя.
_UNKNOWN_KEY_RE = re.compile(r"unknown key '(?P<key>[^']+)'")


def _unmapped_keys_note(warnings: tuple[str, ...]) -> str:
    """Строка-приписка со списком нераспознанных показателей (issue #445).

    Не блокирует сохранение — показатели всё равно лежат в документе, просто не
    попали в динамику (blood_tests хранит только канонические ключи).
    """
    keys = [m.group("key") for w in warnings if (m := _UNKNOWN_KEY_RE.search(w))]
    if not keys:
        return ""
    return f"\n⚠️ Не распознал: {', '.join(keys)} (сохранены в документе, но не попали в динамику)."


def _save_to_blood_tests(user_id: int, extracted: dict[str, Any], stored_name: str) -> str:
    """Пишет лабораторные показатели документа в Postgres blood_tests.

    Без этого загруженный через /doc анализ не виден ни дашборду, ни /phenoage,
    ни агенту (все читают blood_tests, а не documents[]) — issue #281.

    Возвращает строку-приписку к ответу пользователю. Исключения не выпускает:
    документ к этому моменту уже сохранён в KB, и падение БД не должно выглядеть
    как несохранённый документ.
    """
    from core.health.doc_to_blood_test import build_blood_test_row
    from database.crud import upsert_blood_test

    result = build_blood_test_row(extracted, stored_name=stored_name, user_id=user_id)
    for warning in result.warnings:
        logger.info("doc_upload: user %s — %s", user_id, warning)
    unmapped_note = _unmapped_keys_note(result.warnings)

    if result.row is None:
        return _NO_ROW_NOTES.get(result.reason, "") + unmapped_note

    db = SessionLocal()
    try:
        created = upsert_blood_test(db, result.row)
    except Exception:
        logger.exception("doc_upload: запись в blood_tests не удалась (user %s)", user_id)
        return "\n⚠️ Показатели не попали в динамику — ошибка записи в базу."
    finally:
        db.close()

    verb = "Добавил" if created else "Обновил"
    note = f"\n📊 {verb} в динамику показателей: {result.marker_count} (дата анализа: {result.row['test_date']})."
    return note + unmapped_note


def archive_photo_as_document(user_id: int, photo_path: Path, reason: str = "") -> str:
    """Сохраняет уже скачанное фото как документ профиля без парсинга.

    Для случаев когда LLM-vision не распознал фото ни как еду/вес/добавки/АД,
    и пользователь не через /doc его прислал — раньше файл просто терялся,
    а BotkinClaw мог только посоветовать /doc (issue #370). Теперь фото
    архивируется сразу, без дополнительного действия пользователя.

    Возвращает stored_name сохранённого файла.
    """
    content = photo_path.read_bytes()
    ext = photo_path.suffix or ".jpg"
    stored_name = _stored_name(content, ext)
    final_path = _uploads_dir(user_id) / stored_name
    final_path.write_bytes(content)

    entry: dict[str, Any] = {
        "added_at": date.today().isoformat(),
        "file": stored_name,
        "extracted": {},
        "user_confirmed": False,
        "auto_archived": True,
    }
    if reason:
        entry["reason"] = reason
    append_document_to_kb(user_id, entry)
    return stored_name


async def run_doc_pipeline(
    message: Message,
    state: FSMContext,
    *,
    content: bytes,
    ext: str,
    is_pdf: bool,
    intro: Optional[str] = None,
    processing_msg: Optional[Message] = None,
    auto: bool = False,
    question: Optional[str] = None,
) -> None:
    """Общее ядро doc-пайплайна: pending-файл → экстракция → превью с клавиатурой.

    Вынесено из `doc_received` (issue #439), чтобы им мог пользоваться не только
    /doc, но и авто-детект медицинских документов без команды в `handlers/photo.py`
    (фото анализа без /doc, текстовый PDF с лабораторными маркерами). Существующие
    callbacks `docup_save`/`docup_cancel` работают с результатом без изменений —
    они читают `pending` из FSM-данных, а не знают, кто их туда положил.

    `content`/`ext`/`is_pdf` — уже скачанный файл (скачивание остаётся на вызывающей
    стороне, у разных источников — Telegram document/photo — разная механика).
    `intro` — текст сообщения «читаю…», можно кастомизировать для авто-детекта,
    чтобы пользователь понимал, почему бот вдруг завёл /doc-подобный диалог.
    `processing_msg` — уже показанное пользователю сообщение («Идёт ИИ-анализ…» и
    т.п.), которое нужно переиспользовать (edit) вместо отправки второго сообщения
    (issue #439: авто-детект без подписи из `process_photos_list` уже показал
    «📸 Получено...» — без этого пользователь видел бы два сообщения подряд).
    Если не передан — ведёт себя как раньше, отправляет новое сообщение.
    `auto` — документ пришёл не через /doc, а через авто-детект (issue #441 п.1):
    пользователь никогда явно не соглашался на doc-режим, поэтому после
    save/cancel состояние ЗАКРЫВАЕТСЯ (`state.clear()`), а не остаётся в
    `DocUpload.waiting` — иначе следующее фото еды или текстовое сообщение
    попадало бы в doc-обработчики (`doc_received`/`doc_wrong_content`) вместо
    своего обычного маршрута, и пользователь застревал молча.
    `question` — вопрос к документу, переданный явным текстом/голосом
    (issue #441 п.6, напр. из `handle_description`), а не через caption
    сообщения с файлом. Если не передан — берём `message.caption`, как раньше.
    """
    from core.health.doc_extractor import extract_medical_data
    from handlers.photo import _extract_pdf_text, _pdf_to_images

    user_id = message.from_user.id
    _cleanup_stale_pending(user_id)
    if processing_msg is not None:
        try:
            await processing_msg.edit_text(intro or "⏳ Читаю…")
        except Exception:
            logger.debug("run_doc_pipeline: не удалось отредактировать processing_msg, отправляю новое")
            processing_msg = None
    if processing_msg is not None:
        processing = processing_msg
    else:
        processing = await message.answer(intro or "⏳ Читаю…")

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

    caption = (getattr(message, "caption", None) or "").strip()
    effective_question = (question or caption or "").strip()
    pending: dict[str, Any] = {
        "tmp_path": str(tmp_path),
        "stored_name": stored_name,
        "extracted": extracted,
        "auto": auto,
    }
    if effective_question:
        pending["caption"] = effective_question

    await state.set_state(DocUpload.waiting)
    await state.update_data(pending=pending)

    existing = _read_existing_profile(user_id)
    preview = _preview_text(extracted, existing)
    if effective_question:
        preview += "\n\n❓ Отвечу на твой вопрос после сохранения."
    keyboard = _preview_keyboard(_has_content(extracted))

    # Issue #441 п.2: extracted-значения экранированы в _preview_text, но
    # Telegram HTML-парсер капризный (например к незакрытым тегам от «<» в
    # значениях, которые не удалось экранировать полностью) — ретраим один
    # раз без parse_mode вместо падения с TelegramBadRequest. Если и это не
    # получилось — пользователь не должен зависнуть в DocUpload.waiting без
    # клавиатуры (issue #441 п.1): чистим state и .pending-файл и пробрасываем
    # исключение выше (вызывающий код это залогирует).
    try:
        await processing.edit_text(preview, reply_markup=keyboard, parse_mode="HTML")
    except TelegramBadRequest:
        logger.warning(
            "run_doc_pipeline: HTML-превью не прошло парсинг Telegram, ретраю без parse_mode (user %s)", user_id
        )
        try:
            await processing.edit_text(preview, reply_markup=keyboard, parse_mode=None)
        except Exception:
            logger.exception("run_doc_pipeline: не удалось показать превью документа даже без HTML (user %s)", user_id)
            await state.clear()
            tmp_path.unlink(missing_ok=True)
            raise
    except Exception:
        logger.exception("run_doc_pipeline: не удалось показать превью документа (user %s)", user_id)
        await state.clear()
        tmp_path.unlink(missing_ok=True)
        raise


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
async def doc_received(message: Message, state: FSMContext, album: list = None) -> None:
    """Обрабатывает входящий файл в режиме /doc. Тонкая обёртка над
    `run_doc_pipeline` — тут только определение типа файла и скачивание."""

    # Альбом (несколько файлов одним сообщением) — пока не поддерживаем батч-обработку
    # в /doc (FSM-state pending хранит один файл). Просим прислать по одному, вместо
    # того чтобы молча обработать только первый файл и потерять остальные.
    if album and len(album) > 1:
        await message.answer(
            "📎 Пришли, пожалуйста, документы по одному — так надёжнее, я смогу их правильно распознать."
        )
        return

    user_id = message.from_user.id

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

    try:
        tg_file = await message.bot.get_file(file_id)
        buf = io.BytesIO()
        await message.bot.download_file(tg_file.file_path, buf)
        content = buf.getvalue()
    except Exception:
        logger.exception("doc_upload: не удалось скачать файл от %s", user_id)
        await message.answer("⚠️ Не удалось скачать файл. Попробуй ещё раз.")
        return

    await run_doc_pipeline(message, state, content=content, ext=ext, is_pdf=is_pdf)


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
    # Issue #441 п.1: документ, попавший в пайплайн через авто-детект (не /doc),
    # никогда явно не запрашивался пользователем — после save/cancel закрываем
    # FSM полностью, иначе следующее фото еды или текст попадают в doc-обработчики
    # (doc_received/doc_wrong_content) и пользователь молча застревает.
    is_auto = bool(pending.get("auto"))

    if callback.data == "docup_cancel":
        if is_auto:
            # Issue #441 п.7а: авто-детект отменили — файл НЕ удаляем молча.
            # Гарантия issue #370 («фото/документ никогда просто не исчезает»)
            # распространяется и на отмену: архивируем как auto_archived,
            # user_confirmed=False, с явной причиной отмены.
            final_path = _uploads_dir(user_id) / pending["stored_name"]
            try:
                if tmp_path.exists():
                    tmp_path.replace(final_path)
                entry = {
                    "added_at": date.today().isoformat(),
                    "file": pending["stored_name"],
                    "extracted": pending.get("extracted") or {},
                    "user_confirmed": False,
                    "auto_archived": True,
                    "reason": "пользователь отменил разбор",
                }
                append_document_to_kb(user_id, entry)
            except Exception:
                logger.exception("doc_upload: архивация отменённого авто-документа не удалась (user %s)", user_id)
            close_text = "❌ Показатели не сохранил, сам файл оставил в архиве документов."
        else:
            # /doc — пользователь сам явно вошёл в режим загрузки, тут отмена
            # действительно значит «выбросить», как и раньше.
            tmp_path.unlink(missing_ok=True)
            close_text = "❌ Не сохранил. Пришли другой документ или /cancel."

        if is_auto:
            await state.clear()
        else:
            await state.update_data(pending=None)
        await callback.message.edit_text(close_text)
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
        append_document_to_kb(user_id, entry)
    except Exception:
        logger.exception("doc_upload: сохранение не удалось (user %s)", user_id)
        await callback.message.edit_text("⚠️ Не получилось сохранить, попробуй ещё раз.")
        await callback.answer()
        return

    extracted = pending.get("extracted") or {}
    biomarkers_note = _save_to_blood_tests(user_id, extracted, pending["stored_name"])
    profile_note = ""
    if extracted.get("allergies") or extracted.get("conditions"):
        db = SessionLocal()
        try:
            counts = merge_onboarding_lists(
                db,
                user_id,
                {
                    "allergies": extracted.get("allergies") or [],
                    "chronic_conditions": extracted.get("conditions") or [],
                },
            )
        except Exception:
            logger.exception("doc_upload: merge onboarding не удался (user %s)", user_id)
            profile_note = "\n⚠️ Документ сохранён, но профиль обновить не удалось — попробуй ещё раз."
            counts = None
        finally:
            db.close()
        if counts is not None:
            n_a, n_c = counts.get("allergies", 0), counts.get("chronic_conditions", 0)
            if n_a or n_c:
                profile_note = f"\nВ профиль добавлено: аллергии +{n_a}, диагнозы +{n_c}."
            else:
                profile_note = "\nНового в профиль не добавил (всё уже было)."

    caption_question = (pending.get("caption") or "").strip()

    close_text = "✅ Сохранено в твою базу здоровья." + biomarkers_note + profile_note
    if is_auto:
        # Issue #441 п.1: авто-документ — закрываем FSM, «Пришли другой документ
        # или /cancel» тут вводило бы в заблуждение (мы не в /doc-режиме).
        await state.clear()
    else:
        await state.update_data(pending=None)
        close_text += "\n\nМожешь прислать ещё документ или /cancel."
    await callback.message.edit_text(close_text, parse_mode="HTML")
    await callback.answer("Сохранено")

    # Issue #439 п.4: если к документу была подпись-вопрос — отвечаем на неё
    # ПОСЛЕ сохранения (см. пометку в превью из run_doc_pipeline), чтобы не
    # терять диалог, ради которого пользователь и прислал документ.
    if caption_question:
        from core.agent_chat import ask_agent
        from core.tg_markdown import md_to_html

        loop = asyncio.get_event_loop()
        try:
            reply = await loop.run_in_executor(None, lambda: ask_agent(int(user_id), caption_question))
        except Exception:
            logger.exception("doc_upload: не удалось ответить на вопрос из подписи (user %s)", user_id)
            reply = None
        if reply:
            try:
                await callback.message.answer(md_to_html(reply), parse_mode="HTML")
            except Exception:
                await callback.message.answer(reply)


@router.message(DocUpload.waiting)
async def doc_wrong_content(message: Message) -> None:
    """Напоминание если прислали не файл в режиме /doc."""
    await message.answer("Жду PDF, фото или скан документа. Выйти — /cancel.")
