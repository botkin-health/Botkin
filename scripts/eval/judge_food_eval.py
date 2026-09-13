#!/usr/bin/env python3
"""Слепой судья для спорных кейсов food-eval.

Эталон в cases.json — то, что распознал прод (Sonnet 4.6) и подтвердил пользователь,
поэтому сравнение «кандидат vs эталон» смещено в пользу прод-модели. Для кейсов, где
кандидат расходится с baseline по ккал > порога (или по типу), судья получает исходный
текст/фото и ДВЕ оценки в случайном порядке (A/B) и говорит, какая правдоподобнее.

    python3 scripts/eval/judge_food_eval.py <results_dir> --baseline sonnet46 --candidates haiku45 sonnet5

Пишет <results_dir>/judge_<candidate>.jsonl и сводку win/tie/loss. Каждый вызов — деньги.
"""

from __future__ import annotations

import argparse
import base64
import json
import random
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from food_parsing_eval import CASES_PATH, _env, _strip_fences  # noqa: E402

JUDGE_MODEL = "claude-opus-5"
KCAL_DISPUTE = 0.15

JUDGE_PROMPT = """Ты — эксперт-нутрициолог, судья. Пользователь дневника питания прислал сообщение (текст и/или фото).
Две независимые системы оценили состав и КБЖУ. Определи, какая оценка ближе к реальности.
Учитывай: указанные пользователем веса и данные этикеток обязательны к использованию; типичные порции;
калорийная плотность продуктов; для карточек рецептов (Elementaree и т.п.) — верна печатная калорийность порции.
Не отдавай предпочтение более подробной или более «уверенной» оценке — только правдоподобию чисел.

Ответь ТОЛЬКО JSON:
{"winner": "A" | "B" | "tie" | "both_wrong",
 "true_kcal_estimate": number,
 "reason": "1-2 предложения по-русски"}"""


def _load_rows(path: Path) -> dict[str, dict]:
    return {json.loads(l)["id"]: json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()}


def _summary(row: dict) -> str:
    try:
        parsed = json.loads(_strip_fences(row["raw"]))
        data = parsed.get("data") or {}
        items = data.get("items") or (data.get("food") or {}).get("items") or []
        tn = data.get("total_nutrition") or (data.get("food") or {}).get("total_nutrition") or {}
        lines = [
            f"- {i.get('name')}: {i.get('weight')} г, {i.get('calories')} ккал, Б{i.get('protein')} Ж{i.get('fats')} У{i.get('carbs')}"
            for i in items
        ]
        return (
            f"тип: {parsed.get('type')}\n"
            + "\n".join(lines)
            + f"\nИТОГО: {tn.get('calories')} ккал, Б{tn.get('protein')} Ж{tn.get('fats')} У{tn.get('carbs')}"
        )
    except Exception:  # noqa: BLE001
        return f"тип: {row.get('pred_type')}, итого {row.get('pred_kcal')} ккал (детали не распарсились)"


def _disputed(base: dict, cand: dict) -> bool:
    if cand.get("error") or base.get("error"):
        return False
    if cand.get("pred_type") != base.get("pred_type"):
        return True
    bk, ck = base.get("pred_kcal"), cand.get("pred_kcal")
    if isinstance(bk, (int, float)) and isinstance(ck, (int, float)) and bk > 0:
        return abs(ck - bk) / bk > KCAL_DISPUTE
    return False


def judge(case: dict, a: str, b: str, photo_dir: Path | None) -> dict:
    content = []
    photo = case.get("photo")
    if photo:
        p = photo_dir / Path(photo).name if photo_dir else Path(photo)
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.b64encode(p.read_bytes()).decode(),
                },
            }
        )
    content.append(
        {
            "type": "text",
            "text": f"СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ: {case.get('text') or '[только фото]'}\n\nОЦЕНКА A:\n{a}\n\nОЦЕНКА B:\n{b}",
        }
    )
    payload = {
        "model": JUDGE_MODEL,
        "max_tokens": 1500,
        "output_config": {"effort": "medium"},
        "system": JUDGE_PROMPT,
        "messages": [{"role": "user", "content": content}],
    }
    headers = {
        "x-api-key": _env("ANTHROPIC_API_KEY"),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    for attempt in range(4):
        r = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload, timeout=120)
        if r.status_code in (429, 529) or r.status_code >= 500:
            time.sleep(2 ** (attempt + 1))
            continue
        break
    if r.status_code >= 400:
        return {"error": f"http {r.status_code}: {r.text[:200]}"}
    j = r.json()
    text = "".join(bk.get("text", "") for bk in j.get("content", []) if bk.get("type") == "text")
    u = j.get("usage", {})
    cost = (u.get("input_tokens", 0) * 5 + u.get("output_tokens", 0) * 25) / 1e6
    try:
        verdict = json.loads(_strip_fences(text))
    except Exception:  # noqa: BLE001
        return {"error": "judge json", "raw": text[:300], "cost": cost}
    verdict["cost"] = cost
    return verdict


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("results_dir", type=Path)
    ap.add_argument("--baseline", default="sonnet46")
    ap.add_argument("--candidates", nargs="+", required=True)
    ap.add_argument("--photo-dir", type=Path, default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    cases = {c["id"]: c for c in json.loads(CASES_PATH.read_text(encoding="utf-8"))}
    base = _load_rows(args.results_dir / f"{args.baseline}.jsonl")
    rng = random.Random(args.seed)

    for cand_name in args.candidates:
        cand = _load_rows(args.results_dir / f"{cand_name}.jsonl")
        disputed = [
            cid
            for cid in cand
            if cid in base
            and cid in cases
            and cases[cid]["golden"]["type"] == "food"
            and _disputed(base[cid], cand[cid])
        ]
        if args.limit:
            disputed = disputed[: args.limit]
        print(f"[{cand_name}] спорных кейсов: {len(disputed)} из {len(cand)}")
        tally = {"cand_wins": 0, "base_wins": 0, "tie": 0, "both_wrong": 0, "error": 0}
        total_cost = 0.0
        with (args.results_dir / f"judge_{cand_name}.jsonl").open("w", encoding="utf-8") as fh:
            for i, cid in enumerate(disputed, 1):
                cand_first = rng.random() < 0.5
                a, b = (
                    (_summary(cand[cid]), _summary(base[cid]))
                    if cand_first
                    else (_summary(base[cid]), _summary(cand[cid]))
                )
                v = judge(cases[cid], a, b, args.photo_dir)
                total_cost += v.get("cost", 0)
                if "error" in v:
                    tally["error"] += 1
                    outcome = "error"
                else:
                    w = v.get("winner")
                    if w in ("tie", "both_wrong"):
                        outcome = w
                    elif (w == "A") == cand_first:
                        outcome = "cand_wins"
                    else:
                        outcome = "base_wins"
                    tally[outcome] += 1
                rec = {
                    "id": cid,
                    "outcome": outcome,
                    "base_kcal": base[cid].get("pred_kcal"),
                    "cand_kcal": cand[cid].get("pred_kcal"),
                    "judge": v,
                    "text": (cases[cid].get("text") or "[фото]")[:80],
                }
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                print(
                    f"  {i}/{len(disputed)} {cid:<14} {outcome:<10} base={base[cid].get('pred_kcal')} cand={cand[cid].get('pred_kcal')} true≈{v.get('true_kcal_estimate')} — {v.get('reason', v.get('error', ''))[:90]}"
                )
        print(f"[{cand_name}] {tally} judge cost ${total_cost:.2f}\n")


if __name__ == "__main__":
    main()
