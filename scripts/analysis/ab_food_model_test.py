#!/usr/bin/env python3
"""A/B: разбор фото еды Sonnet 4.6 (прод-baseline) vs Haiku 4.5 (дешевле в 3×).

Прогоняет один и тот же набор фото через тот же пайплайн (SYSTEM_PROMPT,
temperature 0.1) на обеих моделях и сравнивает КБЖУ + распознанные блюда.
Sonnet — это эталон (то, что юзеры получают сейчас), вопрос: совпадает ли Haiku.

Не трогает прод. Только читает локальные фото + дёргает Anthropic API.
"""

import base64
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config import get_settings  # noqa: E402
from core.llm.router import SYSTEM_PROMPT  # noqa: E402
from core.llm.models import parse_llm_response  # noqa: E402
from core.food.nutrition import process_llm_food_data  # noqa: E402

API_KEY = get_settings().anthropic_api_key
URL = "https://api.anthropic.com/v1/messages"
MACROS = ["calories", "protein", "fats", "carbs"]
# Цены $/1M (вход, выход) — сверено со справкой Claude API 2026.
PRICE = {"claude-sonnet-4-6": (3.0, 15.0), "claude-haiku-4-5": (1.0, 5.0)}


def encode(p: Path) -> str:
    return base64.b64encode(p.read_bytes()).decode("utf-8")


def call(model: str, b64: str) -> dict:
    """Один вызов модели на фото. effort только для Sonnet (Haiku его не поддерживает)."""
    payload = {
        "model": model,
        "max_tokens": 2000,
        "temperature": 0.1,
        "system": [{"type": "text", "text": SYSTEM_PROMPT}],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                ],
            }
        ],
    }
    if model == "claude-sonnet-4-6":
        payload["output_config"] = {"effort": "low"}
    t0 = time.monotonic()
    for attempt in range(3):
        r = requests.post(
            URL,
            headers={
                "Content-Type": "application/json",
                "x-api-key": API_KEY,
                "anthropic-version": "2023-06-01",
            },
            json=payload,
            timeout=60,
        )
        if r.status_code in (429, 529):
            time.sleep(2 ** (attempt + 1))
            continue
        r.raise_for_status()
        break
    dt = time.monotonic() - t0
    res = r.json()
    usage = res.get("usage", {})
    txt = res["content"][0]["text"].strip()
    if txt.startswith("```"):
        txt = txt.split("\n", 1)[1].rsplit("```", 1)[0]
    parsed = parse_llm_response(json.loads(txt))
    items, totals = process_llm_food_data(parsed, None) if parsed else ([], {})
    cost = (
        usage.get("input_tokens", 0) * PRICE[model][0] + usage.get("output_tokens", 0) * PRICE[model][1]
    ) / 1_000_000
    names = [it.get("product") or it.get("name") or "?" for it in items]
    return {
        "totals": totals,
        "names": names,
        "n_items": len(items),
        "in_tok": usage.get("input_tokens", 0),
        "out_tok": usage.get("output_tokens", 0),
        "cost": cost,
        "latency": dt,
        "type": parsed.get("type") if parsed else "none",
    }


def pct_diff(a: float, b: float) -> float:
    """% отклонения haiku(b) от sonnet(a) относительно sonnet."""
    if a == 0:
        return 0.0 if b == 0 else 100.0
    return abs(b - a) / a * 100.0


def main():
    photos = [Path(p) for p in sys.argv[1:]]
    if not photos:
        sys.exit("usage: ab_food_model_test.py <photo1> <photo2> ...")
    print(f"A/B food model test — {len(photos)} фото\n{'=' * 70}")
    agg = {m: [] for m in MACROS}
    cost_s = cost_h = 0.0
    lat_s = lat_h = 0.0
    within15 = within25 = food_both = 0
    rows = []
    for i, ph in enumerate(photos, 1):
        try:
            b64 = encode(ph)
            s = call("claude-sonnet-4-6", b64)
            h = call("claude-haiku-4-5", b64)
        except Exception as e:
            print(f"[{i}] {ph.name[:20]} — ОШИБКА: {e}")
            continue
        cost_s += s["cost"]
        cost_h += h["cost"]
        lat_s += s["latency"]
        lat_h += h["latency"]
        st, ht = s["totals"], h["totals"]
        cal_s, cal_h = st.get("calories", 0), ht.get("calories", 0)
        is_food = s["type"] == "food" and h["type"] == "food"
        if is_food:
            food_both += 1
            cd = pct_diff(cal_s, cal_h)
            for m in MACROS:
                agg[m].append(pct_diff(st.get(m, 0), ht.get(m, 0)))
            if cd <= 15:
                within15 += 1
            if cd <= 25:
                within25 += 1
        rows.append((i, ph.name[:16], cal_s, cal_h, s["names"][:3], h["names"][:3], s["type"], h["type"]))
        print(
            f"[{i}] ккал S={cal_s:.0f} H={cal_h:.0f}  Δ={pct_diff(cal_s, cal_h):.0f}%  "
            f"| S:{','.join(str(x) for x in s['names'][:3])[:40]} || H:{','.join(str(x) for x in h['names'][:3])[:40]}"
        )
    n = max(food_both, 1)
    print(f"\n{'=' * 70}\nИТОГ ({food_both} фото распознаны как еда обеими)")
    for m in MACROS:
        vals = agg[m]
        mean = sum(vals) / len(vals) if vals else 0
        print(f"  {m:10s}: средн. |Δ| Haiku vs Sonnet = {mean:.1f}%")
    print(f"  Калории в пределах ±15% от Sonnet: {within15}/{food_both} ({100 * within15 / n:.0f}%)")
    print(f"  Калории в пределах ±25% от Sonnet: {within25}/{food_both} ({100 * within25 / n:.0f}%)")
    print(
        f"\n  Стоимость: Sonnet ${cost_s:.4f} | Haiku ${cost_h:.4f} | экономия {100 * (1 - cost_h / max(cost_s, 1e-9)):.0f}%"
    )
    print(f"  Латентность средняя: Sonnet {lat_s / len(photos):.1f}s | Haiku {lat_h / len(photos):.1f}s")


if __name__ == "__main__":
    main()
