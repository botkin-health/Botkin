#!/usr/bin/env python3
"""Eval парсинга еды: прогоняет замороженный набор кейсов через разные модели/промпты
и сравнивает с эталоном (то, что пользователи подтвердили кнопкой «Сохранить»).

Метрики на конфигурацию: валидный JSON, совпадение типа, ккал в пределах ±15%,
белок в пределах max(5 г, 25%), латентность p50/p90, $ за вызов (по прайсу ниже).
Каждый вызов — реальные деньги; конфигурации гоняются ПОСЛЕДОВАТЕЛЬНО, чтобы кэш
и латентность были сравнимы.

    python3 scripts/eval/food_parsing_eval.py --configs sonnet46 haiku45 --limit 5
    python3 scripts/eval/food_parsing_eval.py --configs all --prompt-file <альтернативный промпт>

Результаты — data/eval/food/results/<timestamp>/{summary.md,<config>.jsonl}.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.llm.models import parse_llm_response  # noqa: E402
from core.llm.router import SYSTEM_PROMPT  # noqa: E402

CASES_PATH = ROOT / "data" / "eval" / "food" / "cases.json"
RESULTS_DIR = ROOT / "data" / "eval" / "food" / "results"

KCAL_TOL = 0.15
PROTEIN_TOL_G = 5.0
PROTEIN_TOL_REL = 0.25
TIMEOUT_S = 60


# $/1M токенов: (input, output, cache_write, cache_read). Источники — официальные
# страницы цен, проверены 2026-09-13; для Gemini/OpenAI cache_write=0 (неявный кэш).
PRICING = {
    "claude-sonnet-4-6": (3.00, 15.00, 3.75, 0.30),
    "claude-sonnet-5": (2.00, 10.00, 2.50, 0.20),
    "claude-haiku-4-5": (1.00, 5.00, 1.25, 0.10),
    "gemini-3.6-flash": (0.75, 3.75, 0.0, 0.1875),
    "gemini-3.5-flash-lite": (0.30, 2.50, 0.0, 0.075),
    "gpt-5-mini": (0.25, 2.00, 0.0, 0.03),
    "gpt-5-nano": (0.05, 0.40, 0.0, 0.005),
}

CONFIGS = {
    "sonnet46": ("anthropic", "claude-sonnet-4-6"),
    "sonnet5": ("anthropic", "claude-sonnet-5"),
    "haiku45": ("anthropic", "claude-haiku-4-5"),
    "gemini36": ("gemini", "gemini-3.6-flash"),
    "gemini35lite": ("gemini", "gemini-3.5-flash-lite"),
    "gpt5mini": ("openai", "gpt-5-mini"),
    "gpt5nano": ("openai", "gpt-5-nano"),
}

PHOTO_DEFAULT_CAPTION = "Что на фото? Название продукта или блюда, вес и КБЖУ."


@dataclass
class CallResult:
    parsed: dict | None
    raw_text: str
    latency_s: float
    usage: dict = field(default_factory=dict)  # input/output/cache_write/cache_read
    error: str | None = None


def _env(name: str) -> str:
    val = os.getenv(name, "")
    if not val:
        env_file = ROOT / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith(f"{name}="):
                    val = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not val:
        raise SystemExit(f"{name} не задан (ни в env, ни в .env)")
    return val


def _b64(path: str) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode()


def _strip_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1]
        s = s.rsplit("```", 1)[0]
    return s.strip()


def _finish(raw: str, t0: float, usage: dict) -> CallResult:
    latency = time.perf_counter() - t0
    try:
        parsed = parse_llm_response(json.loads(_strip_fences(raw)))
        return CallResult(parsed, raw, latency, usage)
    except Exception as e:  # noqa: BLE001
        return CallResult(None, raw, latency, usage, error=f"json: {e}")


# ── провайдеры ───────────────────────────────────────────────────────────────


def call_anthropic(model: str, system: str, case: dict) -> CallResult:
    content = []
    if case.get("photo"):
        content.append(
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _b64(case["photo"])}}
        )
    content.append({"type": "text", "text": f"USER MESSAGE: {case['text'] or PHOTO_DEFAULT_CAPTION}"})
    payload = {
        "model": model,
        "max_tokens": 2000,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": content}],
    }
    # Sonnet 5 не принимает temperature; Haiku 4.5 не знает effort — как в проде для 4.6.
    if model != "claude-sonnet-5":
        payload["temperature"] = 0.1
    if model != "claude-haiku-4-5":
        payload["output_config"] = {"effort": "low"}
    headers = {
        "x-api-key": _env("ANTHROPIC_API_KEY"),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    t0 = time.perf_counter()
    r = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload, timeout=TIMEOUT_S)
    if r.status_code >= 400:
        return CallResult(None, r.text[:500], time.perf_counter() - t0, error=f"http {r.status_code}")
    j = r.json()
    u = j.get("usage", {})
    usage = {
        "input": u.get("input_tokens", 0),
        "output": u.get("output_tokens", 0),
        "cache_write": u.get("cache_creation_input_tokens", 0),
        "cache_read": u.get("cache_read_input_tokens", 0),
    }
    text = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
    return _finish(text, t0, usage)


def call_gemini(model: str, system: str, case: dict) -> CallResult:
    parts = []
    if case.get("photo"):
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": _b64(case["photo"])}})
    parts.append({"text": f"USER MESSAGE: {case['text'] or PHOTO_DEFAULT_CAPTION}"})
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.1,
            "response_mime_type": "application/json",
            # Gemini 3.x думает по умолчанию (2K thinking-токенов и 5–12 с на простой JSON);
            # thinkingBudget:0 для 3.x — INVALID_ARGUMENT, работает только thinkingLevel.
            "thinkingConfig": {"thinkingLevel": "minimal"},
        },
    }
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={_env('GEMINI_API_KEY')}"
    )
    t0 = time.perf_counter()
    r = requests.post(url, json=payload, timeout=TIMEOUT_S)
    if r.status_code >= 400:
        return CallResult(None, r.text[:500], time.perf_counter() - t0, error=f"http {r.status_code}")
    j = r.json()
    u = j.get("usageMetadata", {})
    cached = u.get("cachedContentTokenCount", 0)
    usage = {
        "input": u.get("promptTokenCount", 0) - cached,
        "output": u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0),
        "cache_write": 0,
        "cache_read": cached,
    }
    try:
        text = j["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        return CallResult(None, json.dumps(j)[:500], time.perf_counter() - t0, usage, error="no candidates")
    return _finish(text, t0, usage)


def call_openai(model: str, system: str, case: dict) -> CallResult:
    content = [{"type": "text", "text": f"USER MESSAGE: {case['text'] or PHOTO_DEFAULT_CAPTION}"}]
    if case.get("photo"):
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{_b64(case['photo'])}"}})
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
        "max_completion_tokens": 2000,
        "response_format": {"type": "json_object"},
    }
    if model.startswith("gpt-5"):
        payload["reasoning_effort"] = "minimal"
    else:
        payload["temperature"] = 0.1
    headers = {"Authorization": f"Bearer {_env('OPENAI_API_KEY')}"}
    t0 = time.perf_counter()
    r = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=TIMEOUT_S)
    if r.status_code >= 400:
        return CallResult(None, r.text[:500], time.perf_counter() - t0, error=f"http {r.status_code}")
    j = r.json()
    u = j.get("usage", {})
    cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
    usage = {
        "input": u.get("prompt_tokens", 0) - cached,
        "output": u.get("completion_tokens", 0),
        "cache_write": 0,
        "cache_read": cached,
    }
    text = j["choices"][0]["message"].get("content") or ""
    return _finish(text, t0, usage)


def _with_retry(fn):
    """429/529/5xx → до 4 повторов с экспоненциальной паузой (как в прод-роутере)."""

    def wrapped(model: str, system: str, case: dict) -> CallResult:
        res = None
        for attempt in range(5):
            res = fn(model, system, case)
            code = (res.error or "").replace("http ", "")
            if not (res.error and code.isdigit() and (code in ("429", "529") or code.startswith("5"))):
                return res
            time.sleep(2 ** (attempt + 1))
        return res

    return wrapped


PROVIDERS = {
    "anthropic": _with_retry(call_anthropic),
    "gemini": _with_retry(call_gemini),
    "openai": _with_retry(call_openai),
}


# ── скоринг ──────────────────────────────────────────────────────────────────


def cost_usd(model: str, u: dict) -> float:
    inp, out, cw, cr = PRICING[model]
    return (
        u.get("input", 0) * inp + u.get("output", 0) * out + u.get("cache_write", 0) * cw + u.get("cache_read", 0) * cr
    ) / 1e6


def _pred_totals(parsed: dict) -> dict:
    data = parsed.get("data") or {}
    tn = data.get("total_nutrition") or {}
    if not tn and parsed.get("type") == "mixed":
        tn = ((data.get("food") or {}).get("total_nutrition")) or {}
    return tn


def score(case: dict, res: CallResult) -> dict:
    g = case["golden"]
    row = {
        "id": case["id"],
        "source": case["source"],
        "json_ok": res.parsed is not None,
        "type_ok": False,
        "kcal_ok": None,
        "protein_ok": None,
        "kcal_rel_err": None,
        "pred_type": None,
        "pred_kcal": None,
        "latency_s": round(res.latency_s, 2),
        "usage": res.usage,
        "error": res.error,
    }
    if not res.parsed:
        return row
    pred_type = res.parsed.get("type")
    row["pred_type"] = pred_type
    row["type_ok"] = pred_type == g["type"] or (g["type"] == "food" and pred_type == "mixed")
    if g["type"] == "medical" and g.get("subtype"):
        pred_sub = (res.parsed.get("data") or {}).get("subtype")
        row["pred_subtype"] = pred_sub
        row["subtype_ok"] = row["type_ok"] and pred_sub in g["subtype"].split("|")
    if g["type"] != "food" or not row["type_ok"]:
        return row
    tn = _pred_totals(res.parsed)
    pk, pp = tn.get("calories"), tn.get("protein")
    row["pred_kcal"] = pk
    if g.get("calories") and pk is not None:
        rel = abs(pk - g["calories"]) / max(g["calories"], 1)
        row["kcal_rel_err"] = round(rel, 3)
        row["kcal_ok"] = rel <= KCAL_TOL
    if g.get("protein") is not None and pp is not None:
        tol = max(PROTEIN_TOL_G, PROTEIN_TOL_REL * g["protein"])
        row["protein_ok"] = abs(pp - g["protein"]) <= tol
    return row


def _pct(vals: list) -> str:
    vals = [v for v in vals if v is not None]
    return f"{100 * sum(vals) / len(vals):.0f}%" if vals else "—"


def _p(vals: list[float], q: float) -> float:
    if not vals:
        return 0.0
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(q * len(vals)))]


def summarize(name: str, model: str, rows: list[dict]) -> dict:
    food = [r for r in rows if not r["id"].startswith(("neg-", "med-"))]
    neg = [r for r in rows if r["id"].startswith("neg-")]
    med = [r for r in rows if r["id"].startswith("med-")]
    lat = [r["latency_s"] for r in rows if not r["error"]]
    costs = [cost_usd(model, r["usage"]) for r in rows]
    kcal_errs = [r["kcal_rel_err"] for r in food if r["kcal_rel_err"] is not None]
    return {
        "config": name,
        "model": model,
        "n": len(rows),
        "json_ok": _pct([r["json_ok"] for r in rows]),
        "type_ok_food": _pct([r["type_ok"] for r in food]),
        "type_ok_neg": _pct([r["type_ok"] for r in neg]),
        "medical_ok": _pct([r.get("subtype_ok") for r in med]),
        "kcal_within_15": _pct([r["kcal_ok"] for r in food]),
        "kcal_median_err": f"{100 * statistics.median(kcal_errs):.0f}%" if kcal_errs else "—",
        "protein_ok": _pct([r["protein_ok"] for r in food]),
        "lat_p50": f"{_p(lat, 0.5):.1f}s",
        "lat_p90": f"{_p(lat, 0.9):.1f}s",
        "cost_total": f"${sum(costs):.3f}",
        "cost_per_call": f"${sum(costs) / max(len(costs), 1):.4f}",
        "errors": sum(1 for r in rows if r["error"]),
    }


def to_markdown(summaries: list[dict]) -> str:
    cols = list(summaries[0].keys())
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(s[c]) for c in cols) + " |" for s in summaries]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", nargs="+", default=["sonnet46"], help=f"{list(CONFIGS)} или all")
    ap.add_argument("--limit", type=int, default=None, help="первые N кейсов (smoke-тест)")
    ap.add_argument("--only", choices=["text", "photo", "neg"], default=None)
    ap.add_argument("--prompt-file", type=Path, default=None, help="альтернативный system-промпт")
    ap.add_argument("--tag", default="", help="суффикс к имени конфигурации в отчёте")
    ap.add_argument(
        "--photo-dir", type=Path, default=None, help="каталог с фото (ищем по имени файла) — для запуска на сервере"
    )
    ap.add_argument(
        "--resume-from",
        type=Path,
        default=None,
        help="каталог results/*: уже прогнанные кейсы не повторять, строки переносятся",
    )
    args = ap.parse_args()

    names = list(CONFIGS) if args.configs == ["all"] else args.configs
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if args.photo_dir:
        for c in cases:
            if c.get("photo"):
                c["photo"] = str(args.photo_dir / Path(c["photo"]).name)
    if args.only:
        cases = [
            c
            for c in cases
            if (
                c["id"].startswith("neg-")
                if args.only == "neg"
                else c["source"] == args.only and not c["id"].startswith("neg-")
            )
        ]
    if args.limit:
        cases = cases[: args.limit]
    system = args.prompt_file.read_text(encoding="utf-8") if args.prompt_file else SYSTEM_PROMPT
    print(f"cases={len(cases)} configs={names} prompt_chars={len(system)}")

    out_dir = RESULTS_DIR / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    summaries = []
    for name in names:
        provider, model = CONFIGS[name]
        call = PROVIDERS[provider]
        rows = []
        label = f"{name}{('-' + args.tag) if args.tag else ''}"
        done: dict[str, dict] = {}
        prev = args.resume_from / f"{label}.jsonl" if args.resume_from else None
        if prev and prev.exists():
            done = {
                json.loads(l)["id"]: json.loads(l) for l in prev.read_text(encoding="utf-8").splitlines() if l.strip()
            }
        with (out_dir / f"{label}.jsonl").open("w", encoding="utf-8") as fh:
            for i, case in enumerate(cases, 1):
                if case["id"] in done and not done[case["id"]].get("error"):
                    fh.write(json.dumps(done[case["id"]], ensure_ascii=False) + "\n")
                    rows.append(done[case["id"]])
                    continue
                res = call(model, system, case)
                row = score(case, res)
                row["raw"] = res.raw_text[:8000]
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                rows.append(row)
                flag = "ERR" if res.error else ("ok" if row["type_ok"] and row["kcal_ok"] is not False else "miss")
                print(
                    f"[{label}] {i}/{len(cases)} {case['id']:<14} {flag:<4} {row['latency_s']:>5}s ${cost_usd(model, res.usage):.4f} {res.error or ''}"
                )
        summaries.append(summarize(label, model, rows))
        print(to_markdown([summaries[-1]]))

    (out_dir / "summary.md").write_text(to_markdown(summaries) + "\n", encoding="utf-8")
    (out_dir / "meta.json").write_text(
        json.dumps(
            {"cases": len(cases), "prompt_chars": len(system), "prompt_file": str(args.prompt_file or "SYSTEM_PROMPT")},
            indent=1,
        )
    )
    print(f"\n{to_markdown(summaries)}\n→ {out_dir}")


if __name__ == "__main__":
    main()
