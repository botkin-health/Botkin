"""Agent tools: документы профиля пользователя (issue #370) — список,
переименование/категоризация и отправка файла назад пользователю в Telegram.

Метаданные (`title`/`category`) и разрешение id → путь на диске —
`core.health.profile_documents` (без Telegram-зависимостей). Здесь —
только HTTP-обвязка с JWT-аутентификацией и side-effect отправки в Telegram
(тот же паттерн, что `render_report` в `reports.py`).
"""

import logging
from typing import Optional

import requests as _requests
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from bot_token import resolve_bot_token
from webhook.jwt_auth import require_agent_scope

from core.health.profile_documents import (
    CATEGORIES,
    DocumentNotFoundError,
    list_documents as _list_documents,
    resolve_document_path,
    update_document as _update_document,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent", tags=["agent-tools-documents"])


@router.get("/list_documents")
async def list_documents(user=Depends(require_agent_scope("ro"))):
    """Документы профиля пользователя (issue #370): и лабораторные (из /doc),
    и общие «на всякий случай» (полис, справка, визитка врача и т.п.),
    новые сверху. Каждый: id, title, category, added_at, is_lab.

    Зови перед `send_document` — чтобы найти нужный id по названию/категории.
    """
    docs = _list_documents(user.telegram_id)
    return {"status": "ok", "documents": docs, "total": len(docs)}


class UpdateDocumentRequest(BaseModel):
    title: Optional[str] = Field(None, description="Человекочитаемое название, напр. «Полис ОМС»")
    category: Optional[str] = Field(
        None,
        description=f"Одна из: {', '.join(CATEGORIES)}",
    )


@router.post("/update_document")
async def update_document(
    document_id: str,
    req: UpdateDocumentRequest,
    user=Depends(require_agent_scope("rw")),
):
    """Проставить/поменять title и/или category у уже сохранённого документа.

    Зови сразу после того, как пользователь попросил сохранить документ
    «про запас» (фото полиса, справки, памятки) — не отказывай, документ уже
    лежит в архиве, но название вида «Документ от 2026-08-12» неинформативно.
    Уточни у пользователя, если не очевидно, и запиши title/category здесь.

    document_id — id из `list_documents`. Неизвестный id или чужой документ →
    ошибка с понятным сообщением.
    """
    if req.title is None and req.category is None:
        return {"status": "noop", "reason": "no fields provided"}
    try:
        result = _update_document(user.telegram_id, document_id, title=req.title, category=req.category)
    except DocumentNotFoundError as e:
        return {"status": "error", "error": str(e)}
    except ValueError as e:
        return {"status": "error", "error": str(e)}
    return {"status": "ok", "document": result}


class SendDocumentRequest(BaseModel):
    document_id: str = Field(..., description="id документа из list_documents")


@router.post("/send_document")
async def send_document(
    req: SendDocumentRequest,
    user=Depends(require_agent_scope("ro")),
):
    """Прислать пользователю обратно в Telegram ранее сохранённый документ
    профиля (полис, справка, анализ и т.п.) — issue #370.

    Side-effect: sendPhoto (для .jpg/.jpeg/.png) или sendDocument (иначе) через
    Bot API на user.telegram_id. Подпись — title документа. Зови когда
    пользователь просит «покажи/пришли мой полис/справку/документ».
    """
    try:
        path = resolve_document_path(user.telegram_id, req.document_id)
    except DocumentNotFoundError as e:
        return {"status": "error", "error": str(e), "sent": False}

    docs = {d["id"]: d for d in _list_documents(user.telegram_id)}
    title = (docs.get(req.document_id) or {}).get("title") or path.name

    bot_token = resolve_bot_token()
    if not bot_token:
        return {"status": "error", "error": "bot-token-missing", "sent": False}

    is_image = path.suffix.lower() in (".jpg", ".jpeg", ".png")
    method = "sendPhoto" if is_image else "sendDocument"
    field = "photo" if is_image else "document"

    try:
        content = path.read_bytes()
        resp = _requests.post(
            f"https://api.telegram.org/bot{bot_token}/{method}",
            data={"chat_id": user.telegram_id, "caption": title},
            files={field: (path.name, content, "application/octet-stream")},
            timeout=20,
        )
        result = resp.json()
        if not result.get("ok"):
            logger.warning("%s failed for document %s: %s", method, req.document_id, result)
            return {"status": "error", "error": f"telegram: {result.get('description')}", "sent": False}
    except Exception as e:
        logger.error("%s exception for document %s: %s", method, req.document_id, e, exc_info=True)
        return {"status": "error", "error": f"send-failed: {e}", "sent": False}

    return {"status": "ok", "sent": True, "title": title}
