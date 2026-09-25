# telegram-bot/handlers/doc_upload.py
"""Handler for /doc command — user uploads medical documents to their KB."""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import re
import tempfile
import time
from datetime import date
from pathlib import Path
from typing import Any, Optional

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
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
from handlers import doc_dedup
from handlers.doc_queue import (
    archive_leftover_documents,
    archive_single_file,
    empty_gather_header,
    finish_step_or_advance,
    format_progress_prefix,
    format_skip_summary,
    gather_source_files,
    pluralize_docs,
    pop_next_loadable,
    queue_lock,
    stage_queue_item,
)

logger = logging.getLogger(__name__)

router = Router()

# Корень проекта — два уровня выше telegram-bot/handlers/
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_UPLOADS_DIR = _PROJECT_ROOT / "data" / "uploads"


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
    """Есть ли что сохранять: числа, аллергии, диагнозы или текстовое резюме (#558)."""
    if not extracted:
        return False
    return bool(
        extracted.get("values")
        or extracted.get("series")
        or extracted.get("allergies")
        or extracted.get("conditions")
        or extracted.get("summary")
    )


_STALE_PENDING_SECONDS = 24 * 3600
# Страниц текстового PDF для разбора: досье бывает на 15+ страниц (#559), а
# больше 40 — уже не медицинский документ, а книга.
_MAX_PDF_PAGES = 40
_PREVIEW_SERIES_DATES = 6


async def _cleanup_stale_pending(user_id: int, state: Optional[FSMContext] = None) -> None:
    """Архивирует (не удаляет!) зависшие `.pending_*`/`.queued_*` файлы старше
    24ч (issue #441 п.7б, расширено issue #499 для файлов очереди).

    Раньше сторож УДАЛЯЛ такие файлы (`f.unlink`) — это нарушало гарантию
    issue #370 «документ никогда просто не исчезает»: если пайплайн упал
    где-то между записью `.pending_*`/`.queued_*` и подтверждением, или бот
    перезапустился посреди разбора пачки (FSM в MemoryStorage теряется целиком
    при рестарте), документ исчезал безвозвратно через сутки, минуя KB
    (issue #516).

    Теперь такие файлы переносятся в архив тем же способом, что
    `archive_leftover_documents` при явном `/cancel` (`archive_single_file`),
    и попадают в KB как `auto_archived` с причиной «не дождался разбора».
    Чистим такие огрызки при каждом новом запуске пайплайна для этого юзера —
    поэтому сама проверка (`glob` по паттерну + `stat`) должна оставаться
    дешёвой, а архивация — не падать наружу, если KB недоступна
    (`archive_single_file` логирует сбой записи в KB, но не роняет пайплайн).

    Issue #516 доп. (дефект Б, независимый ревьюер): бот НЕ обязательно
    рестартовал — пользователь мог просто вернуться к живой очереди на
    следующий день (MemoryStorage жив, старше 24ч бывает и у живой сессии,
    например ZIP из 5 файлов, разобрали 2 вечером, продолжили на следующий).
    Файлы, на которые ссылается ТЕКУЩЕЕ FSM-состояние этого пользователя
    (`pending.tmp_path` и `tmp_path` элементов `queue`), не трогаем — иначе
    следующий `docup_save`/`docup_cancel` упадёт в `load_staged_item` на
    пропавшем файле. `state` передаётся из `run_doc_pipeline`, где он всегда
    есть; без него (гипотетический вызов без FSM) защиты нет — но такого
    вызывающего кода в проекте нет.
    """
    protected_names: set[str] = set()
    if state is not None:
        try:
            data = await state.get_data()
        except Exception:
            data = None
        # Не доверяем форме данных, которые вернуло FSM (в тестах `state`
        # часто — облегчённый мок без честного get_data; в проде это всегда
        # обычный dict, но защититься дешевле, чем упасть на .get() чужого
        # типа): не dict — считаем, что защищать нечего.
        if not isinstance(data, dict):
            data = {}
        pending = data.get("pending")
        if isinstance(pending, dict):
            pending_tmp = pending.get("tmp_path")
            if pending_tmp:
                protected_names.add(Path(pending_tmp).name)
        for staged in data.get("queue") or []:
            if not isinstance(staged, dict):
                continue
            staged_tmp = staged.get("tmp_path")
            if staged_tmp:
                protected_names.add(Path(staged_tmp).name)

    try:
        uploads = _uploads_dir(user_id)
        cutoff = time.time() - _STALE_PENDING_SECONDS
        for pattern in (".pending_*", ".queued_*"):
            for f in uploads.glob(pattern):
                if f.name in protected_names:
                    continue
                try:
                    if f.stat().st_mtime < cutoff:
                        archive_single_file(user_id, f, reason="не дождался разбора")
                except OSError:
                    continue
    except OSError:
        logger.debug("doc_upload: не удалось прибрать зависшие .pending_*/.queued_* для user %s", user_id)


