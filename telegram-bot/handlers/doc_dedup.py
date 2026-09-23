# telegram-bot/handlers/doc_dedup.py
"""Дедупликация документов по содержимому (issue #503 → #499 → #516).

Инцидент #503: пользователь прислал ОДИН И ТОТ ЖЕ PDF пятью разными
сообщениями Telegram (разные message_id/update_id) — `IdempotencyMiddleware`
(telegram-bot/middlewares/idempotency.py) дедупит только апдейты, не
содержимое файла, так что каждое сообщение ушло в полноценный (платный)
LLM-разбор со своим отдельным ответом пользователю.

Для очереди из #499 это особенно важно: ZIP-архив от пользователя может
содержать несколько копий одного документа (пересканы, случайные дубли), и
без входного гейта по хэшу каждая копия дала бы лишний LLM-вызов и лишнее
сообщение. Модуль сделан переиспользуемым и не зависит от FSM/Telegram —
годится и для очереди `/doc`, и в перспективе для авто-детекта в
`handlers/photo.py` (там дедупа по содержимому пока нет, но это отдельная
задача — не трогаем этот путь здесь).

Issue #516 (продакшн-инцидент на дев-стенде): старая версия помечала контент
как «виденный» СРАЗУ при приёме (`mark=True` в `is_duplicate`), независимо от
исхода. Пользователь нажимал «Отмена» на документе (не сохранил), затем
присылал этот же файл повторно — бот отвечал «точный повтор уже разобранного
файла» и не разбирал его вовсе. Это ломает ровно тот сценарий, который нужен
для исправления самого #516: после сбоя показа превью или рестарта правильное
действие пользователя — прислать файл ещё раз, и дедуп не должен этому
мешать.

Решение — двухфазная отметка вместо одной:
  - `mark_in_progress()` — при приёме, пока файл ещё разбирается. Ловит
    исходный шквал #503 (пять одинаковых сообщений подряд, пока первое ещё
    не долетело до подтверждения). TTL короче и служит только страховкой на
    случай, если `clear()` почему-то не был вызван (сбой без обработки
    исключения где-то в новом коде) — сама по себе отметка снимается явно.
  - `mark_saved()` — при фактическом успешном сохранении (`docup_save`).
    Именно она блокирует повторную отправку «того же анализа ещё раз» на
    разумный срок.
  - `clear()` — при отмене, сбое или архивации без разбора: снимает отметку,
    чтобы повторная отправка того же файла не была нужна пользователю в
    другой форме и просто сработала как в первый раз.

Хранилище — только in-memory, короткий TTL. Не претендует на межпроцессную
или переживающую рестарт идемпотентность (как и DocUpload.FSM на
MemoryStorage) — это защита от быстрого повторного шквала одного и того же
файла, а не постоянный реестр «что когда-либо присылали». Рестарт бота стирает
и FSM, и этот кэш одновременно (оба — обычные объекты процесса), так что
после рестарта резидентных блоков не остаётся вообще.
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from typing import Optional

STATUS_IN_PROGRESS = "in_progress"
STATUS_SAVED = "saved"

# Сколько считаем документ «сейчас разбираю» — страховочный потолок на случай
# если explicit clear() не случился (не должно быть основным механизмом снятия
# отметки, только подстраховкой от вечной блокировки).
IN_PROGRESS_TTL_SECONDS = 15 * 60

# Несколько минут — не даёт повторно скормить в LLM тот же УЖЕ СОХРАНЁННЫЙ
# анализ, но не мешает переслать тот же файл заново спустя долгое время
# осмысленно (например тот же анализ на память через месяц).
SAVED_TTL_SECONDS = 10 * 60
# Старое имя — оставлено, т.к. на него ссылались вызовы вида
# `doc_dedup.DEDUP_TTL_SECONDS` (тесты); семантически то же самое, что и
# SAVED_TTL_SECONDS.
DEDUP_TTL_SECONDS = SAVED_TTL_SECONDS

MAX_ENTRIES_PER_USER = 200

# user_id -> OrderedDict[sha256_hex -> (status, expires_at)]
_seen: dict[int, "OrderedDict[str, tuple[str, float]]"] = {}


def content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _prune(bucket: "OrderedDict[str, tuple[str, float]]", now: float) -> None:
    expired = [h for h, (_, expires_at) in bucket.items() if expires_at < now]
    for h in expired:
        del bucket[h]


def status(user_id: int, content: bytes) -> Optional[str]:
    """Текущий статус контента для юзера: `STATUS_SAVED`, `STATUS_IN_PROGRESS`
    либо `None` (не видели недавно — можно разбирать)."""
    now = time.time()
    h = content_hash(content)
    bucket = _seen.setdefault(user_id, OrderedDict())
    _prune(bucket, now)
    entry = bucket.get(h)
    return entry[0] if entry else None


def _set(user_id: int, content: bytes, state: str, ttl: float) -> None:
    now = time.time()
    h = content_hash(content)
    bucket = _seen.setdefault(user_id, OrderedDict())
    _prune(bucket, now)
    bucket[h] = (state, now + ttl)
    bucket.move_to_end(h)
    while len(bucket) > MAX_ENTRIES_PER_USER:
        bucket.popitem(last=False)


def mark_in_progress(user_id: int, content: bytes) -> None:
    """Помечает контент как «сейчас разбираю» — вызывается при приёме файла,
    до того как известен исход (issue #516: временная отметка, не постоянная)."""
    _set(user_id, content, STATUS_IN_PROGRESS, IN_PROGRESS_TTL_SECONDS)


def mark_saved(user_id: int, content: bytes) -> None:
    """Помечает контент как «успешно сохранён» — вызывается после того, как
    документ реально попал в KB (`docup_save`), не раньше."""
    _set(user_id, content, STATUS_SAVED, SAVED_TTL_SECONDS)


def clear(user_id: int, content: bytes) -> None:
    """Снимает отметку — документ отменён, сбойнул или заархивирован без
    разбора. Повторная отправка того же файла должна разбираться заново
    (issue #516), а не отклоняться как «уже виденный»."""
    h = content_hash(content)
    bucket = _seen.get(user_id)
    if bucket is not None:
        bucket.pop(h, None)


def reset(user_id: Optional[int] = None) -> None:
    """Только для тестов — очищает кэш (для конкретного юзера либо весь)."""
    if user_id is None:
        _seen.clear()
    else:
        _seen.pop(user_id, None)
