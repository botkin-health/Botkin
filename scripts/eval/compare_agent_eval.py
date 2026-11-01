#!/usr/bin/env python3
"""Сравнение двух прогонов agent_cost_eval.py: тулы, аргументы, цена, ответы.

    python compare_agent_eval.py out_A.jsonl out_B.jsonl [--replies]

Печатает по кейсу: совпал ли набор тулов, разницу в тулах и аргументах,
цену; с --replies — оба ответа целиком для ручного чтения. В конце — итоги.
Вывод содержит реальные сообщения — не коммитить и не постить в GitHub.
"""

import argparse
import json


def _load(path: str) -> dict:
    with open(path) as f:
        return {r["id"]: r for r in map(json.loads, f)}


def _calls(row: dict) -> list[str]:
    return [f"{c['name']}({json.dumps(c['args'], ensure_ascii=False, sort_keys=True)})" for c in row["tool_calls"]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--replies", action="store_true")
    args = ap.parse_args()

    a, b = _load(args.a), _load(args.b)
    same_tools = same_calls = 0
    cost_a = cost_b = 0.0
    ids = [i for i in a if i in b]
    for i in ids:
        ra, rb = a[i], b[i]
        ta, tb = {c["name"] for c in ra["tool_calls"]}, {c["name"] for c in rb["tool_calls"]}
        ca, cb = _calls(ra), _calls(rb)
        same_tools += ta == tb
        same_calls += sorted(ca) == sorted(cb)
        cost_a += ra["cost_usd"]
        cost_b += rb["cost_usd"]
        mark = "=" if ta == tb else "≠"
        print(f"\n### {i} {mark} ${ra['cost_usd']:.4f} → ${rb['cost_usd']:.4f}  {ra['text'][:120]!r}")
        print(f"  A: {', '.join(ca) or '—'}")
        print(f"  B: {', '.join(cb) or '—'}")
        if ra.get("error") or rb.get("error"):
            print(f"  errors: A={ra.get('error')} B={rb.get('error')}")
        if args.replies:
            print(f"  --- A ---\n{ra['reply']}\n  --- B ---\n{rb['reply']}")
    n = len(ids)
    print(f"\nкейсов {n}: тот же набор тулов {same_tools}/{n}, те же вызовы с аргументами {same_calls}/{n}")
    print(f"цена: A ${cost_a:.4f}, B ${cost_b:.4f} ({(cost_b / cost_a - 1) * 100:+.1f}%)" if cost_a else "")


if __name__ == "__main__":
    main()