# Issue #516: 429 от Telegram (TelegramRetryAfter) не фатален. Очередь из
# #499 делает несколько edit_text/answer подряд (закрыть предыдущий шаг →
# показать «читаю» → показать превью) — реалистичный триггер флуд-контроля.
# Потолок на попытки и на время ожидания, чтобы не повиснуть навсегда, если
# Telegram вдруг попросит подождать несколько часов.
_MAX_RETRY_AFTER_ATTEMPTS = 3
_MAX_RETRY_AFTER_WAIT_SECONDS = 30


async def _call_with_flood_retry(coro_factory, *, user_id: int, what: str):
    """Вызывает `coro_factory()` (awaitable Telegram-вызов), при
    `TelegramRetryAfter` ждёт `retry_after` (не дольше потолка) и повторяет —
    issue #516. Не глушит другие исключения (TelegramBadRequest и прочее
    обрабатывает вызывающий код, как и раньше)."""
    attempt = 0
    while True:
        try:
            return await coro_factory()
        except TelegramRetryAfter as e:
            attempt += 1
            if attempt > _MAX_RETRY_AFTER_ATTEMPTS:
                logger.warning(
                    "run_doc_pipeline: %s — исчерпаны попытки после 429 (user %s, retry_after=%s)",
                    what,
                    user_id,
                    e.retry_after,
                )
                raise
            wait = min(e.retry_after, _MAX_RETRY_AFTER_WAIT_SECONDS)
            logger.info(
                "run_doc_pipeline: %s — 429 от Telegram, жду %.1fс и повторяю (попытка %d/%d, user %s)",
                what,
                wait,
                attempt,
                _MAX_RETRY_AFTER_ATTEMPTS,
                user_id,
            )
            await asyncio.sleep(wait)


