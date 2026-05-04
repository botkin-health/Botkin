"""Telegram webhook entry point.

Routes incoming Telegram updates to:
- handle_onboarding(): new users (not in DB)
- forward_to_container(): existing users with a provisioned NanoClaw container
- no-op: existing users without container (Sprint 1a state for Andrey/Elen)
- no-op: photo/voice messages (handled by legacy aiogram long-poll process)

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
    """Dispatch new user to the onboarding wizard."""
    from handlers.onboarding import process_onboarding_message

    await process_onboarding_message(payload)


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
    msg = payload.get("message") or payload.get("edited_message") or {}
    if not msg:
        return {"status": "ok", "action": "ignored_no_message"}

    from_id = msg.get("from", {}).get("id")
    if not from_id:
        return {"status": "ok", "action": "ignored_no_from_id"}

    db = SessionLocal()
    try:
        user = db.query(User).filter_by(telegram_id=from_id).first()

        # Photo or voice — handled by legacy aiogram long-poll process
        if "photo" in msg or "voice" in msg:
            logger.info("Media message received — handled by legacy bot")
            return {"status": "ok", "action": "legacy_media"}

        # New user — start onboarding wizard
        if not user:
            await handle_onboarding(payload)
            return {"status": "ok", "action": "onboarding"}

        # Existing user but no container yet (Sprint 1a state)
        if not user.container_id or not user.container_port:
            logger.info(f"User {from_id} has no container yet — no-op in Sprint 1a")
            return {"status": "ok", "action": "no_container"}

        # Route to user's NanoClaw container
        await forward_to_container(user.container_id, user.container_port, payload)
        return {"status": "ok", "action": "forwarded"}
    finally:
        db.close()
