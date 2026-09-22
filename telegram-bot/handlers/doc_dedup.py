# telegram-bot/handlers/doc_dedup.py
"""Дедупликация документов по содержимому (issue #503 → #499).

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

Хранилище — только in-memory, короткий TTL. Не претендует на межпроцессную
или переживающую рестарт идемпотентность (как и DocUpload.FSM на
MemoryStorage) — это защита от быстрого повторного шквала одного и того же
файла, а не постоянный реестр «что когда-либо присылали».
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from typing import Optional

# Несколько минут — ловит повторную отправку в пределах одной "пачки" от
# пользователя (ретраи, повторные пересылки), но не мешает переслать тот же
# файл заново спустя долгое время осмысленно (например тот же анализ на
# память через месяц).
DEDUP_TTL_SECONDS = 10 * 60
MAX_ENTRIES_PER_USER = 200

# user_id -> OrderedDict[sha256_hex -> expires_at]
_seen: dict[int, "OrderedDict[str, float]"] = {}


def content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _prune(bucket: "OrderedDict[str, float]", now: float) -> None:
    expired = [h for h, expires_at in bucket.items() if expires_at < now]
    for h in expired:
        del bucket[h]


def is_duplicate(user_id: int, content: bytes, *, mark: bool = True) -> bool:
    """True, если этот же контент уже был поставлен в обработку недавно для
    этого пользователя.

    `mark=True` (по умолчанию) сразу же запоминает контент как виденный —
    типичный сценарий «проверить и сразу занять место в очереди». `mark=False`
    — только проверка, без записи.
    """
    now = time.time()
    h = content_hash(content)
    bucket = _seen.setdefault(user_id, OrderedDict())
    _prune(bucket, now)

    if h in bucket:
        if mark:
            bucket.move_to_end(h)
        return True

    if mark:
        bucket[h] = now + DEDUP_TTL_SECONDS
        while len(bucket) > MAX_ENTRIES_PER_USER:
            bucket.popitem(last=False)
    return False


def reset(user_id: Optional[int] = None) -> None:
    """Только для тестов — очищает кэш (для конкретного юзера либо весь)."""
    if user_id is None:
        _seen.clear()
    else:
        _seen.pop(user_id, None)