async def _archive_failed_preview(user_id: int, state: FSMContext, message: Message) -> None:
    """Issue #516: показ превью документа не удался даже после ретраев на
    429. Раньше это стирало всё FSM-состояние (`state.clear()`) и удаляло
    текущий файл (`tmp_path.unlink()`) — хвост очереди (`.queued_*` на диске)
    оставался без ссылок в FSM и исчезал через сутки мимо KB, а текущий файл
    пропадал сразу. Нарушает гарантию issue #370.

    Вместо этого — архивируем текущий pending и весь хвост очереди тем же
    способом, что явный `/cancel` (`archive_leftover_documents`), и сообщаем
    пользователю спокойным текстом, что документы сохранены в архив, но
    разобрать их сейчас не получилось. FSM всё равно закрывается — issue
    #441 п.1 остаётся в силе: пользователь не должен зависнуть в
    `DocUpload.waiting` без клавиатуры.
    """
    try:
        data = await state.get_data()
    except Exception:
        logger.exception("run_doc_pipeline: не удалось прочитать FSM-состояние после сбоя превью (user %s)", user_id)
        data = {}

    archived = archive_leftover_documents(user_id, data)
    await state.clear()

    text = "⚠️ Не получилось показать, что нашёл в документе — Telegram не принял сообщение."
    if archived:
        word = "документ" if archived == 1 else "документа" if 2 <= archived <= 4 else "документов"
        text += (
            f"\n\nНичего не потерялось: сохранил как есть в архив ({archived} {word}) — "
            "просто не успел показать разбор. Если нужно — пришли документ ещё раз."
        )
    else:
        text += "\n\nК сожалению, файл не сохранился — пришли его ещё раз, пожалуйста."

    try:
        await message.answer(text)
    except Exception:
        logger.exception("run_doc_pipeline: не удалось сообщить пользователю о сбое превью (user %s)", user_id)


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
        if extracted and (extracted.get("_unverified_labels") or extracted.get("_unreadable_text")):
            # Issue #509: LLM что-то нашёл, но не смог надёжно прочитать названия
            # показателей (сверка с текстом документа не подтвердила ни одного) —
            # честно говорим про плохое качество текста, а не молчим о том, что
            # цифры вообще-то были.
            return (
                "⚠️ Текст документа читается плохо — не смог достоверно определить "
                "названия показателей, поэтому не показываю и не сохраняю их в базу "
                "(могу перепутать анализ с другим).\n\n"
                "Сам документ всё равно можно сохранить как архив — "
                "запомню что он есть, и смогу перечитать его при разговоре."
            )
        return (
            "⚠️ Не нашёл данных для сохранения в документе.\n\n"
            "Это всё равно можно сохранить как архив — "
            "запомню что такой документ есть, и смогу перечитать его при разговоре."
        )

    lines: list[str] = ["📋 <b>Нашёл в документе:</b>"]
    failed = extracted.get("_chunks_failed")
    if failed:
        # Часть длинного документа не разобралась (обрыв, тайм-аут) — без пометки
        # превью выглядело бы полным, а хвост дат молча пропал бы (ревью #564).
        total = extracted.get("_chunks_total") or "?"
        lines.insert(
            0,
            f"⚠️ Не получилось разобрать {failed} из {total} частей документа — часть дат может "
            "не попасть в динамику. Можно сохранить то, что есть, или прислать документ ещё раз.\n",
        )

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

    summary = extracted.get("summary")
    if summary:
        lines.append(f"• <b>Кратко:</b> {_esc(str(summary)[:600])}")

    series = [e for e in extracted.get("series") or [] if isinstance(e, dict)]
    if series:
        # Сводная таблица (#559): строка на дату, свежие сверху — все значения
        # 13 дат по 6 показателей в превью не поместить и не прочитать.
        n = len(series)
        lines.append(
            f"• <b>Сводная таблица:</b> {n} {_plural_dates(n)}, {_esc(series[0]['date'])} — {_esc(series[-1]['date'])}"
        )
        for entry in list(reversed(series))[:_PREVIEW_SERIES_DATES]:
            vals = ", ".join(f"{k} {v}" for k, v in (entry.get("values") or {}).items())
            if len(vals) > 90:
                vals = vals[:90].rsplit(",", 1)[0] + ", …"
            lines.append(f"  {_esc(entry['date'])}: {_esc(vals)}")
        if n > _PREVIEW_SERIES_DATES:
            lines.append(f"  <i>...и ещё {n - _PREVIEW_SERIES_DATES} {_plural_dates(n - _PREVIEW_SERIES_DATES)}</i>")

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


def _duplicate_note(user_id: int, extracted: dict[str, Any]) -> str:
    """Строка-предупреждение, если в KB уже есть документ с тем же содержимым (#558).

    Ловит повторную фотографию того же бланка (байты другие — `doc_dedup` не видит).
    Ошибки чтения KB не мешают показу превью.
    """
    from core.health.doc_duplicates import find_similar_document

    kb_path = _PROJECT_ROOT / "data" / "kb" / f"kb_{user_id}.json"
    try:
        documents = json.loads(kb_path.read_text(encoding="utf-8")).get("documents") or []
    except Exception:
        return ""
    match = find_similar_document(documents, extracted)
    if match is None:
        return ""
    old = match.get("extracted") or {}
    name = match.get("title") or old.get("doc_type") or old.get("laboratory") or "документ"
    when = old.get("date") or match.get("added_at")
    label = f"{name} ({when})" if when else str(name)
    return (
        f"⚠️ Похоже, этот документ уже сохранён: {html.escape(label, quote=False)}. "
        "Если это та же страница — нажми «Отмена»."
    )


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
# Кавычки из repr() — обычно одинарные, но python переключается на двойные,
# если сама строка содержит апостроф (repr("it's") == '"it\'s"') — матчим оба варианта.
_UNKNOWN_KEY_RE = re.compile(r"unknown key [\"'](?P<key>.+?)[\"']:")


