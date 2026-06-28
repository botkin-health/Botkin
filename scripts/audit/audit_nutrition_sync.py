#!/usr/bin/env python3
"""Аудит рассинхрона вес↔калории в nutrition_log.

Находит записи, где расчётная плотность калорий (ккал/100г) превышает
пороговое значение — вероятный признак того, что LLM оценил ккал за полную
порцию, а вес поставлен только для основного ингредиента.

Вывод: CSV со столбцами id, user_id, meal_date, dish_name, weight_g,
calories, kcal_per_100g.

Использование:
    DATABASE_URL=postgresql://... python3 scripts/audit/audit_nutrition_sync.py
    python3 scripts/audit/audit_nutrition_sync.py --threshold 400 --out report.csv
"""

import argparse
import csv
import json
import os
import sys

_DEFAULT_THRESHOLD = 400  # ккал/100г выше этого → подозрительно


def _iter_items(items_raw):
    """Разворачивает items из JSONB (список или строка)."""
    if not items_raw:
        return
    if isinstance(items_raw, str):
        try:
            items_raw = json.loads(items_raw)
        except json.JSONDecodeError:
            return
    if isinstance(items_raw, list):
        yield from items_raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--threshold",
        type=float,
        default=_DEFAULT_THRESHOLD,
        help="Порог ккал/100г для флага (по умолчанию %(default)s)",
    )
    parser.add_argument("--out", default="-", help="Путь к CSV-файлу (- для stdout)")
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL не задан", file=sys.stderr)
        sys.exit(1)

    try:
        import psycopg2
    except ImportError:
        print("ERROR: psycopg2 не установлен (pip install psycopg2-binary)", file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, user_id, meal_date, meal_name,
               totals->>'calories' AS calories,
               items
        FROM nutrition_log
        WHERE totals->>'calories' IS NOT NULL
          AND items IS NOT NULL
        ORDER BY meal_date DESC
        LIMIT 50000
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    flagged = []
    for row_id, user_id, meal_date, meal_name, cal_str, items_raw in rows:
        total_weight = 0.0
        for item in _iter_items(items_raw):
            w = item.get("weight") or item.get("amount") or 0
            try:
                total_weight += float(w)
            except (TypeError, ValueError):
                pass

        if total_weight <= 0:
            continue

        try:
            calories = float(cal_str)
        except (TypeError, ValueError):
            continue

        kcal_per_100g = calories / total_weight * 100
        if kcal_per_100g > args.threshold:
            flagged.append(
                {
                    "id": row_id,
                    "user_id": user_id,
                    "meal_date": meal_date,
                    "dish_name": meal_name or "",
                    "weight_g": round(total_weight, 1),
                    "calories": round(calories, 1),
                    "kcal_per_100g": round(kcal_per_100g, 1),
                }
            )

    fieldnames = ["id", "user_id", "meal_date", "dish_name", "weight_g", "calories", "kcal_per_100g"]
    out = open(args.out, "w", newline="", encoding="utf-8") if args.out != "-" else sys.stdout
    try:
        writer = csv.DictWriter(out, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(flagged)
    finally:
        if args.out != "-":
            out.close()

    print(f"Найдено {len(flagged)} записей с ккал/100г > {args.threshold}", file=sys.stderr)


if __name__ == "__main__":
    main()
