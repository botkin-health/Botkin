"""JWT authentication для BotkinClaw → FastAPI tools API.

BotkinClaw — in-process AI-агент внутри @Botkin_md_bot (см. ADR-0002,
заменил NanoClaw). Бот сам подписывает JWT и сам же его валидирует, но JWT-
контракт сохранён — пригодится если когда-нибудь снова появятся внешние
агенты (Claude Desktop через MCP, etc).

Контракт:
- payload = {user_id, container_id, exp, iat}
- jwt_secret хранится в users.jwt_secret (per-user)
- container_id — agent identifier через core.agent_chat.agent_id_for(user):
  либо устаревшее значение из users.container_id (для legacy NanoClaw-юзеров),
  либо деривированное `botkinclaw-{telegram_id}`. Обе стороны (подпись и
  валидация) используют одну и ту же функцию, поэтому всегда сходятся.

Security: container_id mismatch → 403. Защищает от replay-атаки если JWT
утечёт между пользователями.
"""

import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

JWT_TTL_HOURS = int(os.getenv("AGENT_JWT_TTL_HOURS", "1"))


def get_db():
    """FastAPI dependency: yield a DB session and always close it on exit."""
    from database import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def generate_agent_jwt(user_id: int, container_id: str, secret: str) -> str:
    """Generate a JWT for a NanoClaw container.

    Called at container startup. Rotated when health_token is regenerated.
    """
    payload = {
        "user_id": user_id,
        "container_id": container_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_TTL_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


async def get_agent_user(
    authorization: str = Header(...),
    db: Session = Depends(get_db),
):
    """FastAPI dependency: validate agent JWT, return User row.

    Usage:
        @router.post("/some/endpoint")
        async def endpoint(user=Depends(get_agent_user)):
            ...

    Raises:
        401: missing/malformed/expired token or user not found
        403: container_id mismatch (impersonation attempt)
    """
    # Import here to avoid circular imports and to support testing with mocks
    from database.models import User
    from database.crud import set_user_session_var

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization[7:]

    # Decode without verification to extract user_id (need it to fetch their secret)
    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Malformed JWT")

    user_id = unverified.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="JWT missing user_id claim")

    user = db.query(User).filter_by(telegram_id=user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    if not user.jwt_secret:
        raise HTTPException(status_code=401, detail="User not provisioned (no jwt_secret)")

    # Now verify with user's actual secret
    try:
        verified = jwt.decode(token, user.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="JWT expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="JWT signature invalid")

    # Derive expected agent_id the same way agent_chat.py does — so payload
    # always matches even когда users.container_id NULL (новые пользователи
    # после удаления NanoClaw, см. ADR-0002).
    from core.agent_chat import agent_id_for

    if verified.get("container_id") != agent_id_for(user):
        raise HTTPException(status_code=403, detail="agent_id mismatch")

    # Set RLS session variable for any DB queries in this request
    set_user_session_var(db, user.telegram_id)

    return user