def _unmapped_keys_note(warnings: tuple[str, ...]) -> str:
    """Строка-приписка со списком нераспознанных показателей (issue #445).

    Не блокирует сохранение — показатели всё равно лежат в документе, просто не
    попали в динамику (blood_tests хранит только канонические ключи).
    """
    # dict.fromkeys: у сводной таблицы (#559) тот же ключ приходит за каждую дату.
    keys = list(dict.fromkeys(m.group("key") for w in warnings if (m := _UNKNOWN_KEY_RE.search(w))))
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
    from core.health.doc_to_blood_test import build_blood_test_rows
    from database.crud import upsert_blood_test

    result = build_blood_test_rows(extracted, stored_name=stored_name, user_id=user_id)
    for warning in result.warnings:
        logger.info("doc_upload: user %s — %s", user_id, warning)
    unmapped_note = _unmapped_keys_note(result.warnings)

    if not result.rows:
        if result.reason == "no_values" and (extracted.get("_unverified_labels") or extracted.get("_unreadable_text")):
            # Issue #509: значения были, но ни одно название не подтвердилось
            # текстом документа (doc_extractor их уже отбросил) — отдельная,
            # более честная формулировка вместо общего «не нашёл показателей».
            return (
                "\n📊 Текст документа читается плохо — названия показателей не "
                "подтвердились, в динамику ничего не записал (документ остался в архиве)."
            )
        note = _NO_ROW_NOTES.get(result.reason, "")
        # reason="not_lab": НИ ОДИН сырой ключ не распознан как лабораторный маркер
        # (типичный случай — УЗИ с размерами органов, это не наш стол вообще).
        # Приписывать «не распознал: liver_size, spleen_size» здесь означало бы
        # выдавать ожидаемое поведение за сбой — тот же список ключей, что и
        # «не нашёл лабораторных показателей» выше, только звучит как ошибка.
        if result.reason != "not_lab":
            note += unmapped_note
        return note

    db = SessionLocal()
    try:
        created = [upsert_blood_test(db, row) for row in result.rows]
    except Exception:
        logger.exception("doc_upload: запись в blood_tests не удалась (user %s)", user_id)
        return "\n⚠️ Показатели не попали в динамику — ошибка записи в базу."
    finally:
        db.close()

    verb = "Добавил" if any(created) else "Обновил"
    dates = sorted(row["test_date"] for row in result.rows)
    if len(dates) == 1:
        when = f"дата анализа: {dates[0]}"
    else:
        when = f"{len(dates)} {_plural_dates(len(dates))}: {dates[0]} — {dates[-1]}"
    note = f"\n📊 {verb} в динамику показателей: {result.marker_count} ({when})."
    return note + unmapped_note


