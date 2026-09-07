"""Agent tools: user feedback flagging, listing, and admin triage."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from webhook.jwt_auth import get_db, require_agent_scope
from bot_token import resolve_bot_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent", tags=["agent-tools-feedback"])


class FlagForDevsRequest(BaseModel):
    category: str  # bug | feature | question
    user_msg: str
    agent_note: Optional[str] = None


class ListFeedbackRequest(BaseModel):
    # #269 триаж (admin-only): status=None/'all' → все статусы
    status: Optional[str] = "new"
    limit: int = 20


class TriageFeedbackRequest(BaseModel):
    # #269 триаж (admin-only): частичное обновление — передавай только меняемые поля
    feedback_id: int
    status: Optional[str] = None  # new/triaged/in_progress/done/wontfix/duplicate
    priority: Optional[str] = None  # P0-P3
    github_issue: Optional[str] = None
    # Фаза 3 (#188): явный текст ответа автору. Перекрывает авто-текст и уходит
    # пользователю при любом статусе — так `question` закрывается человеческим ответом.
    notify_text: Optional[str] = Field(None, max_length=3000)


@router.post("/flag_for_devs")
async def flag_for_devs(
    req: FlagForDevsRequest,
    user=Depends(require_agent_scope("rw")),
    db: Session = Depends(get_db),
):
    """Агент флагает пожелание/багрепорт в инбокс user_feedback (#188)."""
    from database.crud import create_feedback, is_feedback_opted_out

    kind = req.category if req.category in ("bug", "feature", "question") else "unspecified"

    if is_feedback_opted_out(db, user.telegram_id):
        return {"status": "skipped_opt_out"}

    row = create_feedback(
        db,
        user_id=user.telegram_id,
        text=req.user_msg,
        source="agent",
        kind=kind,
        agent_context={"agent_note": req.agent_note} if req.agent_note else None,
    )
    return {"status": "ok", "feedback_id": row.id, "kind": kind}


def _feedback_to_dict(row) -> dict:
    """Плоский структурный вид записи фидбека для агента (#269)."""
    ctx = row.agent_context if isinstance(row.agent_context, dict) else {}
    return {
        "id": row.id,
        "kind": row.kind,
        "status": row.status,
        "priority": row.priority,
        "source": row.source,
        "user_id": row.user_id,
        "text": row.text,
        "agent_note": ctx.get("agent_note"),
        "github_issue": row.github_issue,
        "dedup_of": row.dedup_of,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "notified_at": row.notified_at.isoformat() if row.notified_at else None,
    }


async def _send_feedback_notification(chat_id: int, text: str) -> bool:
    """Личное сообщение автору фидбека о разборе обращения (Фаза 3, #188). True при успехе.

    parse_mode НЕ задаём — текст плоский: в нём цитата пользователя, HTML-разметку
    включать нельзя (символ '<' в обращении иначе сломал бы разметку/инъектнул теги)."""
    import httpx

    bot_token = resolve_bot_token()
    if not bot_token:
        logger.warning("feedback-notify: bot token missing, cannot notify %s", chat_id)
        return False
    try:
        async with httpx.AsyncClient() as http:
            resp = await http.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
                timeout=10.0,
            )
        data = resp.json()
        if not data.get("ok"):
            logger.warning("feedback-notify sendMessage failed for %s: %s", chat_id, data.get("description"))
            return False
        return True
    except Exception as e:
        logger.error("feedback-notify exception for %s: %s", chat_id, e, exc_info=True)
        return False


@router.post("/list_feedback")
async def list_feedback(
    req: ListFeedbackRequest,
    user=Depends(require_agent_scope("ro")),
    db: Session = Depends(get_db),
):
    """Список записей инбокса фидбека для триажа (#269). Только для админов."""
    from config.users import is_admin
    from database.crud import list_recent_feedback

    if not is_admin(user.telegram_id):
        raise HTTPException(status_code=403, detail="триаж доступен только администраторам")
    status = req.status if req.status not in (None, "", "all") else None
    limit = max(1, min(req.limit, 100))
    rows = list_recent_feedback(db, status=status, limit=limit)
    return {"status": "ok", "count": len(rows), "feedback": [_feedback_to_dict(r) for r in rows]}


@router.post("/triage_feedback")
async def triage_feedback(
    req: TriageFeedbackRequest,
    user=Depends(require_agent_scope("rw")),
    db: Session = Depends(get_db),
):
    """Триаж записи фидбека: статус/приоритет/GitHub-issue (#269). Только для админов.

    Частичное обновление — применяются только переданные (не-None) поля.
    Возвращает обновлённую запись, чтобы агент подтвердил результат.
    """
    from config.users import is_admin
    from database.crud import (
        FEEDBACK_PRIORITIES,
        FEEDBACK_STATUSES,
        get_feedback,
        set_feedback_github,
        set_feedback_priority,
        update_feedback_status,
    )

    if not is_admin(user.telegram_id):
        raise HTTPException(status_code=403, detail="триаж доступен только администраторам")
    row = get_feedback(db, req.feedback_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"фидбек #{req.feedback_id} не найден")
    # #269: провалидировать ВСЕ поля ДО первой мутации — каждый CRUD-хелпер
    # коммитит отдельно, поэтому иначе невалидный priority после валидного status
    # оставил бы частичное изменение при ответе 400 (неатомарность).
    if req.status is not None and req.status not in FEEDBACK_STATUSES:
        raise HTTPException(status_code=400, detail=f"невалидный статус {req.status!r}")
    if req.priority is not None and req.priority not in FEEDBACK_PRIORITIES:
        raise HTTPException(status_code=400, detail=f"невалидный приоритет {req.priority!r}")
    if req.github_issue and len(req.github_issue) > 64:
        raise HTTPException(status_code=400, detail="github_issue слишком длинный (макс 64; передавай номер)")
    try:
        if req.status is not None:
            row = update_feedback_status(db, req.feedback_id, req.status)
        if req.priority is not None:
            row = set_feedback_priority(db, req.feedback_id, req.priority)
        if req.github_issue is not None:
            row = set_feedback_github(db, req.feedback_id, req.github_issue)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Фаза 3 (#188): уведомить автора, когда обращение разобрано (done/wontfix) или
    # когда админ явно ответил (notify_text). Идемпотентность — guard по notified_at:
    # штампуем ТОЛЬКО после успешной отправки, поэтому сбой сети → повтор на след. триаже,
    # а второй done по уже уведомлённой записи молча пропускается.
    from core.feedback_notify import build_notification_text
    from database.crud import is_feedback_opted_out, mark_feedback_notified

    notified = False
    notify_skipped: Optional[str] = None
    msg = build_notification_text(
        kind=row.kind,
        status=row.status,
        text=row.text,
        custom=req.notify_text,
    )
    if msg:
        if row.notified_at is not None:
            notify_skipped = "already_notified"
        elif is_feedback_opted_out(db, row.user_id):
            # opt-out = никаких исходящих контактов по фидбеку; не шлём и не штампуем.
            notify_skipped = "opt_out"
        elif await _send_feedback_notification(row.user_id, msg):
            mark_feedback_notified(db, row.id)
            db.refresh(row)
            notified = True
        else:
            notify_skipped = "send_failed"

    return {
        "status": "ok",
        "feedback": _feedback_to_dict(row),
        "notified": notified,
        "notify_skipped": notify_skipped,
    }
