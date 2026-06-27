"""Telegram WebApp initData auth — shared between webhook modules.

Extracted from apple_health.py to avoid circular imports when other
webhook modules (e.g. nutrition_api) need get_tg_user as a dependency.
"""

import hashlib
import hmac
import json
import time
import urllib.parse

from fastapi import Header, HTTPException

from bot_token import resolve_bot_token

BOT_TOKEN = resolve_bot_token()

# initData считается просроченным через сутки (replay-защита): перехваченный
# токен не должен работать вечно. Telegram рекомендует такой TTL.
INIT_DATA_TTL_SEC = 24 * 3600


def verify_telegram_init_data(init_data_str: str) -> dict:
    """Validate Telegram WebApp initData HMAC + freshness, return user dict."""
    if not init_data_str:
        raise ValueError("Empty initData")

    params = dict(urllib.parse.parse_qsl(init_data_str, keep_blank_values=True))
    received_hash = params.pop("hash", None)
    if not received_hash:
        raise ValueError("No hash in initData")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed, received_hash):
        raise ValueError("initData HMAC mismatch")

    # Freshness: отвергаем initData старше суток (защита от replay перехваченного
    # токена). auth_date — unix-время выдачи Telegram'ом.
    try:
        auth_date = int(params.get("auth_date", "0"))
    except (TypeError, ValueError):
        auth_date = 0
    if auth_date <= 0 or (time.time() - auth_date) > INIT_DATA_TTL_SEC:
        raise ValueError("initData expired")

    return json.loads(params.get("user", "{}"))


def get_tg_user(authorization: str = Header(...)) -> dict:
    """FastAPI dependency: validates TMA token, returns Telegram user dict."""
    if not authorization.startswith("tma "):
        raise HTTPException(status_code=401, detail="Expected 'tma <initData>'")
    init_data = authorization.removeprefix("tma ").strip()
    try:
        return verify_telegram_init_data(init_data)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
