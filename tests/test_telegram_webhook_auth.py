"""Security + характеризующий тест аутентификации /telegram/webhook.

Реальный обработчик — webhook/telegram_router.py:telegram_webhook (обработчик в
apple_health.py:981 затенён и подлежит удалению). Сейчас он принимает любой
POST без проверки X-Telegram-Bot-Api-Secret-Token → можно слать поддельные
Update от любого user_id из docker-сети.

Характеризующий: валидный запрос с правильным секретом проходит (НЕ 403).
Security: без секрета / с неверным — 403. RED сейчас → GREEN после фикса.

Используется payload без message (`{"update_id": 1}`) — обработчик отвечает
рано (ignored_no_message), не трогая БД и dispatcher: изолируем именно
секрет-гейт.
"""

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

SECRET = "webhook-secret-abc123"
PAYLOAD = {"update_id": 1}


@pytest.fixture
def webhook_client(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
    from webhook import telegram_router

    app = FastAPI()
    app.include_router(telegram_router.router)
    return TestClient(app)


def test_valid_secret_passes(webhook_client):
    """Характеризующий: правильный секрет → запрос обрабатывается (не 403)."""
    r = webhook_client.post(
        "/telegram/webhook",
        json=PAYLOAD,
        headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
    )
    assert r.status_code == 200, r.text
    assert r.json().get("action") == "ignored_no_message"


def test_missing_secret_rejected(webhook_client):
    """Security: без секрет-заголовка → 403."""
    r = webhook_client.post("/telegram/webhook", json=PAYLOAD)
    assert r.status_code == 403, f"ожидали 403, получили {r.status_code}"


def test_wrong_secret_rejected(webhook_client):
    """Security: неверный секрет → 403."""
    r = webhook_client.post(
        "/telegram/webhook",
        json=PAYLOAD,
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )
    assert r.status_code == 403
