"""Извлечение медицинских значений из документа через Claude (#227).

Принимает текст PDF или изображение (скан/фото бланка), возвращает dict:

    {
        "date": "2026-04-13" | None,
        "laboratory": "KDL" | None,
        "values": {"Гемоглобин": "165 г/л", ...},   # пусто если ничего не нашли
        "doc_type": "анализ крови" | ...,
    }

Пустой ``values`` — валидный результат (спека: «сохранить как архив»).
Дизайн: docs/architecture/2026-06-28-user-kb-self-onboarding-design.md
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re

import requests

from config.models import AGENT_MODEL

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MAX_TOKENS = 1500
TIMEOUT_S = 120

_EXTRACT_PROMPT = (
    "Ты — парсер медицинских документов. Извлеки из документа данные и верни "
    "ТОЛЬКО JSON без пояснений, в формате:\n"
    '{"date": "YYYY-MM-DD или null", "laboratory": "название лаборатории/клиники или null", '
    '"doc_type": "анализ крови / УЗИ / заключение врача / другое", '
    '"values": {"Название показателя": "значение с единицами", ...}}\n\n'
    "В values клади ТОЛЬКО реально присутствующие в документе числовые показатели "
    "(биомаркеры, измерения) с единицами. Если числовых показателей нет — values: {}. "
    "Не выдумывай значения."
)


def _headers() -> dict:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")
    return {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }


def _parse_json_reply(text: str) -> dict:
    """Достаёт первый JSON-объект из ответа модели. Пустой dict при провале."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    values = data.get("values")
    if not isinstance(values, dict):
        data["values"] = {}
    return data


def _call_claude(content: list) -> dict:
    payload = {
        "model": AGENT_MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": content}],
    }
    resp = requests.post(ANTHROPIC_API_URL, json=payload, headers=_headers(), timeout=TIMEOUT_S)
    resp.raise_for_status()
    blocks = resp.json().get("content", [])
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    return _parse_json_reply(text)


def extract_from_text(pdf_text: str) -> dict:
    """Извлечение из текстового PDF (текст уже вытащен pypdf)."""
    if not (pdf_text or "").strip():
        return {}
    content = [{"type": "text", "text": f"{_EXTRACT_PROMPT}\n\n--- ДОКУМЕНТ ---\n{pdf_text[:30000]}"}]
    return _call_claude(content)


def extract_from_image(image_bytes: bytes, media_type: str = "image/jpeg") -> dict:
    """Извлечение из фото/скана бланка через vision."""
    if not image_bytes:
        return {}
    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.b64encode(image_bytes).decode(),
            },
        },
        {"type": "text", "text": _EXTRACT_PROMPT},
    ]
    return _call_claude(content)
