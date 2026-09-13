#!/usr/bin/env python3
"""Ретроспектива расходов на LLM: факт по месяцам/категориям из llm_usage_log
и контрфакт «если бы оптимизация парсинга еды стояла с первого дня».

Контрфакт для food_text/food_photo: те же токены, но
  * цены Sonnet 5 вместо Sonnet 4.6 ($2/$10, cache write $2.5, read $0.2),
  * системный промпт короче в PROMPT_RATIO раз → cache_write/cache_read токены × PROMPT_RATIO
    (обычный input и output не меняются — это текст пользователя и ответ).
Агент (agent_chat*) не трогаем — он вне этой волны оптимизации.

    python3 scripts/eval/cost_retrospective.py            # таблица в stdout (markdown)
"""

from __future__ import annotations

import json
import subprocess
from collections import defaultdict

SSH_HOST = "root@116.203.213.137"
PG = "docker exec healthvault_postgres psql -U healthvault -d healthvault -At -c"

# Урезанный промпт: ~11.7K символов против 37.4K (см. core/llm/prompts/food_router_system.txt)
PROMPT_RATIO = 11689 / 37383

NEW_FOOD_PRICE = (2.00, 10.00, 2.50, 0.20)  # claude-sonnet-5: in, out, cache_write, cache_read

QUERY = """
SELECT json_agg(t) FROM (
  SELECT to_char(created_at,'YYYY-MM') AS month, purpose, model,
         count(*) AS calls,
         sum(input_tokens) AS inp, sum(output_tokens) AS outp,
         sum(cache_creation_tokens) AS cw, sum(cache_read_tokens) AS cr,
         sum(cost_usd) AS usd
  FROM llm_usage_log GROUP BY 1,2,3 ORDER BY 1,2,3
) t;
"""


def counterfactual_food(row: dict) -> float:
    inp, outp, cw, cr = NEW_FOOD_PRICE
    return (row["inp"] * inp + row["outp"] * outp + row["cw"] * PROMPT_RATIO * cw + row["cr"] * PROMPT_RATIO * cr) / 1e6


def main() -> None:
    raw = subprocess.run(["ssh", SSH_HOST, f'{PG} "{QUERY}"'], check=True, capture_output=True, text=True).stdout
    rows = json.loads(raw.strip())
    by_month: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in rows:
        cat = "еда" if r["purpose"].startswith("food") else "агент"
        m = by_month[r["month"]]
        m[f"{cat}_факт"] += float(r["usd"])
        m[f"{cat}_контрфакт"] += counterfactual_food(r) if cat == "еда" else float(r["usd"])
        m["calls"] += r["calls"]

    print("| месяц | вызовов | еда факт | еда «если бы» | агент | итого факт | итого «если бы» | экономия |")
    print("|---|---|---|---|---|---|---|---|")
    tot = defaultdict(float)
    for month, m in sorted(by_month.items()):
        fact = m["еда_факт"] + m["агент_факт"]
        cf = m["еда_контрфакт"] + m["агент_факт"]
        for k, v in m.items():
            tot[k] += v
        print(
            f"| {month} | {int(m['calls'])} | ${m['еда_факт']:.2f} | ${m['еда_контрфакт']:.2f} | ${m['агент_факт']:.2f} | ${fact:.2f} | ${cf:.2f} | {100 * (1 - cf / fact):.0f}% |"
        )
    fact = tot["еда_факт"] + tot["агент_факт"]
    cf = tot["еда_контрфакт"] + tot["агент_факт"]
    print(
        f"| **всего** | {int(tot['calls'])} | ${tot['еда_факт']:.2f} | ${tot['еда_контрфакт']:.2f} | ${tot['агент_факт']:.2f} | **${fact:.2f}** | **${cf:.2f}** | **{100 * (1 - cf / fact):.0f}%** |"
    )
    print(
        f"\nЕда: факт ${tot['еда_факт']:.2f} → «если бы» ${tot['еда_контрфакт']:.2f} (−{100 * (1 - tot['еда_контрфакт'] / tot['еда_факт']):.0f}%). "
        f"Учёт ведётся с 2026-05-20; до этого — только инвойсы консоли."
    )

    print("\n| категория | модель | вызовов | факт |")
    print("|---|---|---|---|")
    agg = defaultdict(lambda: [0, 0.0])
    for r in rows:
        a = agg[(r["purpose"], r["model"])]
        a[0] += r["calls"]
        a[1] += float(r["usd"])
    for (p, mdl), (c, u) in sorted(agg.items(), key=lambda kv: -kv[1][1]):
        print(f"| {p} | {mdl} | {c} | ${u:.2f} |")


if __name__ == "__main__":
    main()
