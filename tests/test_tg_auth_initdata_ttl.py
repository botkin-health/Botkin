"""Характеризующие + security тесты Telegram WebApp initData.

Валидный свежий initData должен проходить и до, и после фикса. Просроченный
(>24ч) сейчас принимается (нет TTL-проверки) — после фикса должен отвергаться.
"""

import hashlib
import hmac
import sys
import time
import urllib.parse
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))


def _make_init_data(auth_date: int) -> str:
    """Строит валидный по HMAC initData с заданным auth_date."""
    from webhook import tg_auth

    params = {
        "user": '{"id":895655,"first_name":"Sasha"}',
        "auth_date": str(auth_date),
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", tg_auth.BOT_TOKEN.encode(), hashlib.sha256).digest()
    h = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()
    params["hash"] = h
    return urllib.parse.urlencode(params)


# ── Характеризующие: валидный свежий initData проходит ───────────────────────
def test_fresh_initdata_valid():
    from webhook import tg_auth

    init = _make_init_data(int(time.time()))
    user = tg_auth.verify_telegram_init_data(init)
    assert user["id"] == 895655


def test_tampered_hash_rejected():
    from webhook import tg_auth

    init = _make_init_data(int(time.time())) + "0"  # портим hash
    with pytest.raises(ValueError):
        tg_auth.verify_telegram_init_data(init)


def test_empty_initdata_rejected():
    from webhook import tg_auth

    with pytest.raises(ValueError):
        tg_auth.verify_telegram_init_data("")


# ── Security: просроченный initData отвергается (RED сейчас → GREEN) ──────────
def test_expired_initdata_rejected():
    """initData старше 24ч должен отвергаться (replay-защита).

    Сейчас TTL не проверяется → валидный HMAC со старым auth_date принимается.
    После фикса — ValueError.
    """
    from webhook import tg_auth

    old = int(time.time()) - 25 * 3600  # 25 часов назад
    init = _make_init_data(old)
    with pytest.raises(ValueError):
        tg_auth.verify_telegram_init_data(init)
