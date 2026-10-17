"""FastAPI router for the mini-app feedback button (#271).

Третий канал захвата инбокса обратной связи (#188), рядом с командой /feedback
и agent-инструментом flag_for_devs. Пользователь пишет баг/идею в настройках
мини-аппа → POST /api/feedback → та же запись в user_feedback (source='webapp').

Endpoint:
  POST /api/feedback
    JSON:      {"text": "...", "kind": "bug"|"feature"|"question"|"unspecified"}
    multipart: поля text, kind + до 3 файлов files (jpeg/png/heic/heif/webp/pdf, ≤10 МБ).
               Файлы в БД не кладём: пересылаем администратору в Telegram, в
               user_feedback.attachments — имя/MIME/размер и Telegram file_id.
    Требует валидный Telegram WebApp initData (get_tg_user).
    Уважает opt-out (is_feedback_opted_out) — как командный и агентский каналы.
"""

import logging
import os
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError, field_validator

from webhook.tg_auth import get_tg_user

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_FILES = 3
MAX_FILE_BYTES = 10 * 1024 * 1024
ALLOWED_MIME = {"image/jpeg", "image/png", "image/heic", "image/heif", "image/webp", "application/pdf"}
# Если браузер не передал content-type (бывает с HEIC) — определяем по расширению.
_EXT_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
}
# Telegram не показывает HEIC/HEIF как фото — их шлём документом.
_PHOTO_MIME = {"image/jpeg", "image/png", "image/webp"}
_NOTIFY_TEXT_LIMIT = 1000

FeedbackKind = Literal["bug", "feature", "question", "unspecified"]


class FeedbackPayload(BaseModel):
    text: str = Field(..., max_length=4000)
    kind: FeedbackKind = "unspecified"

    @field_validator("text")
    @classmethod
    def _strip_nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("text must not be empty")
        return v


def _make_bot():
    """aiogram Bot для разовой отправки админу; None, если токен не задан."""
    from aiogram import Bot

    from bot_token import resolve_bot_token

    token = resolve_bot_token()
    return Bot(token=token) if token else None


def _admin_id() -> int:
    from config.users import ADMIN_USER_ID

    return ADMIN_USER_ID


def _normalize_mime(filename: str, content_type: Optional[str]) -> str:
    mime = (content_type or "").split(";")[0].strip().lower()
    if mime and mime != "application/octet-stream":
        return mime
    return _EXT_MIME.get(os.path.splitext(filename or "")[1].lower(), mime)


async def _read_files(form) -> list[dict]:
    """Прочитать и провалидировать вложения из multipart-формы."""
    uploads = [f for f in form.getlist("files") if hasattr(f, "read")]
    if len(uploads) > MAX_FILES:
        raise HTTPException(status_code=422, detail=f"Не больше {MAX_FILES} файлов")
    files = []
    for up in uploads:
        name = os.path.basename(up.filename or "file")
        mime = _normalize_mime(name, up.content_type)
        if mime not in ALLOWED_MIME:
            raise HTTPException(status_code=422, detail=f"Тип файла не поддерживается: {name}")
        data = await up.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail=f"Файл больше 10 МБ: {name}")
        if not data:
            raise HTTPException(status_code=422, detail=f"Пустой файл: {name}")
        files.append({"name": name, "mime": mime, "size": len(data), "data": data})
    return files


async def _notify_admin(user_id: int, kind: str, text: str, files: list[dict]) -> list[dict]:
    """Переслать фидбек и вложения админу в Telegram. Возвращает метаданные с file_id.

    Best-effort: любой сбой логируется, исключения наружу не летят (запись фидбека
    уже сохранена, ответ пользователю не должен зависеть от Telegram).
    """
    meta = [{k: f[k] for k in ("name", "mime", "size")} for f in files]
    admin_id = _admin_id()
    if not admin_id:
        logger.warning("feedback: администратор не настроен (BOTKIN_ADMIN_IDS), %d вложений не отправлено", len(files))
        return meta
    bot = None
    try:
        bot = _make_bot()
        if bot is None:
            logger.warning("feedback: нет токена бота, %d вложений не отправлено", len(files))
            return meta
        from aiogram.types import BufferedInputFile

        shown = text if len(text) <= _NOTIFY_TEXT_LIMIT else text[:_NOTIFY_TEXT_LIMIT] + "…"
        await bot.send_message(admin_id, f"Фидбек из мини-аппа ({kind}) от {user_id}:\n\n{shown}")
        for f, m in zip(files, meta):
            doc = BufferedInputFile(f["data"], filename=f["name"])
            try:
                if f["mime"] in _PHOTO_MIME:
                    try:
                        msg = await bot.send_photo(admin_id, doc, caption=f["name"])
                        m["file_id"] = msg.photo[-1].file_id
                        continue
                    except Exception:
                        logger.warning("feedback: send_photo не удался, шлю документом", exc_info=True)
                        doc = BufferedInputFile(f["data"], filename=f["name"])
                msg = await bot.send_document(admin_id, doc, caption=f["name"])
                m["file_id"] = msg.document.file_id
            except Exception:
                logger.exception("feedback: не удалось отправить вложение %s", f["name"])
    except Exception:
        logger.exception("feedback: не удалось уведомить администратора")
    finally:
        if bot is not None:
            try:
                await bot.session.close()
            except Exception:
                pass
    return meta


@router.post("/api/feedback")
async def post_feedback(
    request: Request,
    tg_user: dict = Depends(get_tg_user),
):
    """Записать фидбек из мини-аппа в общий инбокс (#188). JSON или multipart с вложениями."""
    user_id = tg_user.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="No user id in initData")

    files: list[dict] = []
    try:
        if (request.headers.get("content-type") or "").lower().startswith("multipart/form-data"):
            form = await request.form()
            payload = FeedbackPayload(text=str(form.get("text") or ""), kind=str(form.get("kind") or "unspecified"))
            files = await _read_files(form)
        else:
            payload = FeedbackPayload(**(await request.json()))
    except ValidationError as e:
        raise HTTPException(
            status_code=422, detail=e.errors(include_url=False, include_context=False, include_input=False)
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=422, detail="Некорректное тело запроса")

    # Импорт внутри хендлера — чтобы тесты могли подменить database.SessionLocal.
    from database import SessionLocal
    from database.crud import create_feedback, is_feedback_opted_out, set_feedback_attachments

    db = SessionLocal()
    try:
        # Тот же opt-out-гейт, что у командного и агентского каналов захвата.
        if is_feedback_opted_out(db, user_id):
            return {"status": "opted_out"}
        meta = [{k: f[k] for k in ("name", "mime", "size")} for f in files] or None
        row = create_feedback(
            db,
            user_id=user_id,
            text=payload.text,
            source="webapp",
            kind=payload.kind,
            attachments=meta,
        )
        row_id = row.id
    finally:
        db.close()

    # Telegram — после закрытия транзакции БД (не держим tx поперёк сети).
    # Админа уведомляем о каждом фидбеке из мини-аппа — иначе текстовый фидбек
    # молча копится в user_feedback. Вложения (если есть) — следом.
    meta = await _notify_admin(user_id, payload.kind, payload.text, files)
    if files:
        if any("file_id" in m for m in meta):
            db = SessionLocal()
            try:
                set_feedback_attachments(db, row_id, meta)
            except Exception:
                logger.exception("feedback: не удалось сохранить file_id вложений (id=%s)", row_id)
            finally:
                db.close()
    return {"status": "ok", "id": row_id}
