#!/usr/bin/env python3
"""A/B-прогон агента BotkinClaw на замороженном наборе реальных вопросов.

Запуск — внутри прод-контейнера, по очереди для каждой версии кода:

    python agent_cost_eval.py --code-root /tmp/eval_A --cases cases.json \
        --out out_A.jsonl --tool-cache tool_cache.json

Режим «только чтение»: ответы и история не сохраняются, расход не пишется в
llm_usage_log, инструменты записи заглушены. Результаты читающих инструментов
кешируются в --tool-cache: второй прогон видит те же данные, что и первый,
и не дёргает внешние сервисы повторно (LibreLinkUp банит за частые логины).

cases.json — список {"id", "user_id", "text"}; хранится вне репозитория
(реальные сообщения пользователей).
"""

import argparse
import json
import sys
import time
from pathlib import Path

WRITE_PREFIXES = (
    "log_",
    "save_",
    "add_",
    "edit_",
    "delete_",
    "adjust_",
    "update_",
    "flag_",
    "triage_",
    "render_",
    "generate_",
    "send_",
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code-root", required=True)
    ap.add_argument("--cases", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tool-cache", required=True)
    ap.add_argument("--max-usd", type=float, default=3.0)
    args = ap.parse_args()

    root = args.code_root
    sys.path.insert(0, str(Path(root) / "telegram-bot"))
    sys.path.insert(0, root)

    import core.agent_chat as ac
    import core.llm_usage as lu

    cache_path = Path(args.tool_cache)
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    state = {"calls": [], "usage": [], "uid": None}

    real_call_tool = ac._call_tool

    def fake_call_tool(name, tool_args, token):
        state["calls"].append({"name": name, "args": tool_args})
        if name.startswith(WRITE_PREFIXES):
            return json.dumps({"ok": True, "status": "saved"}, ensure_ascii=False)
        key = f"{state['uid']}|{name}|{json.dumps(tool_args, sort_keys=True, ensure_ascii=False)}"
        if key not in cache:
            cache[key] = real_call_tool(name, tool_args, token)
        return cache[key]

    def fake_log(purpose, model, response_json, user_id=None):
        u = response_json.get("usage", {}) or {}
        state["usage"].append(
            {
                "purpose": purpose,
                "model": response_json.get("model", model),
                "input": u.get("input_tokens", 0) or 0,
                "cache_write": u.get("cache_creation_input_tokens", 0) or 0,
                "cache_read": u.get("cache_read_input_tokens", 0) or 0,
                "output": u.get("output_tokens", 0) or 0,
                "stop_reason": response_json.get("stop_reason"),
                "block_types": [b.get("type") for b in response_json.get("content", [])],
            }
        )

    ac._call_tool = fake_call_tool
    ac._save_message = lambda *a, **k: None
    ac._persist_turns = lambda *a, **k: None
    ac._log_first_question = lambda *a, **k: None
    ac.record_failed_turn = lambda *a, **k: None
    ac._load_history = lambda db, user_id, limit=None: []
    lu.log_anthropic_response = fake_log

    cases = json.loads(Path(args.cases).read_text())
    total_usd = 0.0
    with open(args.out, "w") as out:
        for case in cases:
            state.update(calls=[], usage=[], uid=case["user_id"])
            t0 = time.monotonic()
            reply, error = "", None
            try:
                reply = ac.ask_agent(case["user_id"], case["text"])
            except Exception as e:  # noqa: BLE001 — фиксируем и идём дальше
                error = f"{type(e).__name__}: {e}"
            latency = round(time.monotonic() - t0, 1)
            cost = sum(
                lu.compute_cost(u["model"], u["input"], u["output"], u["cache_write"], u["cache_read"])
                for u in state["usage"]
            )
            total_usd += cost
            row = {
                "id": case["id"],
                "user_id": case["user_id"],
                "text": case["text"],
                "reply": reply,
                "error": error,
                "tool_calls": state["calls"],
                "usage": state["usage"],
                "cost_usd": round(cost, 5),
                "latency_s": latency,
            }
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            cache_path.write_text(json.dumps(cache, ensure_ascii=False))
            print(f"{case['id']}: ${cost:.4f} {latency}s tools={[c['name'] for c in state['calls']]} err={error}")
            if total_usd > args.max_usd:
                print(f"STOP: потрачено ${total_usd:.2f} > --max-usd {args.max_usd}")
                break
    print(f"TOTAL ${total_usd:.4f}")


if __name__ == "__main__":
    main()
