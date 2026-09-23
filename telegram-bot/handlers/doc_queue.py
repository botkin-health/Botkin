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

import asyncio
import io
import logging
from collections import Counter
from datetime import date
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
#
# Issue #516: раньше "duplicate_content" покрывал и дубли внутри одной пачки,
# и повторную отправку уже сохранённого/ещё разбираемого файла отдельным
# сообщением — под одним и тем же обманчивым текстом «уже разобранного».
# Теперь это три разных, честных причины.
_REASON_TEXT = {
    "unsupported_type": "не подходящий формат",
    "unsafe_path": "небезопасный путь внутри архива",
    "symlink": "ссылка внутри архива вместо файла",
    "nested_archive": "архив внутри архива",
    "too_large_entry": "слишком большой файл",
    "suspicious_ratio": "файл выглядит подозрительно (слишком сильно сжат)",
    "password_protected": "защищён паролем — пришли файлы без архива, я не смогу его открыть",
    "duplicate_content": "точный повтор внутри этой же пачки",
    "duplicate_saved": "этот файл я уже получил и сохранил недавно",
    "duplicate_in_progress": "этот файл я сейчас уже разбираю",
    "too_large": "файл больше лимита Telegram",
    "download_failed": "не получилось скачать",
}

_ARCHIVE_ERROR_TEXT = {
    "archive_too_large": "архив больше {mb} МБ",
    "corrupt_archive": "не смог открыть — архив повреждён или это не zip",
    "too_many_files": "в архиве больше {limit} файлов",
    "zip_bomb": "после распаковки архив оказался подозрительно большим",
}

# Issue #516 п.3: если ВСЕ отсеянные файлы попали под одну и ту же понятную
# причину, заголовок сводки называет её прямо — иначе пользователь видит «не
# нашёл ни одного подходящего файла», хотя файлы были подходящего формата и
# их отфильтровали по конкретной причине (повтор, пароль).
_HEADER_FOR_SOLE_REASON = {
    "duplicate_saved": "⚠️ Этот документ я уже получил и сохранил недавно — новых файлов не нашёл.",
    "duplicate_in_progress": "⚠️ Этот документ я уже сейчас разбираю — подожди немного, пожалуйста.",
    "duplicate_content": "⚠️ Все файлы — точные повторы внутри одной пачки, ничего нового не нашёл.",
    "password_protected": "⚠️ Файлы защищены паролем — пришли их без архива, я не смогу его открыть.",
}
_DEFAULT_EMPTY_HEADER = "⚠️ Не нашёл ни одного подходящего файла (PDF, JPG, PNG, HEIC)."

# Issue #516 доп. (дефект А, независимый ревьюер): webhook обрабатывает
# апдейты параллельно, Dispatcher не изолирует события одного пользователя —
# два апдейта (альбом пришедший частями из-за задержки MediaGroupMiddleware,
# либо новый файл ровно в момент подтверждения предыдущего) могут одновременно
# делать get_data → update_data над одним и тем же `queue`/`pending`.
# aiogram MemoryStorage не даёт атомарного read-modify-write, поэтому
# сериализуем такие операции per-user через обычный `asyncio.Lock`.
_user_queue_locks: dict[int, asyncio.Lock] = {}


