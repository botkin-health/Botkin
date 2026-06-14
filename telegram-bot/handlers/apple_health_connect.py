#!/usr/bin/env python3
"""
Подключение Apple Health — единая развилка «Health Auto Export / бесплатный iOS Shortcut».

Один источник правды для всех входов в подключение Apple Health:
- команда /health_token (handlers/commands.py),
- финиш онбординга при выборе Apple-устройства (handlers/onboarding.py),
- ответ агента в чате («хочу подключить Apple Health» → направляет на /health_token).

Принцип: ВЕЗДЕ, где предлагается платный HAE, рядом показываем бесплатный Shortcut —
с честным перечнем его ограничений (только Watch-метрики за сегодня, без веса/давления/сна).

Inline-кнопки из онбординга (raw Bot API) и из команды (aiogram) дают одинаковый
callback_data; нажатие в обоих случаях ловит хендлер ниже (callback_query форвардятся
в aiogram-диспетчер из webhook/telegram_router.py).
"""

import logging

from aiogram import Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from handlers.callbacks import HealthConnectCallback

logger = logging.getLogger(__name__)

router = Router()

# ── Константы ────────────────────────────────────────────────────────────────

GUIDE_URL = "https://github.com/Lyskovsky/Botkin/blob/main/docs/user_guide/ru/apple-health.md"
SHORTCUT_ICLOUD_URL = "https://www.icloud.com/shortcuts/61542a7b1edb42ad86b0b99137c00a94"

HAE_LABEL = "💰 Health Auto Export ($24.99)"
SHORTCUT_LABEL = "🆓 iOS Shortcuts (бесплатно)"


# ── Клавиатуры (два формата: aiogram и raw dict для онбординга) ──────────────


def connect_keyboard_aiogram() -> InlineKeyboardMarkup:
    """Inline-клавиатура выбора способа подключения (для aiogram message.answer)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=HAE_LABEL, callback_data=HealthConnectCallback(method="hae").pack())],
            [InlineKeyboardButton(text=SHORTCUT_LABEL, callback_data=HealthConnectCallback(method="shortcut").pack())],
        ]
    )


def connect_keyboard_dict() -> dict:
    """Та же клавиатура как raw dict — для онбординга (send_message через Bot API)."""
    return {
        "inline_keyboard": [
            [{"text": HAE_LABEL, "callback_data": HealthConnectCallback(method="hae").pack()}],
            [{"text": SHORTCUT_LABEL, "callback_data": HealthConnectCallback(method="shortcut").pack()}],
        ]
    }


# ── Тексты ───────────────────────────────────────────────────────────────────


def connect_intro_text(token: str) -> str:
    """Вводное сообщение с ключом + приглашением выбрать способ (показывается с клавиатурой)."""
    return (
        "🍎 <b>Подключение Apple Health</b>\n\n"
        "🔑 Твой персональный ключ:\n"
        f"<code>{token}</code>\n\n"
        "Данные с Apple Watch, тонометра, весов — всё, что есть в Apple Health, — "
        "будут приходить именно тебе.\n\n"
        "Выбери способ подключения 👇"
    )


def hae_setup_text(token: str) -> str:
    """Инструкция платного пути Health Auto Export."""
    return (
        "💰 <b>Health Auto Export (HAE)</b>\n\n"
        "Платное приложение ($24.99 разово), зато самый надёжный путь: фоновый синк ночью "
        "и полный набор данных — вес, давление, сон с фазами, походка.\n\n"
        "📲 <b>Настройка:</b>\n"
        "1. Поставь Health Auto Export (App Store)\n"
        "2. Add Automation → REST API:\n"
        "   • URL: <code>https://botkin.health/apple_health_v2</code>\n"
        f"   • Header: <code>Authorization: Bearer {token}</code>\n"
        "   • Format JSON · v2 · Aggregate ON · Group by Day · Range: Yesterday\n"
        "3. Выбери метрики и сохрани.\n\n"
        f"📖 Подробный гайд: {GUIDE_URL}\n"
        "🆓 Бесплатно (без HAE): /health_token → «iOS Shortcuts»\n"
        "♻️ Перевыпустить ключ: /health_token rotate"
    )


def shortcut_setup_text(token: str) -> str:
    """Инструкция бесплатного пути через iOS Shortcuts (с честными ограничениями)."""
    return (
        "🆓 <b>iOS Shortcuts (бесплатно)</b>\n\n"
        "Бесплатно, через встроенные «Команды» iOS. Данные уходят при каждом открытии Telegram.\n\n"
        "⚠️ <b>Что шлёт:</b> шаги, дистанция, активные ккал, пульс, пульс покоя, HRV, SpO₂, "
        "частота дыхания (метрики Apple Watch, за сегодня).\n"
        "⚠️ <b>Чего НЕ шлёт:</b> вес, давление, сон и фазы сна, историю за прошлые дни. "
        "Если у тебя весы/тонометр (Withings, Omron) или нужен сон — бери HAE.\n\n"
        "📲 <b>Настройка:</b>\n"
        f"1. Установи шаблон: {SHORTCUT_ICLOUD_URL}\n"
        "2. В поле «Текст» вставь свой ключ целиком (вместе со словом Bearer):\n"
        f"   <code>Bearer {token}</code>\n"
        "3. Настройки → Команды → Дополнения → включи «Разрешить публикацию большого количества данных»\n"
        "4. Команды → Автоматизация → + → Приложение → Telegram → «Открывается» → "
        "запустить «Botkin Health Export» → «Выполнять немедленно»\n\n"
        f"📖 Подробный гайд: {GUIDE_URL}\n"
        "💰 Надёжнее и полнее (вес/давление/сон): /health_token → «Health Auto Export»\n"
        "♻️ Перевыпустить ключ: /health_token rotate"
    )


# ── Callback-хендлер ──────────────────────────────────────────────────────────


@router.callback_query(HealthConnectCallback.filter())
async def handle_health_connect(callback: CallbackQuery, callback_data: HealthConnectCallback):
    """Пользователь выбрал способ подключения Apple Health → присылаем инструкцию."""
    from database import SessionLocal
    from database.crud import get_or_create_health_token

    user_id = callback.from_user.id
    db = SessionLocal()
    try:
        token = get_or_create_health_token(db, user_id)
    except Exception as e:
        logger.error(f"health_connect: token error for {user_id}: {e}")
        await callback.answer(f"Ошибка: {e}", show_alert=True)
        return
    finally:
        db.close()

    text = hae_setup_text(token) if callback_data.method == "hae" else shortcut_setup_text(token)

    try:
        await callback.message.answer(text, parse_mode="HTML", disable_web_page_preview=True)
    finally:
        # Снимаем «часики» с кнопки в любом случае.
        await callback.answer()
