#!/usr/bin/env python3
"""Сторож незакрытых ходов агента: ищет вопросы, оставшиеся без ответа.

Cron на сервере (каждые 15 минут, как send_reminders.py):
    */15 * * * * docker exec <bot_container> python /app/scripts/server/check_stalled_turns.py >> /var/log/botkin_watchdog.log 2>&1

Зачем
-----
Прецедент 24-25.08.2026: пользователь написал боту семь сообщений подряд и не
получил ни одного ответа — около 27 часов тишины, закончившейся репликой
«Похоже Botkin насовсем помер...». Ветки обработки ошибок в хендлерах есть
(529/503/429/generic), но они живут внутри процесса: если процесс умер или
задачу отменили раньше, чем отработал цикл ретраев, `except` не выполнится
никогда, пользователь не увидит ничего, а в базе не останется следа.

Сторож смотрит снаружи и поэтому ловит ЛЮБУЮ причину, включая те, которые
никакой try/except внутри поймать не может. Нашёл — извиняется перед
пользователем, чтобы он не сидел в тишине, и сообщает владельцу.

Что считается «зависшим ходом»
------------------------------
Последняя строка диалога пользователя в `agent_conversations` — его собственная
реплика (`role='user'`) или зафиксированный сбой (`role='error'`), и с момента
её записи прошло больше STALE_AFTER_MINUTES. Нормальный ход завершается
строкой `role='assistant'`, поэтому такой пользователь под условие не попадает.

Почему смотрим только на последнюю строку: ход агента пишет несколько строк
(assistant + tool_result), и промежуточные состояния не должны считаться
зависанием — важен именно исход.

Идемпотентность
---------------
После обработки сторож сам пишет строку `role='error'` с
`source='watchdog_notified'`. На следующем запуске она оказывается последней и
уже помечена как обработанная — повторных писем не будет. Поэтому запускать
можно хоть каждые пять минут.

Ручной запуск:
    python scripts/server/check_stalled_turns.py --dry-run   # только лог
    python scripts/server/check_stalled_turns.py --stale-after 30
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:  # pragma: no cover - dotenv опционален
    pass

import requests  # noqa: E402

logger = logging.getLogger("check_stalled_turns")

TELEGRAM_API_BASE = "https://api.telegram.org"
REQUEST_TIMEOUT = 15

# Сколько ждать, прежде чем счесть ход зависшим. Нормальный ход агента — это
# до MAX_TOOL_ITERATIONS обращений к модели, каждое с ретраями и таймаутом 60 с,
# то есть несколько минут в худшем случае. 20 минут — заведомо больше любого
# живого хода и заметно меньше, чем «пользователь успел решить, что бот умер».
STALE_AFTER_MINUTES = 20

# Дальше этого в прошлое не смотрим: старые незакрытые ходы разбираются глазами
# по отчёту ночной смены, а не письмами пользователю через неделю после сбоя.
LOOKBACK_HOURS = 24

WATCHDOG_SOURCE = "watchdog_notified"

USER_TEXT = (
    "Извини — я не смог ответить на твоё последнее сообщение, это сбой на моей стороне, "
    "а не что-то с твоим вопросом. Ничего из твоих данных не потерялось.\n\n"
    "Напиши его ещё раз, пожалуйста — сейчас отвечу."
)

# Кому слать алерт. Владелец берётся из env, как в остальном коде
# (core/health/garmin_data.py тоже читает BOTKIN_USER_ID).
_OWNER_ENV = ("BOTKIN_OWNER_ID", "BOTKIN_USER_ID", "HEALTHVAULT_USER_ID")


_STALLED_SQL = """
    WITH last_rows AS (
        SELECT DISTINCT ON (user_id)
               user_id, role, source, created_at, content
        FROM agent_conversations
        WHERE created_at >= NOW() - make_interval(hours => :lookback)
        ORDER BY user_id, created_at DESC, id DESC
    )
    SELECT lr.user_id, u.first_name, lr.role, lr.created_at,
           EXTRACT(EPOCH FROM (NOW() - lr.created_at)) / 60 AS age_min,
           lr.content::text AS content
    FROM last_rows lr
    JOIN users u ON u.telegram_id = lr.user_id
    WHERE lr.role IN ('user', 'error')
      AND COALESCE(lr.source, '') <> :watchdog_source
      AND lr.created_at <= NOW() - make_interval(mins => :stale_after)
      AND u.is_active
    ORDER BY lr.created_at
