"""Agent tools: knowledge_base.json value lookup for the LLM."""

from fastapi import APIRouter, Depends, HTTPException

from webhook.jwt_auth import get_agent_user
from .common import _resolve_user_kb_path

router = APIRouter(prefix="/api/agent", tags=["agent-tools-kb"])


@router.get("/kb_value")
async def kb_value(
    key: str,
    user=Depends(get_agent_user),
):
    """Look up a value in knowledge_base.json by key path.

    Resolution order:
      1. Per-user KB at `kb_<telegram_id>.json` at repo root (any cohort) —
         synced from FamilyHealth/<user>/knowledge_base.json on demand.
      2. Owner-cohort fallback: legacy `knowledge_base.json` (Alex-only).
      3. Otherwise: returns null with source='kb-not-available'.
    """
    kb_path, source = _resolve_user_kb_path(user)
    if kb_path is None:
        return {"key": key, "value": None, "source": source}  # "kb-not-available"

    import json

    try:
        with open(kb_path, encoding="utf-8") as f:
            kb = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read {source}: {e}")

    # Support dot-notation path traversal: e.g. "blood_tests.0.values.cholesterol"
    value = kb
    for part in key.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list):
            try:
                value = value[int(part)]
            except (ValueError, IndexError):
                value = None
        else:
            value = None
        if value is None:
            break

    return {"key": key, "value": value, "source": source}


@router.get("/list_kb_keys")
async def list_kb_keys(user=Depends(get_agent_user)):
    """Top-level keys present in this user's knowledge_base.

    Возвращает реальный список ключей именно этого юзера — у разных людей
    схемы расходятся (у Андрея есть `echocardiogram`/`current_medications`,
    у Павла — `mrt`/`tumor_markers`, у Александра — `cardio`/`endoscopy`).
    Агент должен звать это перед `get_kb_value`, чтобы не гадать.

    Для каждого ключа отдаём type (list/dict/scalar) и count (длина для
    list/dict), чтобы агент понимал где искать. Служебные ключи `_*`
    и крупные дампы (`apple_health`, `cgm_data`) фильтруются.

    Секция `documents` — файлы, загруженные пользователем через /doc
    (`handlers/doc_upload.append_document_to_kb`). Числовые лабораторные
    показатели из них дублируются в Postgres `blood_tests` (#281), поэтому
    за анализами агент идёт в /recent_biomarkers, а сюда — за самим документом.
    """
    kb_path, source = _resolve_user_kb_path(user)
    if kb_path is None:
        return {"keys": [], "source": source}  # "kb-not-available"

    if not kb_path.exists():
        return {"keys": [], "source": "kb-not-found"}

    import json

    try:
        with open(kb_path, encoding="utf-8") as f:
            kb = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read {source}: {e}")

    SKIP = {"apple_health", "cgm_data", "pdf_files", "_changelog"}
    keys = []
    for k, v in kb.items():
        if k.startswith("_") or k in SKIP:
            continue
        if isinstance(v, list):
            t, n = "list", len(v)
        elif isinstance(v, dict):
            t, n = "dict", len(v)
        else:
            t, n = "scalar", None
        # пустые секции тоже показываем — пусть агент видит что нет данных
        keys.append({"key": k, "type": t, "count": n})

    return {"keys": keys, "source": source, "total": len(keys)}
