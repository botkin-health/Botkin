"""Agent tools: внутридневная хронология пульса/стресса/Body Battery."""

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from webhook.agent_tools.common import _get_user_tz, _parse_date
from webhook.jwt_auth import get_agent_user, get_db

router = APIRouter(prefix="/api/agent", tags=["agent-tools-intraday"])


@router.get("/intraday")
async def intraday(date: str | None = None, user=Depends(get_agent_user), db: Session = Depends(get_db)):
    """Получасовые корзины пульса/стресса/Body Battery за день + эпизоды стресса.

    Перед сетевым вызовом к Garmin закрываем транзакцию, которую открыл
    get_agent_user (анти-паттерн «транзакция поперёк сетевого вызова», CLAUDE.md):
    атрибуты пользователя читаем до rollback.
    """
    import asyncio

    from core.health.intraday import get_intraday

    day = _parse_date(date, user).isoformat()
    offset = datetime.now(_get_user_tz(user)).utcoffset()
    uid = int(user.telegram_id)
    db.rollback()
    return await asyncio.get_running_loop().run_in_executor(None, get_intraday, uid, day, offset)
