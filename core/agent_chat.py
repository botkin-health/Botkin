"""
Conversational agent for @Botkin_md_bot — path X of NanoClaw integration.

Called from `handlers/text.py` when LLM router classifies a message as
`type=other` (i.e., not food / supplement / BP / etc — a free-form question).
This module wraps a single Anthropic Messages API call with tools, using:

- per-user system prompt from `users.agent_system_prompt`
- 7 tools that wrap `webhook/agent_tools_api.py` endpoints over HTTP+JWT
- conversation history from `agent_conversations` table (last N turns)

Same model + tools as NanoClaw spawn-container agent (`groups/<u>/skills/botkin/server.ts`).
NanoClaw stays running on `@BotkinAgent_bot` for dev/testing.

See: docs/projects/2026-05_nanoclaw-agent-bot/ (PLAN.md "Phase 4").
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import jwt as pyjwt
import requests

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from config import get_settings
from database import SessionLocal
from database.models import User

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
# Sonnet 4.5 is the same model NanoClaw uses by default for agents.
MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 2000
MAX_TOOL_ITERATIONS = 6  # safety net against tool loops
HISTORY_WINDOW = 20  # last N messages from agent_conversations

# Tools API base URL — same container, FastAPI on 8081.
# When running inside healthvault_bot container, this is localhost:8081 directly.
TOOLS_API_BASE = "http://localhost:8081/api/agent"

JWT_TTL_HOURS = 24  # short-lived; agent_chat regenerates per request

# ---------------------------------------------------------------------------
# Tool schema (same 7 tools as NanoClaw MCP server botkin/server.ts)
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_user_profile",
        "description": "Базовый профиль: имя, возраст, рост, пол, когорта, pack_name. Обычно не нужен — контекст уже в system prompt.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_dashboard_summary",
        "description": "ГЛАВНЫЙ tool: сводка здоровья за последние 7 дней — средние шаги, пульс, активные ккал, ккал съеденные, последний вес+%жира. Используй для любых вопросов 'как мои дела/неделя/прогресс'.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_recent_meals",
        "description": "Недавние приёмы пищи. days=1..30, по умолчанию 3.",
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 30, "default": 3}},
        },
    },
    {
        "name": "get_kb_value",
        "description": "Значение из knowledge base по ключу. Распространённые ключи: 'blood_tests', 'hormones', 'vitamins', 'blood_pressure_history', 'weight_history', 'allergies'.",
        "input_schema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    },
    {
        "name": "get_recent_bp",
        "description": "Измерения артериального давления за последние N дней (1-90, по умолчанию 14). Возвращает каждый замер + статистику: средние систолика/диастолика, max/min, % замеров выше 140/90 (порог гипертонии 1 ст).",
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 90, "default": 14}},
        },
    },
    {
        "name": "get_recent_sleep",
        "description": "Сон за последние N дней (1-90, по умолчанию 14). Возвращает каждую ночь + средняя продолжительность, качество, deep/REM/awake минуты.",
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 90, "default": 14}},
        },
    },
    {
        "name": "get_recent_supplements",
        "description": (
            "ЕДИНСТВЕННЫЙ источник для вопросов 'какие витамины/добавки я "
            "принимаю', 'сколько раз в неделю пил магний', 'когда последний "
            "раз принимал креатин', 'насколько я придерживаюсь схемы'. "
            "Возвращает агрегацию по каждой добавке за период: days_taken, "
            "total_intakes (несколько раз в день — норма), adherence_pct "
            "(% дней приёма от периода), last_date, last_dosage. "
            "Период по умолчанию 30 дней. НЕ используй контекст из system "
            "prompt — там может быть устаревший список, реальный лог здесь."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 180, "default": 30}},
        },
    },
    {
        "name": "get_recent_biomarkers",
        "description": (
            "ЕДИНСТВЕННЫЙ источник для вопросов про анализы крови, гормоны, "
            "витамины, биомаркеры. Возвращает строки blood_tests из Postgres: "
            "дата + тип + values (dict со значениями маркеров типа vitamin_d, "
            "LDL, HDL, glucose, HbA1c, testosterone, TSH, ferritin, ApoB и т.п.). "
            "Используй ВСЕГДА когда юзер спрашивает про любые лабораторные показатели: "
            "'какой у меня витамин Д', 'как менялся холестерин', 'какие гормоны сдавал', "
            "'покажи динамику ЛПНП', 'какие анализы за последний год'. "
            "limit по умолчанию 20 (история на год), увеличь до 50 для 'всё что есть'. "
            "НЕ ИСПОЛЬЗУЙ get_kb_value для анализов — оно ничего не вернёт."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}},
        },
    },
    {
        "name": "get_phenoage",
        "description": (
            "Биологический возраст по формуле Levine 2018 (Aging Cell). "
            "Возвращает bio_age, chronological_age, delta_years, и 9 маркеров "
            "(albumin, creatinine, glucose, hs_CRP, lymphocytes, MCV, RDW, ALP, WBC) "
            "с пометкой 'younger'/'older' vs NHANES median. Используй для "
            "вопросов 'какой мой биологический возраст', 'PhenoAge', "
            "'на сколько я моложе/старше паспорта', 'состав панели биовозраста'. "
            "Если каких-то маркеров не хватает — вернёт error со списком."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_recent_workouts",
        "description": (
            "Анализ тренировок по канонам Seiler 80/20 / Attia Z2 / норвежский 4x4. "
            "Возвращает: by_type (счётчик по Garmin type — running, walking, "
            "strength_training, yoga и т.п.), Z2 min/week, HIIT min/week, A:C "
            "load ratio (sweet spot 0.8-1.3), polarized distribution Z1+Z2/Z3/Z4+Z5 %, "
            "список последних 15 тренировок с type+name. "
            "Используй для 'сколько раз я бегал', 'сколько Z2 в неделю', "
            "'каков мой A:C ratio', 'правильное ли распределение зон'. "
            "ВАЖНО: для классификации (бег/ходьба/силовая) ВСЕГДА смотри поле "
            "`type` (Garmin classification), а НЕ `name` (user-set route label "
            "типа 'Москва - База' который может быть бегом ИЛИ ходьбой). "
            "Используй by_type для прямых вопросов типа 'сколько раз я бегал'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 180, "default": 30}},
        },
    },
    {
        "name": "get_recent_trends",
        "description": (
            "Per-day тренды HRV, Body Battery, Stress, Steps, RHR, Sleep "
            "за N дней (по умолчанию 14). В отличие от get_dashboard_summary "
            "который даёт только AVG за 7 дней — тут видно динамику ДЕНЬ ЗА ДНЁМ. "
            "Используй для 'падает ли мой HRV', 'когда у меня был стресс', "
            "'какой у меня body battery утром', 'как менялся пульс покоя'. "
            "Возвращает items (per-day) + stats (avg/min/max)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 90, "default": 14}},
        },
    },
    {
        "name": "log_meal_text",
        "description": "Залогировать приём пищи из текстового описания. ИСПОЛЬЗОВАТЬ ТОЛЬКО если юзер ЯВНО просит 'запиши' или 'залогируй'. Не пытайся логировать каждое упоминание еды.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "slot": {
                    "type": "string",
                    "enum": ["breakfast", "lunch", "dinner", "snack"],
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "log_bp",
        "description": "Залогировать измерение давления.",
        "input_schema": {
            "type": "object",
            "properties": {
                "systolic": {"type": "integer"},
                "diastolic": {"type": "integer"},
                "pulse": {"type": "integer"},
            },
            "required": ["systolic", "diastolic"],
        },
    },
    {
        "name": "log_supplement",
        "description": "Залогировать приём добавки/витамина.",
        "input_schema": {
            "type": "object",
            "properties": {
                "supplement_name": {"type": "string"},
                "dosage": {"type": "string"},
            },
            "required": ["supplement_name"],
        },
    },
]

# ---------------------------------------------------------------------------
# JWT generation (matches webhook/jwt_auth.py contract)
# ---------------------------------------------------------------------------


def _generate_jwt(user: User) -> str:
    """Short-lived JWT for in-process tool calls.

    Reuses the same `users.jwt_secret` + container_id contract as the
    Sprint 1a NanoClaw integration (webhook/jwt_auth.py).
    """
    if not user.jwt_secret or not user.container_id:
        raise RuntimeError(f"User {user.telegram_id} missing jwt_secret or container_id; cannot generate agent JWT")
    payload = {
        "user_id": user.telegram_id,
        "container_id": user.container_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_TTL_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return pyjwt.encode(payload, user.jwt_secret, algorithm="HS256")


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


def _call_tool(name: str, args: dict, token: str) -> str:
    """Synchronous HTTP call to tools API. Returns raw response body as string."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        if name == "get_user_profile":
            r = requests.get(f"{TOOLS_API_BASE}/user_profile", headers=headers, timeout=10)
        elif name == "get_dashboard_summary":
            r = requests.get(f"{TOOLS_API_BASE}/dashboard_summary", headers=headers, timeout=15)
        elif name == "get_recent_meals":
            days = int(args.get("days", 3))
            r = requests.get(
                f"{TOOLS_API_BASE}/recent_meals",
                params={"days": days},
                headers=headers,
                timeout=15,
            )
        elif name == "get_kb_value":
            r = requests.get(
                f"{TOOLS_API_BASE}/kb_value",
                params={"key": args["key"]},
                headers=headers,
                timeout=10,
            )
        elif name == "get_recent_bp":
            r = requests.get(
                f"{TOOLS_API_BASE}/recent_bp",
                params={"days": int(args.get("days", 14))},
                headers=headers,
                timeout=15,
            )
        elif name == "get_recent_sleep":
            r = requests.get(
                f"{TOOLS_API_BASE}/recent_sleep",
                params={"days": int(args.get("days", 14))},
                headers=headers,
                timeout=15,
            )
        elif name == "get_recent_supplements":
            r = requests.get(
                f"{TOOLS_API_BASE}/recent_supplements",
                params={"days": int(args.get("days", 30))},
                headers=headers,
                timeout=15,
            )
        elif name == "get_recent_biomarkers":
            r = requests.get(
                f"{TOOLS_API_BASE}/recent_biomarkers",
                params={"limit": int(args.get("limit", 20))},
                headers=headers,
                timeout=15,
            )
        elif name == "get_phenoage":
            r = requests.get(f"{TOOLS_API_BASE}/phenoage", headers=headers, timeout=15)
        elif name == "get_recent_workouts":
            r = requests.get(
                f"{TOOLS_API_BASE}/recent_workouts",
                params={"days": int(args.get("days", 30))},
                headers=headers,
                timeout=15,
            )
        elif name == "get_recent_trends":
            r = requests.get(
                f"{TOOLS_API_BASE}/recent_trends",
                params={"days": int(args.get("days", 14))},
                headers=headers,
                timeout=15,
            )
        elif name == "log_meal_text":
            r = requests.post(f"{TOOLS_API_BASE}/log_meal_text", json=args, headers=headers, timeout=30)
        elif name == "log_bp":
            r = requests.post(f"{TOOLS_API_BASE}/log_bp", json=args, headers=headers, timeout=10)
        elif name == "log_supplement":
            r = requests.post(f"{TOOLS_API_BASE}/log_supplement", json=args, headers=headers, timeout=10)
        else:
            return json.dumps({"error": f"unknown tool: {name}"})

        if not r.ok:
            return json.dumps({"error": f"HTTP {r.status_code}", "body": r.text[:500]})
        return r.text
    except Exception as e:
        logger.exception("Tool %s failed", name)
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Conversation history (Postgres)
# ---------------------------------------------------------------------------


