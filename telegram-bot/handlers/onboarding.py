"""Throwaway onboarding wizard for Sprint 1a.

State machine stored in users.onboarding_step + users.onboarding_data.
Steps: name → age → sex → height → has_garmin → done.

On completion: generates health_token, sends instructions for HAE setup.
This wizard is replaced by agent-driven onboarding in Sprint 2.
"""

import logging
import os
import secrets
import uuid
from typing import Optional

import httpx

from database import SessionLocal
from database.models import User

logger = logging.getLogger(__name__)


async def send_message(chat_id: int, text: str, reply_markup: Optional[dict] = None) -> None:
    """Send a message via Telegram Bot API."""
    bot_token = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not bot_token:
        logger.warning("No BOT_TOKEN — cannot send message")
        return
    body = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        body["reply_markup"] = reply_markup
    async with httpx.AsyncClient() as client:
        try:
            await client.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json=body, timeout=10.0)
        except Exception as e:
            logger.error(f"Failed to send message to {chat_id}: {e}")


async def start_wizard(payload: dict) -> None:
    """Entry point called by telegram_router for new users."""
    await process_onboarding_message(payload)


async def process_onboarding_message(payload: dict) -> None:
    """Process one message in the onboarding state machine."""
    msg = payload.get("message", {})
    from_id = msg.get("from", {}).get("id")
    chat_id = msg.get("chat", {}).get("id")
    text = (msg.get("text") or "").strip()

    db = SessionLocal()
    try:
        user = db.query(User).filter_by(telegram_id=from_id).first()

        if not user:
            # Create new user row, start at 'name' step
            user = User(
                telegram_id=from_id,
                username=msg.get("from", {}).get("username"),
                first_name=msg.get("from", {}).get("first_name", ""),
                cohort="external",
                pack_name="generic",
                onboarding_step="name",
                onboarding_data={},
                is_active=True,
            )
            db.add(user)
            db.commit()
            await send_message(chat_id, "👋 Привет! Я твой персональный health-coach.\n\nКак тебя зовут?")
            return

        step = user.onboarding_step or "name"
        data = dict(user.onboarding_data or {})

        if step == "name":
            if not text:
                await send_message(chat_id, "Как тебя зовут?")
                return
            data["name"] = text[:100]
            user.first_name = text[:100]
            user.onboarding_step = "age"
            user.onboarding_data = data
            db.commit()
            await send_message(chat_id, f"Приятно познакомиться, {text}! Сколько тебе лет?")
            return

        if step == "age":
            try:
                age = int(text)
                if not (10 <= age <= 120):
                    raise ValueError("out of range")
            except (ValueError, TypeError):
                await send_message(chat_id, "Введи число от 10 до 120 — сколько тебе лет?")
                return
            data["age"] = age
            user.onboarding_step = "sex"
            user.onboarding_data = data
            db.commit()
            keyboard = {"keyboard": [["М", "Ж"]], "one_time_keyboard": True, "resize_keyboard": True}
            await send_message(chat_id, "Пол?", reply_markup=keyboard)
            return

        if step == "sex":
            normalized = text.upper().strip()
            if normalized.startswith("М") or normalized.startswith("M"):
                sex = "M"
            elif normalized.startswith("Ж") or normalized.startswith("F"):
                sex = "F"
            else:
                keyboard = {"keyboard": [["М", "Ж"]], "one_time_keyboard": True, "resize_keyboard": True}
                await send_message(chat_id, "Нажми кнопку М или Ж", reply_markup=keyboard)
                return
            data["sex"] = sex
            user.onboarding_step = "height"
            user.onboarding_data = data
            db.commit()
            await send_message(chat_id, "Рост в см? (например: 178)")
            return

        if step == "height":
            try:
                height = int(text)
                if not (100 <= height <= 230):
                    raise ValueError("out of range")
            except (ValueError, TypeError):
                await send_message(chat_id, "Введи рост в см от 100 до 230")
                return
            data["height_cm"] = height
            user.onboarding_step = "has_garmin"
            user.onboarding_data = data
            db.commit()
            keyboard = {"keyboard": [["Да", "Нет"]], "one_time_keyboard": True, "resize_keyboard": True}
            await send_message(chat_id, "У тебя есть Garmin?", reply_markup=keyboard)
            return

        if step == "has_garmin":
            data["has_garmin"] = text.lower().startswith("д") or text.lower() == "yes"
            user.onboarding_data = data
            user.onboarding_step = "done"
            user.health_token = f"hvt_{user.telegram_id}_{secrets.token_hex(16)}"
            if not user.share_token:
                user.share_token = str(uuid.uuid4()).replace("-", "")[:32]
            db.commit()

            await send_message(
                chat_id,
                f"Готово! 🎉\n\n"
                f"<b>Твой Apple Health токен:</b>\n"
                f"<code>{user.health_token}</code>\n\n"
                f"Установи приложение Health Auto Export ($24.99, есть 7 дней триала):\n"
                f"https://apps.apple.com/app/health-auto-export-json-csv/id1115567069\n\n"
                f"Настрой в нём:\n"
                f"• REST API → URL: <code>https://health.orangegate.cc/apple_health_v2</code>\n"
                f"• Header: <code>Authorization: Bearer {user.health_token}</code>\n\n"
                f"Пиши мне еду текстом, фото или голосом — буду считать калории. "
                f"Скоро появится твой личный агент-коуч!",
            )
            return

        if step == "done":
            logger.info(f"User {from_id} onboarding_step=done, router shouldn't route here")

    finally:
        db.close()