def _plural_dates(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "дата"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "даты"
    return "дат"


def archive_photo_as_document(
    user_id: int,
    photo_path: Path,
    reason: str = "",
    *,
    title: Optional[str] = None,
    category: Optional[str] = None,
    saved_on_request: bool = False,
) -> str:
    """Сохраняет уже скачанное фото (или PDF — несмотря на имя, работает с
    любым расширением через `photo_path.suffix`) как документ профиля без
    парсинга.

    Для случаев когда LLM-vision не распознал фото ни как еду/вес/добавки/АД,
    и пользователь не через /doc его прислал — раньше файл просто терялся,
    а BotkinClaw мог только посоветовать /doc (issue #370). Теперь фото
    архивируется сразу, без дополнительного действия пользователя.

    `saved_on_request=True` (issue #370, фаза 3) — явная просьба пользователя
    «сохрани про запас» в подписи: `auto_archived=False`, `user_confirmed=True`,
    записывается `saved_on_request=True`; в этом случае обычно уже известны
    `title`/`category` (см. `core.health.profile_documents.parse_save_title`/
    `guess_category`) — они пишутся в запись, если переданы.

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
        "user_confirmed": bool(saved_on_request),
        "auto_archived": not saved_on_request,
    }
    if reason:
        entry["reason"] = reason
    if title:
        entry["title"] = title
    if category:
        entry["category"] = category
    if saved_on_request:
        entry["saved_on_request"] = True
    append_document_to_kb(user_id, entry)
    return stored_name


def save_files_on_request(user_id: int, file_paths: list[Path], caption: str) -> list[str]:
    """Сохраняет фото/PDF как документы профиля по явной просьбе пользователя
    в подписи («сохрани», «на всякий случай», «полис» и т.п. — issue #370,
    фаза 3). Title и category угадываются из подписи один раз для всей пачки
    (`core.health.profile_documents.parse_save_title`/`guess_category`) —
    альбом с одной подписью сохраняется целиком под этим title.

    Дедуп по содержимому через `handlers.doc_dedup` (тот же кэш, что и
    /doc-очередь): файл, уже отмеченный как `STATUS_SAVED`, пропускается —
    не сохраняем один и тот же файл дважды подряд.

    Возвращает список title фактически сохранённых файлов (пустой список —
    все файлы из `file_paths` уже были недавно сохранены, новых записей нет).
    """
    from core.health.profile_documents import guess_category, parse_save_title

    title = parse_save_title(caption)
    category = guess_category(caption)

    saved_titles: list[str] = []
    for path in file_paths:
        content = path.read_bytes()
        if doc_dedup.status(user_id, content) == doc_dedup.STATUS_SAVED:
            continue
        archive_photo_as_document(
            user_id,
            path,
            title=title,
            category=category,
            saved_on_request=True,
        )
        doc_dedup.mark_saved(user_id, content)
        saved_titles.append(title)
    return saved_titles


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
    user_id: Optional[int] = None,
    progress: Optional[tuple[int, int]] = None,
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
    `user_id` — переопределяет `message.from_user.id` (issue #499): при
    продолжении очереди из callback'а `docup_save`/`docup_cancel` роль
    `message` играет `callback.message` (нужен только для `.answer()`), а его
    `from_user` — это бот, а не пользователь.
    `progress` — (позиция, всего) для пометки «Документ N из M» в очереди
    из нескольких файлов (альбом/ZIP, issue #499). Одиночный файл — как
    раньше, без пометки.
    """
    from core.health.doc_extractor import extract_medical_data, extract_medical_data_from_pages, needs_chunking
    from handlers.photo import _extract_pdf_pages, _pdf_to_images

    user_id = user_id if user_id is not None else message.from_user.id
    await _cleanup_stale_pending(user_id, state)

    # Файл — на диск ДО любого сетевого вызова. При продолжении очереди
    # load_staged_item уже удалил `.queued_*`, и содержимое живёт только в
    # памяти: если бы первым шёл message.answer и он упал (429 после потолка
    # ретраев, сеть), документ исчез бы отовсюду — ни на диске, ни в очереди,
    # ни в pending (ревью координатора #516). Записанный `.pending_*` в худшем
    # случае подберёт сторож или архивация ниже.
    stored_name = _stored_name(content, ext)
    tmp_path = _uploads_dir(user_id) / f".pending_{stored_name}"
    tmp_path.write_bytes(content)

    if processing_msg is not None:
        try:
            await _call_with_flood_retry(
                lambda: processing_msg.edit_text(intro or "⏳ Читаю…"), user_id=user_id, what="intro"
            )
        except Exception:
            logger.debug("run_doc_pipeline: не удалось отредактировать processing_msg, отправляю новое")
            processing_msg = None
    if processing_msg is not None:
        processing = processing_msg
    else:
        try:
            processing = await _call_with_flood_retry(
                lambda: message.answer(intro or "⏳ Читаю…"), user_id=user_id, what="intro"
            )
        except Exception:
            logger.exception("run_doc_pipeline: не удалось отправить «читаю…» (user %s)", user_id)
            # Ставим текущий документ в pending, чтобы архивация его увидела:
            # на чистом старте здесь может лежать маркер {"claiming": True}.
            await state.update_data(
                pending={"tmp_path": str(tmp_path), "stored_name": stored_name, "extracted": {}, "auto": auto}
            )
            await _archive_failed_preview(user_id, state, message)
            raise

    # Извлекаем показатели
    loop = asyncio.get_event_loop()
    try:
        if is_pdf:
            # Сводное досье бывает на 15+ страниц (#559): прежние 10 страниц молча
            # теряли хвост, длинный текст экстрактор режет на части сам.
            pdf_pages = await loop.run_in_executor(None, lambda: _extract_pdf_pages(tmp_path, max_pages=_MAX_PDF_PAGES))
            if pdf_pages:
                if needs_chunking(pdf_pages):
                    # 15 страниц — это минуты, а не секунды: без пометки «Читаю…»
                    # выглядит зависшим.
                    try:
                        await processing.edit_text(
                            f"⏳ Длинный документ ({len(pdf_pages)} стр.) — разбираю по частям, это займёт пару минут…"
                        )
                    except Exception:
                        logger.debug("run_doc_pipeline: не удалось показать пометку о длинном документе")
                extracted = await extract_medical_data_from_pages(pdf_pages, user_id=user_id)
            else:
                # Сканированный PDF — берём первую страницу как изображение
                pages = await loop.run_in_executor(None, lambda: _pdf_to_images(tmp_path, max_pages=1))
                if pages:
                    extracted = await extract_medical_data(pages[0].read_bytes(), "image/jpeg", user_id=user_id)
                else:
                    extracted = {}
        else:
            media_type = "image/png" if ext == ".png" else "image/jpeg"
            extracted = await extract_medical_data(content, media_type, user_id=user_id)
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
    duplicate_note = _duplicate_note(user_id, extracted)
    if duplicate_note:
        preview = f"{duplicate_note}\n\n{preview}"
    if progress:
        pos, total = progress
        preview = f"{format_progress_prefix(pos, total)}\n\n{preview}"
    if effective_question:
        preview += "\n\n❓ Отвечу на твой вопрос после сохранения."
    keyboard = _preview_keyboard(_has_content(extracted))

    # Issue #441 п.2: extracted-значения экранированы в _preview_text, но
    # Telegram HTML-парсер капризный (например к незакрытым тегам от «<» в
    # значениях, которые не удалось экранировать полностью) — ретраим один
    # раз без parse_mode вместо падения с TelegramBadRequest.
    #
    # Issue #516: TelegramRetryAfter (429 — самый частый триггер в очереди из
    # #499, где несколько edit_text/answer идут подряд) обрабатывается
    # ожиданием и повтором (`_call_with_flood_retry`), а не как фатальный сбой.
    #
    # Если превью так и не удалось показать (ни с HTML, ни без, ни после
    # ретраев на 429) — пользователь не должен зависнуть в DocUpload.waiting
    # без клавиатуры (issue #441 п.1). Раньше это стирало state и удаляло
    # .pending-файл; теперь текущий документ и хвост очереди архивируются
    # (issue #516, гарантия issue #370 — файл никогда просто не исчезает).
    try:
        await _call_with_flood_retry(
            lambda: processing.edit_text(preview, reply_markup=keyboard, parse_mode="HTML"),
            user_id=user_id,
            what="preview",
        )
    except TelegramBadRequest:
        logger.warning(
            "run_doc_pipeline: HTML-превью не прошло парсинг Telegram, ретраю без parse_mode (user %s)", user_id
        )
        try:
            await _call_with_flood_retry(
                lambda: processing.edit_text(preview, reply_markup=keyboard, parse_mode=None),
                user_id=user_id,
                what="preview-no-html",
            )
        except Exception:
            logger.exception("run_doc_pipeline: не удалось показать превью документа даже без HTML (user %s)", user_id)
            await _archive_failed_preview(user_id, state, message)
            raise
    except Exception:
        logger.exception("run_doc_pipeline: не удалось показать превью документа (user %s)", user_id)
        await _archive_failed_preview(user_id, state, message)
        raise


@router.message(Command("doc"))
async def cmd_doc(message: Message, state: FSMContext) -> None:
    """/doc — начать загрузку медицинского документа."""
    await state.set_state(DocUpload.waiting)
    await message.answer(
        "📄 Пришли PDF, фото или скан анализа / заключения врача.\n\n"
        "Поддерживаются: PDF, JPG, PNG, HEIC, а также ZIP-архив или сразу "
        "несколько файлов — разберу по одному.\n"
        "Выйти из режима загрузки — /cancel.",
        parse_mode="HTML",
    )


@router.message(Command("cancel"), DocUpload.waiting)
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """Выход из режима загрузки по /cancel.

    issue #499: если пользователь выходит посреди разбора пачки — текущий
    документ и всё, что ещё ждало своей очереди, не пропадают молча (гарантия
    issue #370), а архивируются как есть.
    """
    user_id = message.from_user.id
    data = await state.get_data()
    archived = archive_leftover_documents(user_id, data)
    await state.clear()

    text = "Вышел из режима загрузки документов."
    if archived:
        word = "документ" if archived == 1 else "документа" if 2 <= archived <= 4 else "документов"
        text += f"\n\nНе разобранные файлы ({archived} {word}) сохранил как есть в архив — просто не распознавал."
    await message.answer(text)


@router.message(DocUpload.waiting, F.document | F.photo)
async def doc_received(message: Message, state: FSMContext, album: list = None) -> None:
    """Обрабатывает входящий файл (или несколько — альбом/ZIP) в режиме /doc.

    issue #499: раньше альбом из нескольких файлов отбивался целиком, а ZIP
    (так Windows пакует группу файлов для пересылки) не распознавался вовсе.
    Теперь всё собирается в очередь и разбирается по одному, с прогрессом
    «документ N из M» — остальное берёт на себя `handlers.doc_queue`.
    """
    user_id = message.from_user.id
    sources = album if album else [message]

    gathered = await gather_source_files(user_id, sources)

    notes = list(gathered.archive_notes)
    skip_summary = format_skip_summary(gathered.skip_counts)
    if skip_summary:
        notes.append(skip_summary)

    if not gathered.items:
        # Issue #516 п.3: если все отсеянные файлы — по одной и той же
        # понятной причине (повтор, пароль), заголовок называет её прямо,
        # а не «не нашёл подходящего файла» — файлы были подходящего формата.
        text = empty_gather_header(gathered)
        if notes:
            text += "\n\n" + "\n".join(notes)
        await message.answer(text)
        return

    if notes:
        await message.answer("\n".join(notes))

    # Issue #516 доп. (дефект А, независимый ревьюер): webhook обрабатывает
    # апдейты параллельно, и Dispatcher не изолирует события одного
    # пользователя друг от друга. Раньше здесь БЕЗУСЛОВНО перезаписывалось
    # `queue`/`queue_total` — если пользователь уже смотрит документ 1 из
    # альбома (превью показано, ждёт «Сохранить/Отмена») и присылает ещё файл
    # (или альбом пришёл частями из-за задержки MediaGroupMiddleware), новая
    # запись стирала текущую очередь, и уже показанный документ и его хвост
    # переставали быть упомянуты где-либо в FSM. Теперь: если сессия уже
    # активна (есть pending или непустая очередь) — новые файлы ДОБАВЛЯЮТСЯ в
    # хвост, текущий pending не трогаем. Чтение+запись идёт под `queue_lock`
    # (общий per-user asyncio.Lock с `finish_step_or_advance`) — MemoryStorage
    # не даёт атомарного read-modify-write, а два конкурентных апдейта могут
    # одновременно делать get_data → update_data над одной и той же очередью.
    async with queue_lock(user_id):
        data = await state.get_data()
        existing_queue = data.get("queue") or []
        has_pending = bool(data.get("pending"))
        session_active = has_pending or bool(existing_queue)
        existing_total = (data.get("queue_total") or (len(existing_queue) + 1)) if session_active else 0

        staged_new = [stage_queue_item(user_id, item) for item in gathered.items]
        new_queue = existing_queue + staged_new
        new_total = existing_total + len(gathered.items)

        start_now = None
        if session_active:
            await state.update_data(queue=new_queue, queue_total=new_total)
        else:
            # Чистый старт (нет ни pending, ни очереди) — эта же горутина
            # забирает голову себе. Взятие головы + отметка `pending`
            # временным маркером происходят ВНУТРИ лока: конкурентный второй
            # вызов, попавший в лок следом, увидит `pending` уже занятым и
            # пойдёт по ветке добавления в хвост, а не запустит второй
            # параллельный run_doc_pipeline поверх той же головы очереди.
            loaded, skipped_labels, rest = pop_next_loadable(new_queue)
            if loaded is not None:
                await state.update_data(queue=rest, queue_total=new_total, pending={"claiming": True})
                start_now = (loaded, skipped_labels, rest)
            else:
                await state.update_data(queue=rest, queue_total=new_total)

    if session_active:
        word = pluralize_docs(len(gathered.items))
        await message.answer(
            f"➕ Добавил ещё {len(gathered.items)} {word} в очередь — дойдёт черёд, разберу по одному."
        )
        return

    if start_now is None:
        # Ни один из присланных файлов не прочитался обратно с диска —
        # не должно случаться в норме, но не молчим тишиной (issue #370).
        await message.answer("⚠️ Не получилось прочитать присланные файлы — попробуй прислать ещё раз.")
        return

    (content, ext, is_pdf, _label), skipped_labels, rest = start_now
    pos = new_total - len(rest)
    intro = None
    progress = None
    if new_total > 1:
        progress = (pos, new_total)
        intro = f"{format_progress_prefix(pos, new_total)} — читаю…"
    if skipped_labels:
        word = pluralize_docs(len(skipped_labels))
        await message.answer(f"⚠️ Пропустил {len(skipped_labels)} {word} — файл не прочитался с диска.")

    await run_doc_pipeline(
        message,
        state,
        content=content,
        ext=ext,
        is_pdf=is_pdf,
        intro=intro,
        progress=progress,
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
            # Issue #516: читаем содержимое ДО переноса файла, чтобы снять
            # отметку дедупликации («в обработке») — отменённый документ не
            # должен блокировать повторную отправку того же файла.
            content_for_dedup = tmp_path.read_bytes() if tmp_path.exists() else None
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
            if content_for_dedup is not None:
                doc_dedup.clear(user_id, content_for_dedup)
            close_text = "❌ Показатели не сохранил, сам файл оставил в архиве документов."
        else:
            # /doc — пользователь сам явно вошёл в режим загрузки, тут отмена
            # действительно значит «выбросить», как и раньше.
            # Issue #516: снимаем отметку дедупликации — отменённый документ
            # не должен блокировать повторную отправку того же файла.
            if tmp_path.exists():
                doc_dedup.clear(user_id, tmp_path.read_bytes())
            tmp_path.unlink(missing_ok=True)
            close_text = "❌ Не сохранил."

        # Issue #499: если следующий документ уже ждёт в очереди (альбом/ZIP) —
        # сразу переходим к нему вместо того чтобы просто закрыть шаг.
        await finish_step_or_advance(
            callback,
            state,
            close_text,
            is_auto=is_auto,
            done_hint="Пришли другой документ или /cancel.",
        )
        return

    # Сохранение
    final_path = _uploads_dir(user_id) / pending["stored_name"]
    # Issue #516: содержимое читаем ДО переноса файла — нужно и для записи в
    # KB (уже было так), и для пометки «успешно сохранён» в дедупе.
    content_for_dedup = tmp_path.read_bytes() if tmp_path.exists() else None
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

    if content_for_dedup is not None:
        # Успешно сохранён — теперь и только теперь считаем файл «уже
        # виденным» на разумный срок (issue #516: не при приёме, а по факту).
        doc_dedup.mark_saved(user_id, content_for_dedup)

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
    # Issue #499: следующий документ из очереди (альбом/ZIP) запускается сразу,
    # без ожидания нового сообщения. Issue #441 п.1 остаётся в силе для
    # авто-детекта — там очереди не бывает, и после save FSM просто закрывается.
    await finish_step_or_advance(
        callback,
        state,
        close_text,
        is_auto=is_auto,
        parse_mode="HTML",
        answer_text="Сохранено",
        done_hint="Можешь прислать ещё документ или /cancel.",
    )

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