def _load_history(db, user_id: int, limit: int = HISTORY_WINDOW) -> list[dict]:
    """Load last N messages from agent_conversations in chronological order.

    Returns list shaped for Anthropic API `messages` parameter.
    Each row's `content` is already a JSONB list of content blocks.
    Adjacent rows of same role are squashed by Anthropic-side; we don't.
    """
    from sqlalchemy import text

    sql = text(
        """
        SELECT role, content
        FROM agent_conversations
        WHERE user_id = :uid
        ORDER BY id DESC
        LIMIT :lim
        """
    )
    rows = db.execute(sql, {"uid": user_id, "lim": limit}).fetchall()
    rows = list(reversed(rows))  # chronological
    # Map our role values → Anthropic roles.
    # We store 'user' / 'assistant' (verbatim from API) and intermediary
    # 'tool_use' / 'tool_result' are part of assistant / user messages
    # respectively, but in our denormalised storage they're separate rows.
    # We re-group adjacent tool_use/tool_result rows back into assistant/user
    # turns.
    messages: list[dict] = []
    for role, content in rows:
        if role == "user":
            messages.append({"role": "user", "content": content})
        elif role == "assistant":
            messages.append({"role": "assistant", "content": content})
        elif role == "tool_use":
            # tool_use blocks are part of an assistant message — append.
            if messages and messages[-1]["role"] == "assistant":
                if isinstance(messages[-1]["content"], str):
                    messages[-1]["content"] = [{"type": "text", "text": messages[-1]["content"]}]
                messages[-1]["content"].extend(content)
            else:
                messages.append({"role": "assistant", "content": content})
        elif role == "tool_result":
            # tool_result blocks belong to a user message.
            if messages and messages[-1]["role"] == "user":
                if isinstance(messages[-1]["content"], str):
                    messages[-1]["content"] = [{"type": "text", "text": messages[-1]["content"]}]
                messages[-1]["content"].extend(content)
            else:
                messages.append({"role": "user", "content": content})

    return _validate_history(messages)


