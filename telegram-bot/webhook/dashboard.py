"""
HealthVault Share Dashboard — FastAPI endpoint.
GET /mc/{token} → персональный HTML-дашборд пользователя.
"""

import logging
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/mc/{token}", response_class=HTMLResponse, include_in_schema=False)
async def share_dashboard(token: str, embed: bool = False):
    """Render personal health dashboard for the given share token.

    Returns 404 for unknown/invalid tokens — no hints about why.

    embed=1 (mini-app iframe): renders a scale-to-fit variant for narrow screens.
    Without the param the standalone/shared dashboard renders unchanged.
    """
    from database import SessionLocal, system_session
    from database.crud import get_user_by_share_token
    from database.rls import bind_user
    from dashboard_generator import generate_dashboard_html

    # Bootstrap (ADR-0014): кто владелец токена — до того, как пользователь
    # известен, поэтому через system-сессию; наружу выходит только telegram_id.
    with system_session() as sdb:
        owner = get_user_by_share_token(sdb, token)
        owner_id = owner.telegram_id if owner is not None and owner.is_active else None
    if owner_id is None:
        raise HTTPException(status_code=404, detail="Not found")

    db = SessionLocal()
    bind_user(db, owner_id)
    try:
        html = generate_dashboard_html(db, owner_id, embed=embed)
        return HTMLResponse(content=html)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Dashboard render error for token {token[:8]}…: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error")
    finally:
        db.close()
