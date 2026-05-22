"""LLM-генерация персональных блоков для system_prompt.

Шесть блоков выводятся одним структурированным вызовом Claude'а:
- framing: рамка для интерпретации всего
- chronic: список диагнозов с формулировками
- open_questions: красные флаги, что сейчас обсуждаем
- therapy: текущая терапия
- focus_areas: что важно для pack
- typical_questions: контекстные ответы на типичные ситуации

Модель: claude-sonnet-4-6 с fallback на 4-5 при 529/503/429 (паттерн из core/agent_chat.py).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from string import Template

import requests

from core.packs import get_pack

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = "claude-sonnet-4-6"
FALLBACK_MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 4000
REQUEST_TIMEOUT = 60
QUICK_RETRY_SLEEP = 0.7


@dataclass(frozen=True)
class PersonaInput:
    name: str  # короткое имя — "Игорь"
    full_name: str  # полное — "Лысковский Игорь Александрович"
    age: str  # "21 год" — словами
    birth_date: str
    location: str
    cohort: str
    cohort_relationship: str  # "сын Александра"
    pack_name: str
    bio_line: str
    kb_json: dict  # полный knowledge_base.json
    profile_md: str  # содержимое PROFILE.md
    style: str  # "ty" или "vy"


@dataclass(frozen=True)
class PersonaBlocks:
    framing: str
    chronic: str
    open_questions: str
    therapy: str
    focus_areas: str
    typical_questions: str


_GENERATION_INSTRUCTION = """\
Ты помогаешь сгенерировать персональные блоки для system_prompt медицинского AI-агента.

Тебе дан профиль пользователя (структурированный knowledge_base.json + PROFILE.md),
его pack ({pack_name}, описание: {pack_description}), стиль обращения {style_human}.

Сгенерируй СТРОГО JSON-объект с шестью полями:
- framing: 2-3 абзаца — главная рамка интерпретации (кто этот пациент, что у него
  основное, что сейчас в фокусе). Без списков, проза.
- chronic: маркированный список диагнозов с МКБ-кодами (если есть) и кратким
  пояснением. Если диагнозов нет — пиши "Хронических диагнозов в KB нет".
- open_questions: 1-5 пунктов про "красные флаги" / что сейчас под вниманием.
  Если ничего — пиши "На момент онбординга открытых красных флагов в KB не зафиксировано".
- therapy: текущая терапия (препараты + добавки). Если в KB нет — пиши
  "Постоянной терапии в KB нет. Уточни у пользователя в первом разговоре."
- focus_areas: 2-4 предложения про focus-зоны под этот pack. Привязывай к
  реальным данным юзера.
- typical_questions: 3-6 примеров вопросов, которые юзер может задать, с краткими
  гайдами как отвечать (например, "Про витамин D — назови последнее значение
  и тренд за 2-3 точки").

ВАЖНО:
- {style_instruction}
- Без выдумок. Только факты из KB и PROFILE.md.
- Если данных мало — честно отмечай ("при первом разговоре уточни").
- Только Markdown в значениях. Без HTML.
- Ответ — голый JSON без обёртки ```json, без префиксных фраз.
"""


def _build_generation_messages(inp: PersonaInput) -> tuple[str, list[dict]]:
    pack = get_pack(inp.pack_name)
    style_instruction = (
        "Стиль обращения — на «ты», непринуждённо, без формальностей."
        if inp.style == "ty"
        else "Стиль обращения — на «Вы», уважительно, без панибратства."
    )
    style_human = "на «ты»" if inp.style == "ty" else "на «Вы»"
    instruction = _GENERATION_INSTRUCTION.format(
        pack_name=pack.name,
        pack_description=pack.description,
        style_instruction=style_instruction,
        style_human=style_human,
    )
    user_content = (
        f"PROFILE.md:\n```\n{inp.profile_md}\n```\n\n"
        f"knowledge_base.json:\n```json\n{json.dumps(inp.kb_json, ensure_ascii=False, indent=2)}\n```"
    )
    messages = [{"role": "user", "content": user_content}]
    return instruction, messages


def _call_anthropic(*, system: str, messages: list[dict], model: str, api_key: str) -> requests.Response:
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": system,
        "messages": messages,
    }
    return requests.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)


def generate_persona(inp: PersonaInput) -> PersonaBlocks:
    """Сгенерить 6 блоков через Claude. Fallback 4.6 → 4.5 при overload."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY env var not set")

    system, messages = _build_generation_messages(inp)

    # Primary attempt with quick retry on overload, then fallback model.
    resp = _call_anthropic(system=system, messages=messages, model=MODEL, api_key=api_key)
    if resp.status_code in (429, 503, 529):
        time.sleep(QUICK_RETRY_SLEEP)
        resp = _call_anthropic(system=system, messages=messages, model=MODEL, api_key=api_key)
    if resp.status_code in (429, 503, 529):
        resp = _call_anthropic(system=system, messages=messages, model=FALLBACK_MODEL, api_key=api_key)
    if resp.status_code != 200:
        raise RuntimeError(f"Anthropic API call failed: {resp.status_code} {resp.text[:500]}")

    body = resp.json()
    raw_text = body["content"][0]["text"].strip()
    # tolerate ```json wrapping if LLM ignored "no wrapping" instruction
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```", 2)[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.rsplit("```", 1)[0].strip()

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Failed to parse LLM response as JSON: {exc}. Raw text (first 300 chars): {raw_text[:300]!r}"
        ) from exc

    required = ("framing", "chronic", "open_questions", "therapy", "focus_areas", "typical_questions")
    missing = [k for k in required if k not in data]
    if missing:
        raise RuntimeError(
            f"LLM response missing required keys: {missing}. "
            f"Got keys: {sorted(data.keys())}. Raw (first 300): {raw_text[:300]!r}"
        )
    return PersonaBlocks(
        framing=data["framing"],
        chronic=data["chronic"],
        open_questions=data["open_questions"],
        therapy=data["therapy"],
        focus_areas=data["focus_areas"],
        typical_questions=data["typical_questions"],
    )


def render_prompt(
    inp: PersonaInput,
    blocks: PersonaBlocks,
    *,
    template_path: Path,
) -> str:
    """Подставить blocks + inp в markdown-шаблон через string.Template."""
    pack = get_pack(inp.pack_name)
    template = Template(template_path.read_text(encoding="utf-8"))
    style_text = (
        "- Обращение на «ты», непринуждённо, без формальностей.\n"
        "- Конкретно и по сути. Объяснять механизмы можно, но без перегруза.\n"
        "- Не пугать. Спокойный тон, фокус на «что предлагаю проверить»."
        if inp.style == "ty"
        else "- Обращение на «Вы», с уважением. Без панибратства.\n"
        "- Не пугать. Спокойно, с контекстом «вот что вижу, окончательно — за лечащим врачом».\n"
        "- Конкретно и по сути."
    )
    kb_sections = sorted(inp.kb_json.keys())
    return template.safe_substitute(
        name=inp.name,
        full_name=inp.full_name,
        age=inp.age,
        birth_date=inp.birth_date,
        location=inp.location,
        cohort=inp.cohort,
        cohort_relationship=inp.cohort_relationship,
        pack_name=pack.name,
        pack_description=pack.description,
        bio_line=inp.bio_line,
        communication_style=style_text,
        framing_block=blocks.framing,
        chronic_block=blocks.chronic,
        open_questions_block=blocks.open_questions,
        therapy_block=blocks.therapy,
        focus_areas_block=blocks.focus_areas,
        typical_questions_block=blocks.typical_questions,
        kb_sections_list=", ".join(kb_sections) if kb_sections else "(пусто)",
    )
