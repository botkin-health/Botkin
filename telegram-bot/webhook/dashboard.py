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
async def share_dashboard(token: str):
    """Render personal health dashboard for the given share token.

    Returns 404 for unknown/invalid tokens — no hints about why.
    """
    from database import SessionLocal
    from database.crud import get_user_by_share_token
    from dashboard_generator import generate_dashboard_html

    db = SessionLocal()
    try:
        user = get_user_by_share_token(db, token)
        if not user or not user.is_active:
            raise HTTPException(status_code=404, detail="Not found")
        html = generate_dashboard_html(db, user.telegram_id)
        return HTMLResponse(content=html)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Dashboard render error for token {token[:8]}…: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error")
    finally:
        db.close()
