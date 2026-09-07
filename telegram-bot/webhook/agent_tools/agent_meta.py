"""Agent tools: agent self-correction log and open-questions tracker."""

import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from webhook.jwt_auth import get_agent_user, require_agent_scope
from .common import _resolve_user_kb_path

router = APIRouter(prefix="/api/agent", tags=["agent-tools-meta"])


_CORRECTION_KEY_RE = re.compile(r"^[a-zA-Z0-9_-]{1,100}$")


_CORRECTION_MAX_VALUE_LEN = 2000


class AgentCorrectionRequest(BaseModel):
    key: str = Field(..., description="Уникальный ключ факта (snake_case, ≤100 символов)")
    value: str = Field(..., description="Значение (≤2000 символов)")
    reason: str = Field("", description="Откуда факт — слова пользователя")


@router.post("/add_agent_correction")
async def add_agent_correction(
    req: AgentCorrectionRequest,
    user=Depends(require_agent_scope("rw")),
):
    """Сохранить поправку или новый факт в секцию agent_corrections KB пользователя.

    Агент должен вызывать этот endpoint СРАЗУ при получении корректирующей
    информации от пользователя (дата операции, диагноз, новый препарат и т.п.).
    Данные записываются в KB-файл — при следующем разговоре агент увидит их.

    Ключ — только [a-zA-Z0-9_-], длина ≤100. Значение — строка ≤2000 символов.
    При повторном вызове с тем же ключом значение обновляется.
    """
    import json
    import tempfile

    if not _CORRECTION_KEY_RE.match(req.key):
        raise HTTPException(
            status_code=422,
            detail=f"Недопустимый ключ '{req.key}': только буквы, цифры, _ и -, длина ≤100",
        )
    if len(req.value) > _CORRECTION_MAX_VALUE_LEN:
        raise HTTPException(
            status_code=422,
            detail=f"Значение слишком длинное: {len(req.value)} > {_CORRECTION_MAX_VALUE_LEN}",
        )

    kb_path, source = _resolve_user_kb_path(user)
    if kb_path is None or not kb_path.exists():
        raise HTTPException(status_code=404, detail=f"KB не найден для пользователя {user.telegram_id}")

    try:
        kb = json.loads(kb_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка чтения {source}: {e}")

    corrections = kb.setdefault("agent_corrections", {})
    corrections[req.key] = {
        "value": req.value,
        "reason": req.reason,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Атомарная запись через временный файл
    try:
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=kb_path.parent,
            suffix=".tmp",
            delete=False,
        )
        json.dump(kb, tmp, ensure_ascii=False, indent=2)
        tmp.flush()
        tmp.close()
        Path(tmp.name).replace(kb_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка записи KB: {e}")

    return {"status": "ok", "key": req.key, "source": source}


@router.get("/open_questions")
async def open_questions(user=Depends(get_agent_user)):
    """Открытые клинические вопросы и красные флаги из KB пользователя.

    Каждый человек ведёт «висящие» вопросы которые ждут решения врача,
    повторного анализа или клинического follow-up — например «K+/Mg+
    ни разу не сдавались при QTc 0.60», «микрогематурия 04.2025 без
    дообследования», «HbA1c на Метформине ни разу не измерен».

    Бот ДОЛЖЕН проактивно поднимать их при ЛЮБОМ медицинском вопросе,
    даже если пользователь спрашивает о другом. Прецедент 25.05.2026 —
    папа спрашивал «какие диагнозы» и «разбор анализов», бот корректно
    отвечал по факту, но НЕ упомянул что K/Mg/ТТГ должны быть в
    следующем заборе (хотя в его KB это давно как красный флаг).

    Источники в KB (бот пробует по очереди):
      1. `open_questions` (список строк) — у папы
      2. `open_issues` (список строк/dict) — альтернативное имя
      3. `urgent_problems` (dict с приоритетами) — если завели
      4. `red_flags` (список) — ещё один синоним

    Возвращает: {questions: [...], source: '<key>', count: N}.
    Если ничего не найдено — questions=[], source='not-tracked'.
    """
    kb_path, source = _resolve_user_kb_path(user)
    if kb_path is None or not kb_path.exists():
        return {"questions": [], "source": "kb-not-available", "count": 0}

    import json

    try:
        with open(kb_path, encoding="utf-8") as f:
            kb = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read {source}: {e}")

    # Try multiple known key names — у людей разные схемы
    candidates = ["open_questions", "open_issues", "urgent_problems", "red_flags"]
    for k in candidates:
        v = kb.get(k)
        if v is None:
            continue
        if isinstance(v, list) and len(v) > 0:
            return {"questions": v, "source": k, "count": len(v)}
        if isinstance(v, dict) and len(v) > 0:
            # Преобразуем dict в список «{приоритет}: {описание}» строк
            flattened = [f"{prio}: {desc}" for prio, desc in v.items()]
            return {"questions": flattened, "source": k, "count": len(flattened)}

    return {"questions": [], "source": "not-tracked", "count": 0}
