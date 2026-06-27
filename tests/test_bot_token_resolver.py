"""Тесты единого резолвера токена бота (#201).

Регрессия: `bot.py` читал только `TELEGRAM_BOT_TOKEN`, а `tg_auth` предпочитал
`BOT_TOKEN`. При половинчатом `.env` (две переменные → разные боты) это давало
`403 initData HMAC mismatch` на дев-стенде: поллинг шёл на один токен, валидация
WebApp-initData — на другой. Резолвер сводит источник к одному.
"""

import sys
from pathlib import Path

import pytest

BOT_DIR = Path(__file__).resolve().parent.parent / "telegram-bot"
sys.path.insert(0, str(BOT_DIR))

from bot_token import resolve_bot_token  # noqa: E402


def test_prefers_telegram_bot_token(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tg-token")
    monkeypatch.setenv("BOT_TOKEN", "bot-token")
    assert resolve_bot_token() == "tg-token"


def test_falls_back_to_bot_token_when_telegram_unset(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("BOT_TOKEN", "bot-token")
    assert resolve_bot_token() == "bot-token"


def test_empty_telegram_token_falls_back(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("BOT_TOKEN", "bot-token")
    assert resolve_bot_token() == "bot-token"


def test_returns_empty_string_when_nothing_set(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    assert resolve_bot_token() == ""


@pytest.mark.parametrize("rel", ["bot.py", "webhook/tg_auth.py"])
def test_polling_and_validator_share_resolver(rel):
    """`bot.py` (поллинг) и `tg_auth` (валидатор initData) берут токен из одного
    источника, иначе половинчатый `.env` снова разъедется (#201)."""
    src = (BOT_DIR / rel).read_text(encoding="utf-8")
    assert "resolve_bot_token()" in src
    assert 'os.getenv("BOT_TOKEN")' not in src