def queue_lock(user_id: int) -> asyncio.Lock:
    """`asyncio.Lock`, общий для всех операций чтения+записи `queue`/`pending`
    в FSM этого пользователя. Использовать как `async with queue_lock(uid):`."""
    lock = _user_queue_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _user_queue_locks[user_id] = lock
    return lock


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
    содержимому и считает, что и почему пропущено — для понятной сводки
    пользователю.

    Issue #516: две независимые проверки дублей, раньше смешанные в одну.
      - Дубли ВНУТРИ этой же пачки (ZIP/альбом с копиями одного файла,
        issue #503) — локальное множество хэшей, живёт только на время этого
        вызова, не зависит от глобального кэша `doc_dedup`.
      - Повторная отправка того же файла ОТДЕЛЬНЫМ сообщением — глобальный
        кэш `doc_dedup` (переживает вызовы, недолгий TTL). Блокирует только
        если файл либо уже сейчас разбирается (`mark_in_progress` при приёме,
        снимается через `doc_dedup.clear` при отмене/сбое), либо уже успешно
        сохранён недавно (`mark_saved` при `docup_save`). Отменённый, упавший
        или ещё не досмотренный документ НЕ блокирует повтор.
    """
    result = GatherResult()
    local_seen: set[str] = set()

    def _check_and_register(content: bytes) -> Optional[str]:
        """None — не дубль, контент зарегистрирован (локально + как
        «в обработке» глобально). Иначе — причина пропуска."""
        h = doc_dedup.content_hash(content)
        if h in local_seen:
            return "duplicate_content"
        existing_status = doc_dedup.status(user_id, content)
        if existing_status == doc_dedup.STATUS_SAVED:
            return "duplicate_saved"
        if existing_status == doc_dedup.STATUS_IN_PROGRESS:
            return "duplicate_in_progress"
        local_seen.add(h)
        doc_dedup.mark_in_progress(user_id, content)
        return None

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
                    skip_reason = _check_and_register(extracted.content)
                    if skip_reason:
                        result.skip_counts[skip_reason] += 1
                        continue
                    result.items.append(_make_item(extracted.content, extracted.ext, extracted.is_pdf, extracted.name))
                continue

            skip_reason = _check_and_register(content)
            if skip_reason:
                result.skip_counts[skip_reason] += 1
                continue
            ext = ".pdf" if is_pdf else (Path(fname).suffix or ".jpg")
            result.items.append(_make_item(content, ext, is_pdf, fname or "документ"))

        elif msg.photo:
            file_id = msg.photo[-1].file_id
            content = await _download(msg, file_id)
            if content is None:
                result.skip_counts["download_failed"] += 1
                continue
            skip_reason = _check_and_register(content)
            if skip_reason:
                result.skip_counts[skip_reason] += 1
                continue
            result.items.append(_make_item(content, ".jpg", False, "фото"))

    return result


def empty_gather_header(gathered: GatherResult) -> str:
    """Заголовок для случая, когда после сборки не осталось ни одного файла
    для разбора (issue #516 п.3).

    Раньше заголовок всегда был «не нашёл ни одного подходящего файла» — даже
    если файлы были самого что ни на есть подходящего формата, просто все до
    единого оказались повторами или под паролем. Это вводило в заблуждение:
    правильная реакция пользователя на «не нашёл подходящего файла» и на
    «уже сохранил этот файл» — разная. Если все отсеянные файлы попали под
    одну и ту же понятную причину — называем её прямо.
    """
    counts = gathered.skip_counts
    total = sum(counts.values())
    if counts and len(counts) == 1 and total > 0:
        (reason, count) = next(iter(counts.items()))
        if count == total:
            header = _HEADER_FOR_SOLE_REASON.get(reason)
            if header:
                return header
    return _DEFAULT_EMPTY_HEADER


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


def load_staged_item(staged: dict[str, Any]) -> Optional[tuple[bytes, str, bool, str]]:
    """Читает файл очереди обратно с диска и удаляет `.queued_*` — следующий
    шаг (`run_doc_pipeline`) сам запишет свежий `.pending_*`.

    Issue #516 доп. (дефект Б): если файл почему-то пропал с диска (например,
    сторож `_cleanup_stale_pending` его тронул до фикса, или ручное
    вмешательство) — возвращает `None` вместо падения с `FileNotFoundError`.
    Раньше такое падение обрывало `finish_step_or_advance` посреди callback'а,
    и пользователь не получал вообще никакого ответа на нажатую кнопку.
    """
    path = Path(staged["tmp_path"])
    if not path.exists():
        logger.warning("doc_queue: файл очереди пропал с диска (%s) — пропускаю элемент очереди", path)
        return None
    content = path.read_bytes()
    path.unlink(missing_ok=True)
    return content, staged["ext"], staged["is_pdf"], staged.get("label", "документ")


def pop_next_loadable(
    queue: list[dict[str, Any]],
) -> tuple[Optional[tuple[bytes, str, bool, str]], list[str], list[dict[str, Any]]]:
    """Достаёт из головы очереди первый элемент, чей файл реально читается с
    диска — пропуская (с логом в `load_staged_item`) записи, чьи `.queued_*`
    файлы пропали (issue #516 доп., дефект Б). Возвращает (загруженный
    кортеж или `None` если вся очередь пуста/нечитаема, метки пропущенных
    элементов, остаток очереди без уже обработанных/пропущенных)."""
    remaining = list(queue)
    skipped: list[str] = []
    while remaining:
        candidate = remaining.pop(0)
        loaded = load_staged_item(candidate)
        if loaded is None:
            skipped.append(candidate.get("label", "документ"))
            continue
        return loaded, skipped, remaining
    return None, skipped, remaining


def pluralize_docs(n: int) -> str:
    """«документ»/«документа»/«документов» — используется в нескольких
    местах для сообщений пользователю."""
    return "документ" if n == 1 else "документа" if 2 <= n <= 4 else "документов"


def archive_single_file(
    user_id: int,
    tmp_path: Path,
    *,
    reason: str,
    extracted: Optional[dict[str, Any]] = None,
) -> bool:
    """Единая точка архивации одного `.pending_*`/`.queued_*` файла — issue #516.

    Используется и явным `/cancel` (`archive_leftover_documents`), и сторожем
    осиротевших файлов (`doc_upload._cleanup_stale_pending`), и архивацией
    после сбоя показа превью — чтобы формат KB-записи и сама логика переноса
    файла не расходились в трёх местах.

    Переносит файл под постоянное имя (снимает `.pending_`/`.queued_`
    префикс) и добавляет запись `auto_archived` в KB. Снимает отметку
    дедупликации (issue #516): заархивированный без разбора документ не
    считается «уже виденным» — повторная отправка того же файла должна
    разбираться заново, а не отклоняться как повтор.

    Не падает наружу: недоступность KB не должна ронять вызывающий пайплайн
    (сторож вызывается на каждый запуск пайплайна — должен быть дешёвым и
    безопасным). Возвращает True, если файл был перенесён в архив (даже если
    запись в KB не удалась — физически файл уже не потерян).
    """
    from handlers.doc_upload import _uploads_dir, append_document_to_kb

    if not tmp_path.exists():
        return False

    stored_name = tmp_path.name
    for prefix in (".pending_", ".queued_"):
        if stored_name.startswith(prefix):
            stored_name = stored_name[len(prefix) :]
            break

    try:
        content = tmp_path.read_bytes()
    except OSError:
        content = None

    final_path = _uploads_dir(user_id) / stored_name
    try:
        tmp_path.replace(final_path)
    except OSError:
        logger.exception("doc_queue: не удалось перенести файл в архив (user %s, %s)", user_id, tmp_path)
        return False

    if content is not None:
        # Заархивированный без разбора документ — не «уже виденный».
        doc_dedup.clear(user_id, content)

    try:
        append_document_to_kb(
            user_id,
            {
                "added_at": date.today().isoformat(),
                "file": stored_name,
                "extracted": extracted or {},
                "user_confirmed": False,
                "auto_archived": True,
                "reason": reason,
            },
        )
    except Exception:
        # Файл физически уже в архиве (гарантия issue #370 выполнена) — не
        # проиндексирован в KB, но не потерян. Не роняем вызывающий код.
        logger.exception(
            "doc_queue: файл перенесён в архив, но запись в KB не удалась (user %s, %s)", user_id, stored_name
        )

    return True


def archive_leftover_documents(user_id: int, data: dict[str, Any]) -> int:
    """Архивирует всё, что осталось незавершённым в /doc-сессии: текущий
    pending и весь хвост очереди (issue #499, гарантия issue #370 — файл
    никогда просто не исчезает, включая брошенные посреди батча).

    Вызывается при явном /cancel — раньше он просто чистил FSM, оставляя
    текущий `.pending_*` гнить как орфан на 24ч (issue #441 п.7б), а хвост
    очереди из issue #499 вообще нигде не появлялся на диске до этого метода.
    Также переиспользуется при сбое показа превью (issue #516). Возвращает
    число заархивированных файлов (для лога/сообщения).
    """
    archived = 0

    pending = data.get("pending")
    if pending and pending.get("tmp_path"):
        tmp_path = Path(pending["tmp_path"])
        if archive_single_file(
            user_id,
            tmp_path,
            reason="пользователь вышел из /doc, документ не разобран",
            extracted=pending.get("extracted"),
        ):
            archived += 1

    for staged in data.get("queue") or []:
        tmp_path = Path(staged["tmp_path"])
        if archive_single_file(
            user_id,
            tmp_path,
            reason="пользователь вышел из /doc, документ из очереди не разобран",
        ):
            archived += 1

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

    Issue #516 доп.: чтение+запись `queue` идёт под `queue_lock` (тот же
    per-user лок, что и в `doc_upload.doc_received`) — иначе новый файл,
    пришедший ровно в момент подтверждения текущего, может гонкой затереть
    друг друга. Если у элемента очереди файл пропал с диска (дефект Б) —
    пропускаем его молча в лог, но не роняем callback без ответа пользователю.
    """
    from handlers.doc_upload import run_doc_pipeline

    user_id = callback.from_user.id
    async with queue_lock(user_id):
        data = await state.get_data()
        queue = data.get("queue") or []
        queue_total = data.get("queue_total") or (len(queue) + 1)

        loaded, skipped_labels, rest = (None, [], queue)
        if not is_auto and queue:
            loaded, skipped_labels, rest = pop_next_loadable(queue)
            await state.update_data(queue=rest)

    if skipped_labels:
        word = pluralize_docs(len(skipped_labels))
        close_text += f"\n\n⚠️ Не нашёл на диске {len(skipped_labels)} {word} из очереди — пропустил, не разбирал."

    if loaded is not None:
        pos = queue_total - len(rest)
        content, ext, is_pdf, _label = loaded

        await callback.message.edit_text(close_text, parse_mode=parse_mode)
        if answer_text:
            await callback.answer(answer_text)
        else:
            await callback.answer()

        await run_doc_pipeline(
            callback.message,
            state,
            content=content,
            ext=ext,
            is_pdf=is_pdf,
            intro=f"{format_progress_prefix(pos, queue_total)} — читаю…",
            auto=False,
            user_id=user_id,
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
