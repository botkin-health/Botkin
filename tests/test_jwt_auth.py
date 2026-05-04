"""Tests for JWT auth middleware (NanoClaw agent containers).

TDD — tests written before implementation.
"""

import sys
from pathlib import Path

# Add project root so 'database' module is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Add telegram-bot so 'webhook' package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

import jwt
import pytest
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from unittest.mock import MagicMock

from webhook.jwt_auth import get_agent_user, generate_agent_jwt


TEST_SECRET = "test_secret_64chars_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"


def test_generate_and_decode_jwt():
    token = generate_agent_jwt(user_id=895655, container_id="nc-test", secret=TEST_SECRET)
    decoded = jwt.decode(token, TEST_SECRET, algorithms=["HS256"])
    assert decoded["user_id"] == 895655
    assert decoded["container_id"] == "nc-test"
    assert "exp" in decoded


@pytest.mark.asyncio
async def test_get_agent_user_valid():
    token = generate_agent_jwt(user_id=895655, container_id="nc-test", secret=TEST_SECRET)
    db = MagicMock()
    user = MagicMock(telegram_id=895655, container_id="nc-test", jwt_secret=TEST_SECRET, is_active=True)
    db.query.return_value.filter_by.return_value.first.return_value = user

    result = await get_agent_user(authorization=f"Bearer {token}", db=db)
    assert result.telegram_id == 895655


@pytest.mark.asyncio
async def test_get_agent_user_expired():
    token = jwt.encode(
        {"user_id": 895655, "container_id": "nc-test", "exp": datetime.now(timezone.utc) - timedelta(hours=1)},
        TEST_SECRET,
        algorithm="HS256",
    )
    db = MagicMock()
    user = MagicMock(telegram_id=895655, jwt_secret=TEST_SECRET, is_active=True, container_id="nc-test")
    db.query.return_value.filter_by.return_value.first.return_value = user

    with pytest.raises(HTTPException) as exc:
        await get_agent_user(authorization=f"Bearer {token}", db=db)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_agent_user_wrong_container():
    """JWT with container_id mismatch — reject with 403."""
    token = generate_agent_jwt(user_id=895655, container_id="nc-attacker", secret=TEST_SECRET)
    db = MagicMock()
    user = MagicMock(telegram_id=895655, jwt_secret=TEST_SECRET, is_active=True, container_id="nc-sasha")
    db.query.return_value.filter_by.return_value.first.return_value = user

    with pytest.raises(HTTPException) as exc:
        await get_agent_user(authorization=f"Bearer {token}", db=db)
    assert exc.value.status_code == 403
