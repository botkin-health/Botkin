"""Tests for JWT auth middleware (BotkinClaw in-process agent).

Originally written for NanoClaw spawn-containers (see ADR-0001), now used by
BotkinClaw. The container_id JWT-claim contract is preserved — agent_id_for()
either uses users.container_id (legacy non-NULL) or derives botkinclaw-{id}.
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


def test_agent_id_for_falls_back_to_derived():
    """When users.container_id is NULL — agent_id_for derives botkinclaw-{id}.

    Это критичный contract после ADR-0002: новые пользователи приходят без
    предзаполненного container_id (раньше его ставил NanoClaw provisioning).
    """
    from core.agent_chat import agent_id_for

    # Legacy user — non-NULL container_id used as-is
    legacy = MagicMock(telegram_id=REDACTED_ID, container_id="in-process-andrey")
    assert agent_id_for(legacy) == "in-process-andrey"

    # New user — NULL → derived
    fresh = MagicMock(telegram_id=895655, container_id=None)
    assert agent_id_for(fresh) == "botkinclaw-895655"

    # Empty string also treated as falsy → derived (defensive)
    empty = MagicMock(telegram_id=111, container_id="")
    assert agent_id_for(empty) == "botkinclaw-111"


@pytest.mark.asyncio
async def test_get_agent_user_works_with_null_container_id():
    """User with NULL container_id can authenticate via derived agent_id."""
    from core.agent_chat import _generate_jwt

    user = MagicMock(telegram_id=895655, jwt_secret=TEST_SECRET, is_active=True, container_id=None)
    # Agent generates JWT using derived id
    token = _generate_jwt(user)

    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = user

    result = await get_agent_user(authorization=f"Bearer {token}", db=db)
    assert result.telegram_id == 895655
