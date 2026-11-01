#!/usr/bin/env python3
"""Набор кейсов для agent_cost_eval.py из реальных диалогов BotkinClaw.

Запуск — внутри прод-контейнера (нужна прод-БД):

    python build_agent_cases.py --days 30 --n 15 --out /tmp/cases.json

Берёт только пользователей с agent_review_consent=TRUE и только текстовые
реплики (без картинок). Кейсы подбираются жадно под максимальное покрытие
тулов, которые агент тогда реально вызвал (`orig_tools`), плюс пара реплик
без тулов. К каждому кейсу — текстовая история диалога до него.
Результат содержит реальные сообщения — хранить вне репозитория.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text  # noqa: E402

from database import SessionLocal  # noqa: E402

HISTORY_TURNS = 6
MAX_PER_USER = 4


def _blocks(content) -> list:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content if isinstance(content, list) else []


def _text(content) -> str:
    return "\n".join(b.get("text", "") for b in _blocks(content) if b.get("type") == "text").strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--n", type=int, default=15)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with SessionLocal() as db:
        rows = db.execute(
            text(
                """
                SELECT c.id, c.user_id, c.role, c.content
                FROM agent_conversations c
                JOIN users u ON u.telegram_id = c.user_id
                WHERE u.agent_review_consent = TRUE
                  AND (c.source IS NULL OR c.source = 'botkinclaw')
                  AND c.role IN ('user', 'assistant')
                  AND c.created_at > now() - make_interval(days => :days)
                ORDER BY c.user_id, c.id
                """
            ),
            {"days": args.days},
        ).fetchall()

    by_user: dict[int, list] = {}
    for r in rows:
        by_user.setdefault(r.user_id, []).append(r)

    candidates = []
    for uid, turns in by_user.items():
        for i, r in enumerate(turns):
            blocks = _blocks(r.content)
            msg = _text(r.content)
            is_tool_result = any(b.get("type") == "tool_result" for b in blocks)
            if r.role != "user" or not msg or is_tool_result or any(b.get("type") == "image" for b in blocks):
                continue
            tools = []
            for nxt in turns[i + 1 :]:
                nb = _blocks(nxt.content)
                if nxt.role == "user" and not any(b.get("type") == "tool_result" for b in nb):
                    break
                tools += [b["name"] for b in nb if b.get("type") == "tool_use"]
            history = []
            for prev in turns[:i]:
                t = _text(prev.content)
                if t and not any(b.get("type") == "tool_result" for b in _blocks(prev.content)):
                    history.append({"role": prev.role, "content": t})
            history = history[-HISTORY_TURNS:]
            while history and history[0]["role"] != "user":
                history.pop(0)
            candidates.append(
                {"id": f"c{r.id}", "user_id": uid, "text": msg, "history": history, "orig_tools": sorted(set(tools))}
            )

    picked, covered, per_user = [], set(), {}
    while len(picked) < args.n:
        best = max(
            (c for c in candidates if c not in picked and per_user.get(c["user_id"], 0) < MAX_PER_USER),
            key=lambda c: len(set(c["orig_tools"]) - covered),
            default=None,
        )
        if best is None or not set(best["orig_tools"]) - covered:
            break
        picked.append(best)
        covered |= set(best["orig_tools"])
        per_user[best["user_id"]] = per_user.get(best["user_id"], 0) + 1
    # Добор: сначала реплики с тулами (свежие — в конце списка), потом до двух без тулов.
    no_tools = [c for c in candidates if not c["orig_tools"]][-2:]
    for c in [c for c in reversed(candidates) if c["orig_tools"]] + no_tools:
        if len(picked) >= args.n:
            break
        if c not in picked and per_user.get(c["user_id"], 0) < MAX_PER_USER:
            picked.append(c)
            per_user[c["user_id"]] = per_user.get(c["user_id"], 0) + 1

    Path(args.out).write_text(json.dumps(picked, ensure_ascii=False, indent=1))
    print(f"{len(candidates)} candidates, picked {len(picked)}, tools covered: {sorted(covered)}")


if __name__ == "__main__":
    main()