def _validate_history(messages: list[dict]) -> list[dict]:
    """Strip orphan tool_use/tool_result blocks that violate Anthropic API.

    Bug fix for 400 'unexpected tool_use_id in tool_result blocks'. Reasons
    orphans happen at HISTORY_WINDOW boundary, after row deletions, or after
    save crashes between tool_use save and matching tool_result save.

    Algorithm:
      1. Collect all tool_use_id present anywhere in the window
      2. Drop any tool_result blocks whose tool_use_id isn't in that set
      3. Drop any tool_use blocks whose id isn't matched by a later tool_result
      4. Drop messages that become empty after block-stripping
      5. Strip leading message if its only content was orphan tool blocks
         (Anthropic requires first message to be 'user' with real text)
    """
    # First pass: collect all tool_use_id and tool_result tool_use_id present
    tool_use_ids: set[str] = set()
    tool_result_ids: set[str] = set()
    for m in messages:
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                if tid := block.get("id"):
                    tool_use_ids.add(tid)
            elif block.get("type") == "tool_result":
                if tid := block.get("tool_use_id"):
                    tool_result_ids.add(tid)

    # Both must match — orphans on either side are stripped
    valid_ids = tool_use_ids & tool_result_ids

    # Second pass: strip blocks with id not in valid_ids
    cleaned: list[dict] = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            cleaned.append(m)
            continue
        if not isinstance(content, list):
            cleaned.append(m)
            continue
        new_blocks = []
        for block in content:
            if isinstance(block, dict):
                btype = block.get("type")
                if btype == "tool_use":
                    if block.get("id") in valid_ids:
                        new_blocks.append(block)
                    continue
                if btype == "tool_result":
                    if block.get("tool_use_id") in valid_ids:
                        new_blocks.append(block)
                    continue
            new_blocks.append(block)
        if new_blocks:
            cleaned.append({"role": m["role"], "content": new_blocks})

    # Anthropic requires first message role == "user". If we somehow end up
    # with an assistant-first list (because user msg got fully orphaned),
    # drop leading assistants.
    while cleaned and cleaned[0]["role"] != "user":
        cleaned.pop(0)
    return cleaned


