"""Agent tools: PAT→JWT bootstrap exchange, health-token regeneration."""

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from webhook.jwt_auth import get_db, require_agent_scope
from webhook.rate_limit import SlidingWindowRateLimiter

router = APIRouter(prefix="/api/agent", tags=["agent-tools-auth"])

# Лимит на публичный exchange: не больше 10 попыток в минуту с одного IP,
# чтобы перебор PAT по сети упирался в стену. Состояние в памяти процесса.
_EXCHANGE_RATE_LIMIT = 10
_EXCHANGE_RATE_WINDOW_S = 60.0
_exchange_limiter = SlidingWindowRateLimiter(_EXCHANGE_RATE_LIMIT, _EXCHANGE_RATE_WINDOW_S)


class ExchangePATRequest(BaseModel):
    pat: str = Field(..., min_length=10, max_length=128)


@router.post("/exchange_pat_for_jwt")
async def exchange_pat_for_jwt(
    body: ExchangePATRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Обменять долгоживущий PAT на короткоживущий агентский JWT.

    Единственный публичный (без JWT) эндпоинт. Коннектор Claude Desktop хранит
    durable PAT в keychain и дёргает этот метод, чтобы получить JWT для /api/agent/*.
    JWT наследует scope токена: 'ro'-PAT → 'ro'-JWT (write-эндпоинты вернут 403).
    """
    from database.crud import get_active_pat_by_token
    from database.models import User
    from core.agent_chat import agent_id_for
    from webhook.jwt_auth import generate_agent_jwt, JWT_TTL_HOURS

    from webhook.client_ip import client_ip as resolve_client_ip

    client_ip = resolve_client_ip(request)
    if not _exchange_limiter.allow(client_ip):
        raise HTTPException(status_code=429, detail="Слишком много запросов. Попробуйте через минуту.")

    # Bootstrap (ADR-0014): владелец PAT ещё не известен — поиск по хэшу токена
    # через system-сессию; дальше работаем в обычной сессии от его имени.
    from database import system_session
    from database.rls import bind_user

    with system_session() as sdb:
        pat = get_active_pat_by_token(sdb, body.pat)
        pat_user_id, pat_scope = (pat.user_id, pat.scope) if pat else (None, None)
    if pat_user_id is None:
        raise HTTPException(status_code=401, detail="Недействительный или отозванный токен")

    bind_user(db, pat_user_id)
    user = db.query(User).filter_by(telegram_id=pat_user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Пользователь не найден или неактивен")
    if not user.jwt_secret:
        raise HTTPException(status_code=401, detail="Пользователь не инициализирован (нет jwt_secret)")

    token = generate_agent_jwt(user.telegram_id, agent_id_for(user), user.jwt_secret, scope=pat_scope)
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": JWT_TTL_HOURS * 3600,
        "scope": pat_scope,
    }


@router.post("/regenerate_health_token")
async def regenerate_health_token(
    user=Depends(require_agent_scope("rw")),
    db: Session = Depends(get_db),
):
    """Generate a new health_token for the user and save it to users table."""
    new_token = f"hvt_{user.telegram_id}_{secrets.token_hex(16)}"
    user.health_token = new_token
    db.commit()

    return {
        "status": "ok",
        "health_token": new_token,
    }
