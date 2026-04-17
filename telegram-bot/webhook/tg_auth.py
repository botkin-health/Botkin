"""Telegram WebApp initData auth — shared between webhook modules.

Extracted from apple_health.py to avoid circular imports when other
webhook modules (e.g. nutrition_api) need get_tg_user as a dependency.
"""

import hashlib
import hmac
import json
import os
import urllib.parse

from fastapi import Header, HTTPException

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN", "")


def verify_telegram_init_data(init_data_str: str) -> dict:
    """Validate Telegram WebApp initData HMAC and return user dict."""
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
