"""Telegram webhook entry point.

Все запросы идут в legacy aiogram dispatcher (то есть в основной aiogram-бот),
где BotkinClaw (in-process AI-агент) обрабатывает свободно-формулированные
вопросы через `handlers/text.py`.

Раньше здесь была развилка: пользователи с провижненым NanoClaw-контейнером
получали forward в их container, остальные — fallback на legacy aiogram.
После сноса NanoClaw (см. ADR-0002, 21.05.2026) все ходят через legacy,
поэтому forward-ветка удалена. История в git, при желании посмотреть —
коммит `0af69dd` (feat: NanoClaw deploy Phase 1-3).

IMPORTANT: Этот роутер НЕ парсит текст. Он только определяет:
- message.from.id → identify user
- message type (photo/voice vs text)
- onboarding-state → routing decision (новый юзер → onboarding wizard, иначе legacy)
"""

import hmac
import logging
import os

import httpx
from fastapi import APIRouter, Header, HTTPException

from database import SessionLocal
from database.models import User

logger = logging.getLogger(__name__)
router = APIRouter()


def _verify_webhook_secret(secret_header: str | None) -> None:
    """Проверяет X-Telegram-Bot-Api-Secret-Token против TELEGRAM_WEBHOOK_SECRET.

    Telegram шлёт этот заголовок, если секрет передан в setWebhook. Без проверки
    любой в docker-сети может слать поддельные Update от чужого user_id.
    Если секрет не сконфигурирован — пропускаем (обратная совместимость на время
    выкатки), но логируем предупреждение.
    """
    expected = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    if not expected:
        logger.warning("TELEGRAM_WEBHOOK_SECRET не задан — /telegram/webhook без аутентификации")
        return
    if not secret_header or not hmac.compare_digest(secret_header, expected):
        raise HTTPException(status_code=403, detail="Invalid webhook secret")


async def handle_onboarding(payload: dict) -> None:
    """Dispatch new user to the onboarding wizard.

    Sprint 1a stub: onboarding wizard (handlers.onboarding) is not yet implemented.
    Logs the new user and returns gracefully. Sprint 1b will add the full wizard.
    """
    try:
        from handlers.onboarding import process_onboarding_message

        await process_onboarding_message(payload)
    except ModuleNotFoundError:
        chat_id = (payload.get("message") or {}).get("chat", {}).get("id")
        from_id = (payload.get("message") or {}).get("from", {}).get("id")
        logger.info(f"Onboarding stub: new user {from_id} in chat {chat_id} — wizard not yet implemented (Sprint 1b)")


async def _feed_legacy_bot(payload: dict) -> bool:
    """Feed a Telegram update to the legacy aiogram dispatcher.

    Returns True if the dispatcher was available, False otherwise.
    """
    try:
        from aiogram.types import Update as TgUpdate
        from webhook.apple_health import _tg_bot, _tg_dp

        if _tg_bot is None or _tg_dp is None:
            logger.warning("Legacy aiogram dispatcher not initialised — cannot fall back")
            return False
        update = TgUpdate(**payload)
        await _tg_dp.feed_update(_tg_bot, update)
        return True
    except Exception as e:
        logger.error(f"Failed to feed update to legacy bot: {e}")
        return False


async def _send_fallback(chat_id: int, text: str) -> None:
    """Send a fallback message via Telegram Bot API."""
    bot_token = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not bot_token:
        logger.warning("No BOT_TOKEN set, cannot send fallback message")
        return
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=10.0,
            )
        except Exception as e:
            logger.error(f"Failed to send fallback message: {e}")


@router.post("/telegram/webhook")
async def telegram_webhook(
    payload: dict,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    """Main Telegram webhook handler."""
    _verify_webhook_secret(x_telegram_bot_api_secret_token)

    # callback_query (button press) — always forward to legacy aiogram dispatcher
    if "callback_query" in payload:
        cb = payload["callback_query"]
        from_id = cb.get("from", {}).get("id")
        logger.info(f"Callback query from {from_id} — forwarding to legacy bot")
        await _feed_legacy_bot(payload)
        return {"status": "ok", "action": "legacy_callback"}

    msg = payload.get("message") or payload.get("edited_message") or {}
    if not msg:
        return {"status": "ok", "action": "ignored_no_message"}

    from_id = msg.get("from", {}).get("id")
    if not from_id:
        return {"status": "ok", "action": "ignored_no_from_id"}

    db = SessionLocal()
    try:
        user = db.query(User).filter_by(telegram_id=from_id).first()

        # Auto-sync identity from Telegram payload (Telegram is source of truth
        # for username / first_name / last_name; users can change these any time).
        if user:
            tg_from = msg.get("from", {}) or {}
            tg_username = tg_from.get("username")
            changed = False
            if tg_username and tg_username != user.username:
                logger.info(f"User {from_id} username updated: {user.username!r} -> {tg_username!r}")
                user.username = tg_username
                changed = True
            # first_name/last_name sync intentionally skipped — onboarding answers
            # take precedence over Telegram display name.
            if changed:
                db.commit()

        # Photo or voice — forward to legacy aiogram dispatcher
        if "photo" in msg or "voice" in msg:
            logger.info("Media message received — forwarding to legacy bot")
            await _feed_legacy_bot(payload)
            return {"status": "ok", "action": "legacy_media"}

        # New user — start onboarding wizard
        if not user:
            await handle_onboarding(payload)
            return {"status": "ok", "action": "onboarding"}

        # User exists but onboarding not complete — continue wizard
        if user.onboarding_step != "done":
            await handle_onboarding(payload)
            return {"status": "ok", "action": "onboarding_continue"}

        # /setup command — resume wizard for missing fields (post-onboarding top-up)
        text = (msg.get("text") or "").strip().lower()
        if text == "/setup" or text.startswith("/setup "):
            from handlers.onboarding import handle_setup_command

            await handle_setup_command(payload)
            return {"status": "ok", "action": "setup"}

        # All other text — legacy aiogram dispatcher (BotkinClaw lives there)
        await _feed_legacy_bot(payload)
        return {"status": "ok", "action": "legacy_text"}
    finally:
        db.close()
