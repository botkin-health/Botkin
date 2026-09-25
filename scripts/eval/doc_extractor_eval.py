#!/usr/bin/env python3
"""Eval разбора медицинских документов (`core.health.doc_extractor`, issue #558).

Прогоняет фото/сканы документов через `extract_medical_data` с разными моделями и
сверяет с эталоном, размеченным вручную по самим бланкам: дата взятия/приёма, тип
документа, диагнозы, контрольные показатели. Считает то, что ломалось на реальных
загрузках: дата печати вместо даты взятия, числа у качественных анализов (мазки,
ПЦР), коды Z в диагнозах, активный B12 как общий, СРБ не в мг/л, строка в
`blood_tests` у нелабораторного документа.

Данные (фото и golden.json) — личные, лежат только в `data/eval/doc/` (gitignored).
Гонять с прод-сервера (с мака API недоступен):

    docker exec -d healthvault_bot sh -c 'cd /app && python -u scripts/eval/doc_extractor_eval.py \
        --models claude-haiku-4-5-20251001 claude-sonnet-5 > /app/data/eval/doc/run.log 2>&1'

Формат golden.json: {"cases": [{"file", "date" (ISO|null), "kind", "print_date"?,
"dup_group"?, "expect_keys"?, "expect_conditions"?}, ...]}.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

EVAL_DIR = ROOT / "data" / "eval" / "doc"

# $/1M токенов (input, output) — как в food_parsing_eval.PRICING, проверено 2026-09-13.
PRICING = {
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

_Z_CODE_RE = re.compile(r"\bZ\d{2}(?:\.\d+)?\b")


def _close(a: Any, b: float, rel: float = 0.02) -> bool:
    return isinstance(a, (int, float)) and not isinstance(a, bool) and abs(a - b) <= abs(b) * rel


def score_case(case: dict, pred: dict) -> dict:
    """Сверка одного ответа экстрактора с эталоном. Чистая функция — для тестов.

    Ключи результата: True/False по проверке либо None, если проверка к кейсу
    неприменима (например, `kind_ok` до того, как экстрактор начал отдавать doc_kind).
    """
    from core.health.doc_to_blood_test import build_blood_test_row

    pred = pred or {}
    values = pred.get("values") if isinstance(pred.get("values"), dict) else {}
    conditions = [str(c) for c in (pred.get("conditions") or [])]
    kind = case.get("kind")

    res: dict[str, Optional[bool]] = {
        "date_ok": pred.get("date") == case.get("date"),
        "print_date": bool(case.get("print_date")) and pred.get("date") == case.get("print_date"),
        "kind_ok": None if "doc_kind" not in pred else pred.get("doc_kind") == kind,
        "z_leak": any(_Z_CODE_RE.search(c) for c in conditions),
        "smear_values": (kind == "smear_pcr" and bool(values)) if kind == "smear_pcr" else None,
        "has_summary": bool(str(pred.get("summary") or "").strip()) if kind != "lab_panel" else None,
    }

    row = build_blood_test_row(pred, stored_name="2000-01-01_00000000.jpg", user_id=0)
    res["non_lab_row"] = (row.row is not None) if kind != "lab_panel" else None

    expect_keys = case.get("expect_keys") or {}
    if "holotranscobalamin" in expect_keys:
        res["b12_ok"] = "vitamin_B12" not in values and _close(
            values.get("holotranscobalamin"), expect_keys["holotranscobalamin"]
        )
    if "hs_CRP_mg_l" in expect_keys:
        res["crp_ok"] = _close(values.get("hs_CRP"), expect_keys["hs_CRP_mg_l"])

    expect_conditions = case.get("expect_conditions")
    if expect_conditions:
        res["conditions_ok"] = all(any(code in c for c in conditions) for code in expect_conditions)
    return res


def _price(model: str) -> tuple[float, float]:
    for prefix, p in PRICING.items():
        if model.startswith(prefix):
            return p
    return (0.0, 0.0)


async def run_model(model: str, cases: list[dict], files_dir: Path) -> list[dict]:
    import core.health.doc_extractor as de

    de._MODEL = model
    original_call = de._call_anthropic
    captured: dict[str, Any] = {}

    async def _capturing_call(messages):
        t0 = time.monotonic()
        resp = await original_call(messages)
        captured["latency"] = time.monotonic() - t0
        captured["usage"] = resp.get("usage") or {}
        return resp

    de._call_anthropic = _capturing_call
    rows = []
    try:
        for i, case in enumerate(cases, 1):
            captured.clear()
            path = files_dir / case["file"]
            pred = await de.extract_medical_data(path.read_bytes(), "image/jpeg")
            usage = captured.get("usage") or {}
            p_in, p_out = _price(model)
            cost = (usage.get("input_tokens", 0) * p_in + usage.get("output_tokens", 0) * p_out) / 1e6
            scored = score_case(case, pred)
            rows.append(
                {"file": case["file"], "pred": pred, "score": scored, "latency": captured.get("latency"), "cost": cost}
            )
            print(f"[{model}] {i}/{len(cases)} {case['file']}: {scored}", flush=True)
    finally:
        de._call_anthropic = original_call
    return rows


def summarize(model: str, rows: list[dict]) -> dict:
    def ratio(key: str, want: bool = True) -> str:
        vals = [r["score"].get(key) for r in rows if r["score"].get(key) is not None]
        if not vals:
            return "n/a"
        hit = sum(1 for v in vals if v is want)
        return f"{hit}/{len(vals)}"

    lat = [r["latency"] for r in rows if r.get("latency")]
    return {
        "model": model,
        "дата верна": ratio("date_ok"),
        "дата печати": ratio("print_date"),
        "тип верен": ratio("kind_ok"),
        "мазки без чисел": ratio("smear_values", want=False),
        "резюме есть": ratio("has_summary"),
        "Z в диагнозах": ratio("z_leak"),
        "диагнозы найдены": ratio("conditions_ok"),
        "B12 активный": ratio("b12_ok"),
        "СРБ мг/л": ratio("crp_ok"),
        "нелаб. строка в blood_tests": ratio("non_lab_row"),
        "p50, с": f"{statistics.median(lat):.1f}" if lat else "n/a",
        "$/док": f"{statistics.mean(r['cost'] for r in rows):.4f}" if rows else "n/a",
    }


def to_markdown(summaries: list[dict]) -> str:
    if not summaries:
        return ""
    cols = list(summaries[0].keys())
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(s[c]) for c in cols) + " |" for s in summaries]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--models", nargs="+", default=["claude-haiku-4-5-20251001"])
    ap.add_argument("--golden", type=Path, default=EVAL_DIR / "golden.json")
    ap.add_argument("--files-dir", type=Path, default=EVAL_DIR / "files")
    ap.add_argument("--limit", type=int, default=None, help="первые N кейсов (smoke)")
    ap.add_argument("--tag", default="", help="суффикс папки результатов")
    args = ap.parse_args()

    cases = json.loads(args.golden.read_text(encoding="utf-8"))["cases"][: args.limit]
    out = EVAL_DIR / "results" / (datetime.now().strftime("%Y%m%d_%H%M%S") + (f"_{args.tag}" if args.tag else ""))
    out.mkdir(parents=True, exist_ok=True)

    summaries = []
    for model in args.models:
        rows = asyncio.run(run_model(model, cases, args.files_dir))
        with (out / f"{model}.jsonl").open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
        summaries.append(summarize(model, rows))

    md = to_markdown(summaries)
    (out / "summary.md").write_text(md, encoding="utf-8")
    print("\n" + md)
    print(f"Результаты: {out}")


if __name__ == "__main__":
    main()
