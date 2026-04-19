#!/usr/bin/env python3
"""Sync alcohol_daily.json from nutrition_log_remote.json (runs during /sync)."""

import json
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
NUT_FILE = BASE / "data/nutrition/nutrition_log_remote.json"
OUT_FILE = BASE / "data/nutrition/alcohol_daily.json"


def main():
    if not NUT_FILE.exists():
        print("   ⚠️  nutrition_log_remote.json не найден, пропускаю")
        return

    entries = json.loads(NUT_FILE.read_text())

    by_day: dict = defaultdict(lambda: {"drinks": 0.0, "calories": 0, "items": []})

    for entry in entries:
        day = (entry.get("date") or "")[:10]
        if not day:
            continue
        for item in entry.get("items") or []:
            drinks = float(item.get("drinks") or 0)
            if drinks <= 0:
                continue
            cal = int(round(float(item.get("calories") or 0)))
            by_day[day]["drinks"] = round(by_day[day]["drinks"] + drinks, 2)
            by_day[day]["calories"] += cal
            by_day[day]["items"].append(
                {
                    "food": item.get("food", ""),
                    "ml": int(item["amount"]) if item.get("amount") else 0,
                    "cal": cal,
                    "drinks": drinks,
                }
            )

    result = {day: by_day[day] for day in sorted(by_day)}

    OUT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"   ✅ alcohol_daily.json обновлён: {len(result)} дней с алкоголем")


if __name__ == "__main__":
    main()
