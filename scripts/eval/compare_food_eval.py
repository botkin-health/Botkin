#!/usr/bin/env python3
"""Сводит результаты food_parsing_eval по нескольким каталогам results/* в одну таблицу
и показывает кейсы с наибольшим расхождением по ккал — для ручного разбора.

    python3 scripts/eval/compare_food_eval.py data/eval/food/results/2026*  --top 12
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = ROOT / "data" / "eval" / "food" / "cases.json"


def load_runs(dirs: list[Path]) -> dict[str, dict[str, dict]]:
    runs: dict[str, dict[str, dict]] = {}
    for d in dirs:
        for f in sorted(d.glob("*.jsonl")):
            rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
            runs[f.stem] = {r["id"]: r for r in rows}
    return runs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+", type=Path)
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()

    cases = {c["id"]: c for c in json.loads(CASES_PATH.read_text(encoding="utf-8"))}
    runs = load_runs(args.dirs)
    names = list(runs)

    print("## Ккал по кейсам (golden | " + " | ".join(names) + ")\n")
    print("| id | text | golden | " + " | ".join(names) + " |")
    print("|---|---|---|" + "---|" * len(names))
    for cid, c in cases.items():
        g = c["golden"]
        cells = []
        for n in names:
            r = runs[n].get(cid)
            if not r:
                cells.append("·")
            elif r.get("error"):
                cells.append("ERR")
            elif not r.get("type_ok"):
                cells.append(f"type={r.get('pred_type')}")
            else:
                pk = r.get("pred_kcal")
                cells.append(f"{pk:.0f}" if isinstance(pk, (int, float)) else str(pk))
        gk = g.get("calories")
        print(
            f"| {cid} | {(c['text'] or '[фото]')[:45].replace('|', '/')} | {gk if gk is None else round(gk)} ({g['type']}) | "
            + " | ".join(cells)
            + " |"
        )

    print(f"\n## Топ-{args.top} расхождений по ккал на конфигурацию\n")
    for n in names:
        rows = [r for r in runs[n].values() if r.get("kcal_rel_err") is not None]
        rows.sort(key=lambda r: -r["kcal_rel_err"])
        print(f"### {n}")
        for r in rows[: args.top]:
            c = cases[r["id"]]
            print(
                f"- {r['id']} err={r['kcal_rel_err']:.0%} golden={c['golden'].get('calories')} pred={r.get('pred_kcal')} — {(c['text'] or '[фото]')[:70]!r}"
            )
        print()

    print("## Латентность и цена\n")
    print("| config | p50 | p90 | max | $ total | $/call |")
    print("|---|---|---|---|---|---|")
    for n in names:
        lat = sorted(r["latency_s"] for r in runs[n].values() if not r.get("error"))
        if not lat:
            continue
        p = lambda q: lat[min(len(lat) - 1, int(q * len(lat)))]  # noqa: E731
        print(f"| {n} | {p(0.5):.1f}s | {p(0.9):.1f}s | {lat[-1]:.1f}s | — | — |")


if __name__ == "__main__":
    main()
