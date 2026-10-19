"""Регрессия: юнит-тесты не шлют реальных сообщений в Telegram.

19.10.2026 ночная смена прогнала pytest из папки проекта на Google Drive, где
лежит прод-.env, и админ получил «Фидбек из мини-аппа (bug) … Кнопка не
работает» от прод-бота. Цепочка: Settings() внутри теста делал
load_dotenv(override=True) → прод-токен поверх dummy → feedback_api._notify_admin
создавал настоящий aiogram Bot. Защита — tests/conftest.py: load_dotenv под
pytest no-op, а сетевые вызовы к Telegram перехватываются фикстурой
telegram_net_guard и роняют тест.
"""

import asyncio
import os

import pytest
import requests

from conftest import TelegramNetworkBlocked

REAL_LOOKING_TOKEN = "123456789:AAFakeButRealLookingTokenForGuardTest_x"
DUMMY_TOKEN = "0000000000:CI_DUMMY_TOKEN_NOT_REAL"


def test_settings_created_in_test_does_not_pull_token_from_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(f"TELEGRAM_BOT_TOKEN={REAL_LOOKING_TOKEN}\nBOT_TOKEN={REAL_LOOKING_TOKEN}\n")
    monkeypatch.chdir(tmp_path)

    import dotenv

    from config.settings import Settings

    dotenv.load_dotenv(env_file, override=True)
    s = Settings()

    assert os.environ["TELEGRAM_BOT_TOKEN"] == DUMMY_TOKEN
    assert os.environ["BOT_TOKEN"] == DUMMY_TOKEN
    assert s.telegram_bot_token == DUMMY_TOKEN


def test_feedback_notify_admin_with_real_token_is_blocked(monkeypatch, telegram_net_guard):
    """Тот самый путь из инцидента: реальный токен + незамоканный бот."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", REAL_LOOKING_TOKEN)
    from webhook import feedback_api

    monkeypatch.setattr(feedback_api, "_admin_id", lambda: 895655)

    # _notify_admin best-effort и глотает исключения — поэтому гард фиксирует попытку.
    asyncio.run(feedback_api._notify_admin(895655, "bug", "Кнопка не работает", []))

    assert telegram_net_guard.attempts == ["aiogram SendMessage"]
    telegram_net_guard.attempts.clear()


def test_httpx_feedback_notification_is_blocked(monkeypatch, telegram_net_guard):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", REAL_LOOKING_TOKEN)
    from webhook.agent_tools import feedback

    assert asyncio.run(feedback._send_feedback_notification(895655, "готово")) is False
    assert telegram_net_guard.attempts == ["httpx POST sendMessage"]
    telegram_net_guard.attempts.clear()


def test_requests_to_telegram_is_blocked(telegram_net_guard):
    with pytest.raises(TelegramNetworkBlocked):
        requests.post(f"https://api.telegram.org/bot{REAL_LOOKING_TOKEN}/sendMessage", json={}, timeout=1)
    assert telegram_net_guard.attempts == ["requests POST sendMessage"]
    telegram_net_guard.attempts.clear()
