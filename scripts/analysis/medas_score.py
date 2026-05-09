#!/usr/bin/env python3
"""
CLI-обёртка над core/health/medas.py для анализа nutrition_log без дашборда.

Использование:
  python3 scripts/analysis/medas_score.py                # 30 дней (default)
  python3 scripts/analysis/medas_score.py --days 7       # 7 дней
  python3 scripts/analysis/medas_score.py --days 90      # 90 дней
  python3 scripts/analysis/medas_score.py --debug        # классификация каждого продукта
  python3 scripts/analysis/medas_score.py --unknown      # неклассифицированные
  python3 scripts/analysis/medas_score.py --with-wine    # включить правило #8 (вино, MEDAS-стандарт)

Источник логики: core/health/medas.py (тот же модуль использует dashboard).
"""

from __future__ import annotations
import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

# Импорт из соседнего проекта (HealthVault-engine на GDrive)
PROJECT_ROOT = Path(
    "/Users/alexlyskovsky/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/Projects/Vibe coding/HealthVault-engine"
)
sys.path.insert(0, str(PROJECT_ROOT))

from core.health.medas import compute_medas, classify_food, to_portions  # noqa: E402

NUTRITION_FILE = Path("data/nutrition/nutrition_log_remote.json")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--debug", action="store_true")
    p.add_argument("--unknown", action="store_true")
    p.add_argument(
        "--with-wine",
        action="store_true",
        help="Включить правило #8 о ≥7 бокалах вина (MEDAS-стандарт). Default — выключено, AHA не одобряет.",
    )
    args = p.parse_args()

    nut = json.loads(NUTRITION_FILE.read_text())
    today = date.today()
    cutoff = today - timedelta(days=args.days)

    items_flat: list[dict] = []
    classified: dict = defaultdict(lambda: {"count": 0, "total_g": 0, "tags": None})
    unknown: dict = defaultdict(lambda: {"count": 0, "total_g": 0})

    for meal in nut:
        d_str = meal.get("date")
        if not d_str:
            continue
        try:
            d = date.fromisoformat(d_str)
        except Exception:
            continue
        if d < cutoff or d > today:
            continue
        for it in meal.get("items") or []:
            if not isinstance(it, dict):
                continue
            food = (it.get("food") or it.get("name") or "").strip()
            grams = float(it.get("amount") or it.get("weight") or 0)
            if not food or grams <= 0:
                continue
            items_flat.append({"date": d_str, "food": food, "amount": grams})
            tags = classify_food(food)
            if tags:
                classified[food]["count"] += 1
                classified[food]["total_g"] += grams
                classified[food]["tags"] = tags
            else:
                unknown[food]["count"] += 1
                unknown[food]["total_g"] += grams

    result = compute_medas(items_flat, n_days=args.days, skip_wine_rule=not args.with_wine)

    print(f"\n{'=' * 70}")
    print(f"🥗 MEDAS — Mediterranean Diet Score за последние {args.days} дней")
    print(f"   Период: {cutoff.isoformat()} → {today.isoformat()}")
    if not args.with_wine:
        print("   ⚠ Правило #8 (≥7 бокалов вина/нед) ИСКЛЮЧЕНО — AHA-современная позиция.")
    print(f"{'=' * 70}\n")
    print(f"📊 Итог: {result['points']}/{result['max_points']} баллов → {result['score_100']}/100")
    verdict_emoji = {"low": "🔴 НИЗКАЯ", "medium": "🟡 СРЕДНЯЯ", "high": "🟢 ВЫСОКАЯ"}
    print(f"   {verdict_emoji[result['verdict']]} приверженность\n")

    print(f"📝 Детализация ({result['max_points']} правил):")
    for i, (label, ok, detail) in enumerate(result["items"], 1):
        if not args.with_wine and i == 8:
            continue  # скрываем wine rule если выключено
        mark = "✅" if ok else "❌"
        print(f"   {mark} {i}. {label}")
        print(f"      → {detail}")

    print("\n📈 Сводка ключевых метрик:")
    for k, v in result["raw_metrics"].items():
        print(f"   {k}: {v}")

    if args.debug:
        print("\n🔍 Топ классифицированных продуктов:")
        srt = sorted(classified.items(), key=lambda x: -x[1]["count"])[:30]
        for food, info in srt:
            print(f"   [{info['count']:>3}× {info['total_g']:>6.0f}г] {food} → {info['tags']}")

    if (args.unknown or unknown) and unknown:
        srt = sorted(unknown.items(), key=lambda x: -x[1]["count"])
        print(f"\n⚠️  НЕКЛАССИФИЦИРОВАННЫЕ ({len(srt)} уникальных):")
        for food, info in srt[:40]:
            print(f"   {info['count']:>4}× {info['total_g']:>6.0f}г  {food}")
        if len(srt) > 40:
            print(f"   ... и ещё {len(srt) - 40}")


if __name__ == "__main__":
    main()
