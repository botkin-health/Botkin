"""JWT authentication для BotkinClaw → FastAPI tools API.

BotkinClaw — in-process AI-агент внутри @Botkin_md_bot (см. ADR-0002,
заменил NanoClaw). Бот сам подписывает JWT и сам же его валидирует, но JWT-
контракт сохранён — пригодится если когда-нибудь снова появятся внешние
агенты (Claude Desktop через MCP, etc).

Контракт:
- payload = {user_id, container_id, scope, exp, iat, iss, aud}
- iss/aud = botkin-<env> / botkin-agent-api-<env> (core.env, ADR-0013)
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
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from core.env import agent_jwt_env_claims, jwt_audience, jwt_issuer

JWT_TTL_HOURS = int(os.getenv("AGENT_JWT_TTL_HOURS", "1"))

# Допустимые scope для агентских токенов. 'rw' — полный доступ (личный токен
# владельца, in-process BotkinClaw); 'ro' — только чтение (токен, которым владелец
# делится с врачом/близким через MCP-коннектор, #228). Legacy-токены без claim
# трактуются как 'rw' (поведение до #228 не меняется).
DEFAULT_SCOPE = "rw"


def get_db():
    """FastAPI dependency: yield a DB session and always close it on exit."""
    from database import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def generate_agent_jwt(user_id: int, container_id: str, secret: str, scope: str = DEFAULT_SCOPE) -> str:
    """Generate a JWT for an agent (in-process BotkinClaw or MCP-коннектор).

    Called at container startup / при обмене PAT. Rotated when health_token is regenerated.
    scope: 'rw' (полный) или 'ro' (только чтение, см. #228). По умолчанию 'rw' —
    обратная совместимость с in-process агентом, который не передаёт scope.
    """
    payload = {
        "user_id": user_id,
        "container_id": container_id,
        "scope": scope,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_TTL_HOURS),
        "iat": datetime.now(timezone.utc),
        **agent_jwt_env_claims(),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


async def get_agent_user(
    authorization: str = Header(...),
    db: Session = Depends(get_db),
    request: Request = None,
):
    """FastAPI dependency: validate agent JWT, return User row.

    Usage:
        @router.post("/some/endpoint")
        async def endpoint(user=Depends(get_agent_user)):
            ...

    Кладёт верифицированный scope ('ro'/'rw') в request.state.agent_scope, откуда
    его читает require_agent_scope. request опционален: прямые вызовы в тестах идут
    без него (scope тогда не сохраняется, но проверки scope в таких тестах нет).

    Raises:
        401: missing/malformed/expired token or user not found
        403: container_id mismatch (impersonation attempt)
    """
    # Import here to avoid circular imports and to support testing with mocks
    from database.models import User
    from database.rls import bind_user

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

    # RLS (ADR-0014): строку users под hv_app видно только «изнутри» контекста.
    # Подпись ещё не проверена, но читаем только строку заявленного
    # пользователя (за его jwt_secret); при неверной подписи запрос упадёт 401.
    bind_user(db, int(user_id))
    user = db.query(User).filter_by(telegram_id=user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    if not user.jwt_secret:
        raise HTTPException(status_code=401, detail="User not provisioned (no jwt_secret)")

    # Now verify with user's actual secret. iss/aud обязательны и привязаны к
    # окружению (ADR-0013): токен прода не проходит на деве и наоборот, даже если
    # per-user jwt_secret совпал (раньше дев держал копию прод-секретов).
    try:
        verified = jwt.decode(
            token,
            user.jwt_secret,
            algorithms=["HS256"],
            issuer=jwt_issuer(),
            audience=jwt_audience(),
            options={"require": ["exp", "iat", "iss", "aud"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="JWT expired")
    except (jwt.InvalidIssuerError, jwt.InvalidAudienceError):
        raise HTTPException(status_code=401, detail="JWT issued for another environment")
    except jwt.MissingRequiredClaimError:
        raise HTTPException(status_code=401, detail="JWT missing required claim")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="JWT signature invalid")

    # Derive expected agent_id the same way agent_chat.py does — so payload
    # always matches even когда users.container_id NULL (новые пользователи
    # после удаления NanoClaw, см. ADR-0002).
    from core.agent_chat import agent_id_for

    if verified.get("container_id") != agent_id_for(user):
        raise HTTPException(status_code=403, detail="agent_id mismatch")

    # Scope берём ТОЛЬКО из верифицированного payload (не из unverified — иначе
    # подделка). Legacy-токены без claim → 'rw'. Кладём в request.state для
    # require_agent_scope.
    scope = verified.get("scope", DEFAULT_SCOPE)
    if request is not None:
        request.state.agent_scope = scope

    # RLS-контекст на весь запрос: session.info переживает commit(), contextvar —
    # для сессий, которые тул откроет сам (get_daily_budget, get_user_tz, …).
    bind_user(db, user.telegram_id)

    return user


def require_agent_scope(required_scope: str):
    """Фабрика FastAPI-зависимости: пускает только если у токена нужный scope.

    Навешивается на мутирующие эндпоинты:
        @router.post("/log_meal_text")
        async def log_meal_text(req, user=Depends(require_agent_scope("rw"))):
            ...

    'ro'-токен (которым владелец поделился с врачом) на write-эндпоинте → 403.
    Сначала отрабатывает get_agent_user (валидация JWT + RLS), затем проверяется
    scope из request.state. Если scope не выставлен (напр. get_agent_user
    замокан в тесте) — считаем 'rw', чтобы не ломать существующие тесты.
    """

    async def _checker(request: Request, user=Depends(get_agent_user)):
        scope = getattr(request.state, "agent_scope", DEFAULT_SCOPE)
        if required_scope == "rw" and scope != "rw":
            raise HTTPException(
                status_code=403,
                detail="Токен только для чтения (ro). Изменение данных требует токена с правом записи (rw).",
            )
        return user

    return _checker
