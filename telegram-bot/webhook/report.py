"""GET /r/{token} — публичный HTML-отчёт пользователя (#203).

По аналогии с dashboard.py (GET /mc/{token}).
404 без подсказок для неизвестных токенов.
"""

import logging
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/r/{token}", response_class=HTMLResponse, include_in_schema=False)
async def public_report(token: str):
    """Отдать HTML-отчёт по публичному токену.

    Возвращает 404 для неизвестного/невалидного токена без пояснений.
    """
    from database import SessionLocal
    from services.report_generator import get_report_by_token

    db = SessionLocal()
    try:
        report = get_report_by_token(db, token)
        if report is None:
            raise HTTPException(status_code=404, detail="Not found")
        return HTMLResponse(content=report.html)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Report render error for token %s…: %s", token[:8], e, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error")
    finally:
        db.close()
