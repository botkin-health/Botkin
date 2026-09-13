#!/usr/bin/env python3
"""Пересчитывает метрики прогонов food-eval по ручному эталону golden_v3.json (интервалы),
не перезапуская модели. Работает по сохранённому `raw` в results/*.jsonl.

    python3 scripts/eval/rescore.py data/eval/food/results/<dir> [--configs sonnet46 haiku45] [--detail]

Метрики: type_ok (еда / не-еда / медицина+subtype), kcal_in_range, protein_in_range,
по источникам эталона (card/label/computed/user/visual), латентность, $.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from food_parsing_eval import CASES_PATH, PRICING, _strip_fences, cost_usd  # noqa: E402

GOLDEN_V3 = Path(__file__).resolve().parent / "golden_v3.json"


def _totals(raw: str) -> tuple[str | None, dict, str | None]:
    """→ (type, total_nutrition, subtype). Пустой dict, если JSON обрезан."""
    try:
        p = json.loads(_strip_fences(raw))
    except Exception:  # noqa: BLE001
        return None, {}, None
    data = p.get("data") or {}
    tn = data.get("total_nutrition") or (data.get("food") or {}).get("total_nutrition") or {}
    if p.get("type") == "multi_food":
        meals = data.get("meals") or []
        tn = {
            k: sum((m.get("total_nutrition") or {}).get(k) or 0 for m in meals)
            for k in ("calories", "protein", "fats", "carbs")
        }
    return p.get("type"), tn, data.get("subtype")


def _in(v, rng) -> bool | None:
    if v is None or not isinstance(v, (int, float)):
        return None
    lo, hi = rng
    return lo <= v <= hi


def score_row(case: dict, truth: dict | None, row: dict) -> dict:
    g = dict(case["golden"])
    if truth and truth.get("type"):
        g["type"] = truth["type"]
    ptype, tn, sub = _totals(row.get("raw", ""))
    if ptype is None:
        ptype = row.get("pred_type")
    out = {
        "id": case["id"],
        "error": row.get("error"),
        "latency_s": row.get("latency_s"),
        "usage": row.get("usage", {}),
    }
    out["type_ok"] = ptype == g["type"] or (g["type"] == "food" and ptype == "mixed")
    out["kind"] = (
        "neg"
        if case["id"].startswith("neg-")
        else "med"
        if case["id"].startswith("med-")
        else (truth or {}).get("source", "food")
    )
    if g["type"] == "medical":
        out["subtype_ok"] = out["type_ok"] and sub in (g.get("subtype") or "").split("|")
    if g["type"] in ("food", "multi_food") and truth:
        pk = tn.get("calories", row.get("pred_kcal"))
        pp = tn.get("protein")
        out["pred_kcal"], out["pred_protein"] = pk, pp
        out["kcal_ok"] = _in(pk, truth["kcal"]) if out["type_ok"] else False
        out["protein_ok"] = _in(pp, truth["protein"]) if out["type_ok"] else False
        if isinstance(pk, (int, float)):
            lo, hi = truth["kcal"]
            out["kcal_dist"] = 0.0 if lo <= pk <= hi else (lo - pk) / max(lo, 1) if pk < lo else (pk - hi) / max(hi, 1)
    return out


def pct(vals) -> str:
    vals = [v for v in vals if v is not None]
    return f"{100 * sum(vals) / len(vals):.0f}%" if vals else "—"


def p(vals, q) -> float:
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(q * len(vals)))] if vals else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("results_dir", type=Path)
    ap.add_argument("--configs", nargs="*", default=None)
    ap.add_argument("--detail", action="store_true", help="построчно: кейс × конфигурация (ккал)")
    args = ap.parse_args()

    cases = {c["id"]: c for c in json.loads(CASES_PATH.read_text(encoding="utf-8"))}
    truth = {k: v for k, v in json.loads(GOLDEN_V3.read_text(encoding="utf-8")).items() if not k.startswith("_")}
    files = sorted(args.results_dir.glob("*.jsonl"))
    files = [f for f in files if not f.stem.startswith("judge_") and (not args.configs or f.stem in args.configs)]

    header = [
        "config",
        "n",
        "type_food",
        "type_neg",
        "medical_sub",
        "kcal_all",
        "kcal_card",
        "kcal_label",
        "kcal_computed",
        "kcal_visual",
        "protein",
        "miss_median_dist",
        "lat_p50",
        "lat_p90",
        "$/call",
    ]
    print("| " + " | ".join(header) + " |")
    print("|" + "---|" * len(header))
    scored_all: dict[str, dict[str, dict]] = {}
    for f in files:
        rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        model = rows[0].get("model") if rows and rows[0].get("model") else None
        scored = [score_row(cases[r["id"]], truth.get(r["id"]), r) for r in rows if r["id"] in cases]
        scored_all[f.stem] = {s["id"]: s for s in scored}
        by_kind = defaultdict(list)
        for s in scored:
            by_kind[s["kind"]].append(s)
        food = [s for s in scored if s["kind"] not in ("neg", "med")]
        lat = [s["latency_s"] for s in scored if not s["error"] and s["latency_s"]]
        # модель для цены — по имени конфигурации
        from food_parsing_eval import CONFIGS

        cfg = f.stem.split("-")[0]
        model = CONFIGS.get(cfg, (None, None))[1]
        cost = sum(cost_usd(model, s["usage"]) for s in scored) / max(len(scored), 1) if model in PRICING else 0
        dists = [s["kcal_dist"] for s in food if s.get("kcal_dist") not in (None, 0.0)]
        line = [
            f.stem,
            str(len(scored)),
            pct([s["type_ok"] for s in food]),
            pct([s["type_ok"] for s in by_kind["neg"]]),
            pct([s.get("subtype_ok") for s in by_kind["med"]]),
            pct([s.get("kcal_ok") for s in food]),
            pct([s.get("kcal_ok") for s in by_kind["card"]]),
            pct([s.get("kcal_ok") for s in by_kind["label"]]),
            pct([s.get("kcal_ok") for s in by_kind["computed"] + by_kind["user"]]),
            pct([s.get("kcal_ok") for s in by_kind["visual"]]),
            pct([s.get("protein_ok") for s in food]),
            f"{100 * statistics.median(dists):.0f}%" if dists else "—",
            f"{p(lat, 0.5):.1f}s",
            f"{p(lat, 0.9):.1f}s",
            f"${cost:.4f}",
        ]
        print("| " + " | ".join(line) + " |")

    if args.detail:
        names = list(scored_all)
        print("\n| id | src | truth kcal | " + " | ".join(names) + " |")
        print("|---|---|---|" + "---|" * len(names))
        for cid, c in cases.items():
            t = truth.get(cid)
            cells = []
            for n in names:
                s = scored_all[n].get(cid)
                if not s:
                    cells.append("·")
                elif s["error"]:
                    cells.append("ERR")
                elif not s["type_ok"]:
                    cells.append("type✗")
                elif s.get("kcal_ok") is None:
                    cells.append("✓" if s["type_ok"] else "✗")
                else:
                    pk = s.get("pred_kcal")
                    cells.append(f"{'✓' if s['kcal_ok'] else '✗'}{pk:.0f}" if isinstance(pk, (int, float)) else "?")
            tr = f"{t['kcal'][0]}–{t['kcal'][1]}" if t else c["golden"]["type"]
            print(f"| {cid} | {(t or {}).get('source', c['golden']['type'])} | {tr} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()