def _save_message(db, user_id: int, role: str, content: Any, tool_use_id: Optional[str] = None):
    from sqlalchemy import text

    db.execute(
        text(
            """
            INSERT INTO agent_conversations (user_id, role, content, tool_use_id)
            VALUES (:uid, :role, CAST(:content AS JSONB), :tid)
            """
        ),
        {
            "uid": user_id,
            "role": role,
            "content": json.dumps(content),
            "tid": tool_use_id,
        },
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def ask_agent(user_id: int, user_text: str) -> str:
    """Synchronous — call from `run_in_executor`.

    Returns assistant's text reply. Empty string if nothing produced.
    Errors are raised; caller (handler) catches and replies "технически не вышло".
    """
    settings = get_settings()
    api_key = settings.anthropic_api_key
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    db = SessionLocal()
    try:
        user = db.query(User).filter_by(telegram_id=user_id).first()
        if not user or not user.is_active:
            raise RuntimeError(f"User {user_id} not found or inactive")
        if not user.agent_system_prompt:
            raise RuntimeError(
                f"User {user_id} has no agent_system_prompt — conversational agent not enabled for this user yet"
            )

        token = _generate_jwt(user)

        # Build messages: history + new user turn
        history = _load_history(db, user_id)
        history.append({"role": "user", "content": user_text})

        # Persist user turn immediately so a crash mid-call doesn't lose it.
        _save_message(db, user_id, "user", user_text)
        db.commit()

        headers = {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

        for iteration in range(MAX_TOOL_ITERATIONS):
            payload = {
                "model": MODEL,
                "max_tokens": MAX_TOKENS,
                "system": user.agent_system_prompt,
                "tools": TOOLS,
                "messages": history,
            }
            logger.info(
                "agent_chat call: user=%s iter=%s msgs=%s",
                user_id,
                iteration,
                len(history),
            )
            r = requests.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=60)
            # Anthropic returns 400 when message history has structural issues
            # (e.g. tool_use block without matching tool_result from a previous
            # turn). This can happen if a row was deleted, the DB had a partial
            # write, or older history was corrupted by an earlier bug. Recover
            # by retrying with a clean slate (just system + new user turn),
            # marking the broken history so the user understands context was
            # dropped.
            if r.status_code == 400 and iteration == 0 and len(history) > 1:
                err_body = r.text[:500]
                logger.warning(
                    "agent_chat 400 from Anthropic with %d history msgs — retrying with fresh history. Body: %s",
                    len(history),
                    err_body,
                )
                # Reset to just the new user message
                history = [{"role": "user", "content": user_text}]
                payload["messages"] = history
                r = requests.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=60)
            r.raise_for_status()
            response = r.json()

            stop_reason = response.get("stop_reason")
            blocks = response.get("content", [])

            if stop_reason == "tool_use":
                # Record assistant turn (text + tool_use blocks)
                _save_message(db, user_id, "assistant", blocks)
                history.append({"role": "assistant", "content": blocks})

                # Execute each tool_use, collect tool_result blocks
                tool_results: list[dict] = []
                for block in blocks:
                    if block.get("type") != "tool_use":
                        continue
                    name = block["name"]
                    args = block.get("input", {})
                    tu_id = block["id"]
                    logger.info("agent_chat tool: %s args=%s", name, args)
                    result_text = _call_tool(name, args, token)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tu_id,
                            "content": result_text,
                        }
                    )

                _save_message(db, user_id, "tool_result", tool_results)
                history.append({"role": "user", "content": tool_results})
                db.commit()
                continue  # next iteration — model will incorporate tool results

            # stop_reason in ("end_turn", "max_tokens", "stop_sequence") — final
            _save_message(db, user_id, "assistant", blocks)
            db.commit()

            # Extract text
            text_parts = [b["text"] for b in blocks if b.get("type") == "text"]
            return "\n".join(text_parts).strip()

        # Exhausted iterations
        logger.warning("agent_chat: max iterations (%s) hit", MAX_TOOL_ITERATIONS)
        return "Не справился за разумное число шагов — попробуй переформулировать вопрос."
    finally:
        db.close()
