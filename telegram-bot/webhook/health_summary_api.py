"""GET /api/health/summary — вкладка «Состояние» миниаппа: что обратить внимание + карточки потоков.

Авторизация — WebApp initData (get_tg_user). Все расчёты — services/health_summary.py
(детерминированные правила, без LLM). Схема и контракт «нет потока» — services/health_summary_schema.py.

Ошибки: нет id в initData → 400; нет пользователя в БД → 200, `onboarding=true`, `streams={}`.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from webhook.tg_auth import get_tg_user

router = APIRouter()


@router.get("/api/health/summary")
async def get_health_summary(
    days: int = Query(7, ge=7, le=30),
    lang: Optional[str] = Query(None),
    tg_user: dict = Depends(get_tg_user),
):
    user_id = tg_user.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="No user id in initData")

    # Импорты внутри хендлера — чтобы тесты могли подменить database.SessionLocal.
    from database import SessionLocal
    from services.health_summary import build_health_summary
    from services.report_i18n import resolve_report_language

    language = resolve_report_language(lang, tg_user.get("language_code"))
    db = SessionLocal()
    try:
        summary = build_health_summary(db, user_id, days=days, lang=language)
    finally:
        db.close()
    return summary.model_dump(mode="json")