"""


def _owner_id() -> int | None:
    for key in _OWNER_ENV:
        raw = os.environ.get(key)
        if raw:
            try:
                return int(raw)
            except ValueError:
                logger.warning("%s=%r не число — игнорирую", key, raw)
    return None


def _send(token: str, chat_id: int, text: str, dry: bool) -> bool:
    if dry:
        logger.info("[dry] -> %s: %s", chat_id, text.replace("\n", " ")[:100])
        return True
    resp = requests.post(
        f"{TELEGRAM_API_BASE}/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=REQUEST_TIMEOUT,
    )
    body = resp.json()
    if resp.status_code != 200 or not body.get("ok"):
        logger.error("Telegram error chat=%s: %s", chat_id, body.get("description", resp.text))
        return False
    return True


def _preview(content: str, limit: int = 120) -> str:
    """Короткая выжимка реплики для алерта владельцу."""
    try:
        data = json.loads(content)
    except (ValueError, TypeError):
        return content.strip()[:limit]
    if isinstance(data, str):
        return data.strip()[:limit]
    if isinstance(data, list):
        parts = [b.get("text", "") for b in data if isinstance(b, dict) and b.get("type") == "text"]
        return " ".join(p for p in parts if p).strip()[:limit]
    return str(data)[:limit]


def run(dry: bool = False, stale_after: int = STALE_AFTER_MINUTES, lookback: int = LOOKBACK_HOURS) -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token and not dry:
        logger.error("TELEGRAM_BOT_TOKEN env var not set")
        return 1

    from sqlalchemy import text as sql_text

    from database import SessionLocal

    db = SessionLocal()
    try:
        rows = db.execute(
            sql_text(_STALLED_SQL),
            {"lookback": lookback, "stale_after": stale_after, "watchdog_source": WATCHDOG_SOURCE},
        ).fetchall()

        if not rows:
            logger.info("зависших ходов нет (окно %s ч, порог %s мин)", lookback, stale_after)
            return 0

        logger.warning("найдено зависших ходов: %s", len(rows))
        owner = _owner_id()

        for r in rows:
            age = int(r.age_min)
            logger.warning(
                "user=%s (%s) role=%s возраст=%s мин: %s",
                r.user_id,
                r.first_name,
                r.role,
                age,
                _preview(r.content),
            )

            notified = _send(token, int(r.user_id), USER_TEXT, dry)

            if owner and owner != int(r.user_id):
                _send(
                    token,
                    owner,
                    (
                        f"⚠️ Ход агента завис\n"
                        f"Пользователь: {r.first_name} ({r.user_id})\n"
                        f"Последняя строка: role={r.role}, {age} мин назад\n"
                        f"Текст: {_preview(r.content)}\n"
                        f"Пользователю {'отправлено извинение' if notified else 'ОТПРАВИТЬ НЕ УДАЛОСЬ'}."
                    ),
                    dry,
                )

            if not dry and notified:
                # Помечаем ход обработанным, чтобы не слать повторно.
                db.execute(
                    sql_text(
                        "INSERT INTO agent_conversations (user_id, role, content, source) "
                        "VALUES (:uid, 'error', CAST(:content AS jsonb), :source)"
                    ),
                    {
                        "uid": int(r.user_id),
                        "content": json.dumps(
                            [{"type": "text", "text": f"watchdog: ход без ответа {age} мин, пользователь уведомлён"}],
                            ensure_ascii=False,
                        ),
                        "source": WATCHDOG_SOURCE,
                    },
                )
                db.commit()

        return 0
    finally:
        db.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Сторож незакрытых ходов агента")
    parser.add_argument("--dry-run", action="store_true", help="ничего не отправлять и не писать в БД")
    parser.add_argument("--stale-after", type=int, default=STALE_AFTER_MINUTES, help="порог в минутах")
    parser.add_argument("--lookback", type=int, default=LOOKBACK_HOURS, help="окно поиска в часах")
    args = parser.parse_args()
    return run(dry=args.dry_run, stale_after=args.stale_after, lookback=args.lookback)


if __name__ == "__main__":
    sys.exit(main())
