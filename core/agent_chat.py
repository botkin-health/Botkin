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
        "name": "get_recent_biomarkers",
        "description": "Последние анализы крови (по умолчанию 5 самых свежих). Каждый — дата + тип + JSON со значениями маркеров. Использовать для вопросов 'какие у меня были последние анализы', 'какой холестерин в марте', и т.п.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5}},
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
        elif name == "get_recent_biomarkers":
            r = requests.get(
                f"{TOOLS_API_BASE}/recent_biomarkers",
                params={"limit": int(args.get("limit", 5))},
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
    return messages


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
