"""Telegram webhook entry point.

Routes incoming Telegram updates to:
- handle_onboarding(): new users (not in DB)
- forward_to_container(): existing users with a provisioned NanoClaw container
- legacy aiogram dispatcher: users without container (Sprint 1a fallback) + all media

IMPORTANT: This router does NOT parse message text. It only looks at:
- message.from.id → identify user
- message type (photo/voice vs text)
- user.container_id + user.container_port → routing decision
"""

import logging
import os

import httpx
from fastapi import APIRouter

from database import SessionLocal
from database.models import User

logger = logging.getLogger(__name__)
router = APIRouter()


async def forward_to_container(container_id: str, port: int, payload: dict) -> None:
    """POST the Telegram payload to the NanoClaw container's /agent/process endpoint.

    Fire-and-forget — container will call sendMessage back to Telegram directly.
    On failure: send a fallback message to the user.
    """
    url = f"http://{container_id}:{port}/agent/process"
    chat_id = payload.get("message", {}).get("chat", {}).get("id")
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            await client.post(url, json=payload)
        except (httpx.RequestError, httpx.TimeoutException) as e:
            logger.error(f"Failed to forward to container {container_id}: {e}")
            if chat_id:
                await _send_fallback(chat_id, "⚠️ Агент сейчас недоступен, попробуй через минуту.")


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
async def telegram_webhook(payload: dict):
    """Main Telegram webhook handler."""
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
            tg_first = tg_from.get("first_name")
            tg_last = tg_from.get("last_name")
            changed = False
            if tg_username and tg_username != user.username:
                logger.info(f"User {from_id} username updated: {user.username!r} -> {tg_username!r}")
                user.username = tg_username
                changed = True
            if tg_first and tg_first != user.first_name and not (user.first_name or "").startswith("/"):
                # Don't overwrite an explicitly-set name (during onboarding)
                # with the Telegram display name unless it matches what's there.
                # We only sync if user.first_name was the original Telegram value.
                pass  # skip first_name sync to not overwrite onboarding answers
            # last_active updated by main flow elsewhere; we don't touch here
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

        # Existing user but no container yet — fall back to legacy aiogram bot (Sprint 1a)
        if not user.container_id or not user.container_port:
            logger.info(f"User {from_id} has no container yet — falling back to legacy bot")
            await _feed_legacy_bot(payload)
            return {"status": "ok", "action": "legacy_fallback"}

        # Route to user's NanoClaw container
        await forward_to_container(user.container_id, user.container_port, payload)
        return {"status": "ok", "action": "forwarded"}
    finally:
        db.close()
