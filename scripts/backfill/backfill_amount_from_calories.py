"""Backfill amount for nutrition_log items where amount is 0/NULL.

Context: until Apr 2026, telegram-bot/handlers/photo.py hardcoded weight_g=None
in handle_menu_photo, losing the weight extracted by GPT-vision. Plus GPT
sometimes returned weight_grams=0 for receipt screenshots. Result: 80+ items
got amount=0 in DB despite correct calories/macros.

Strategy: estimate amount from calories using per-category kcal/g density.
KBZHU are authoritative — we only fill the missing `amount` field so the
mini-app shows something instead of "0 г". Each edited item gets
`"amount_source": "estimated_from_calories"` so future audits know this is
derived, not measured.

Usage:
    # dry run (show what would change)
    python3 scripts/backfill/backfill_amount_from_calories.py --dry-run

    # apply
    python3 scripts/backfill/backfill_amount_from_calories.py --apply

Runs via SSH+docker against the production server.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Tuple

SERVER = "root@116.203.213.137"
SSHPASS_BIN = "/opt/homebrew/bin/sshpass"
SERVER_PASS_FILE = "scripts/util/diagnose_remote.sh"
USER_ID = 895655
START_DATE = "2026-01-06"


# ── kcal/g density by food category (rough but sane) ──────────────────────
# These are deliberate approximations. Goal: amount looks plausible, not exact.
# Higher = denser food (e.g. nuts, cheese). Lower = watery (drinks, soups).
DENSITY_RULES: list[tuple[list[str], float, str]] = [
    # (keywords, kcal/g, category)
    (["вино", "шампан", "просекко", "рислинг", "мерло", "каберне", "саперави", "портвейн"], 0.80, "wine"),
    (["виски", "водк", "джин", "текил", "ром ", "коньяк", "бренди"], 2.30, "spirits"),
    (["негрони", "мохито", "аперол", "мартини", "коктейль", "глинтвейн"], 1.00, "cocktail"),
    (["пиво", "сидр", "ликёр", "ликер"], 0.60, "beer"),
    (["хай-про", "hi-pro", "hi pro", "протеиновый напиток", "кисломолочн"], 0.55, "protein_drink"),
    (["кефир", "skyr", "скир", "йогурт", "творог мягк", "пудинг"], 1.00, "fermented_dairy"),
    (["творог"], 1.20, "curd"),
    (["сникерс", "шоколад", "мороженое", "пломбир", "кекс", "пирожное", "булочка", "десерт"], 2.80, "sweets"),
    (["bombbar", "бомбар", "батончик", "protein bar", "natural bar", "exponenta", "exponеnta"], 3.50, "protein_bar"),
    (["сушёное", "сушеное", "вяленые", "вяленое", "чипсы", "сухарик"], 3.50, "dry_snack"),
    (["оливки", "масло"], 4.00, "oil_olive"),
    (["орехи", "миндаль", "фундук", "кешью", "арахис", "грец"], 5.50, "nuts"),
    (["суп", "рассольник", "борщ", "щи", "крем-суп"], 0.60, "soup"),
    (["салат"], 1.00, "salad"),
    (["икра"], 2.50, "caviar"),
    (["ролл", "ролы", "суши", "сашими", "онигири"], 1.80, "sushi"),
    (["сэндвич", "гриль-чиз", "бургер", "шаурм"], 2.50, "sandwich"),
    (["паста", "лапша", "удон", "вок", "кускус", "ризотто"], 1.50, "pasta_rice"),
    (["картофел", "картошк", "пюре"], 1.00, "potato"),
    (["котлет", "медальон", "митболл", "вырезк"], 2.00, "meat_patties"),
    (
        [
            "окунь",
            "лосось",
            "тунец",
            "треск",
            "рыба",
            "скумбри",
            "килька",
            "креветк",
            "гребешк",
            "кальмар",
            "морепродукт",
        ],
        1.50,
        "fish_seafood",
    ),
    (["утин", "утка", "индейка", "курин", "курица", "говяд", "свин", "оленин", "ягнятин", "язык"], 2.00, "meat"),
]

DEFAULT_DENSITY = 1.50  # generic cooked dish
DEFAULT_CATEGORY = "default_cooked"


def estimate_amount_from_calories(food_name: str, calories: float) -> Tuple[float, str]:
    """Return (amount_g, category_used)."""
    if calories <= 0:
        return (0.0, "zero_cal")
    lname = (food_name or "").lower()
    for keywords, density, category in DENSITY_RULES:
        if any(kw in lname for kw in keywords):
            return (round(calories / density), category)
    return (round(calories / DEFAULT_DENSITY), DEFAULT_CATEGORY)


def get_server_password() -> str:
    import re

    with open(SERVER_PASS_FILE) as f:
        for line in f:
            m = re.match(r'PASS="([^"]+)"', line)
            if m:
                return m.group(1)
    raise RuntimeError("Could not find PASS= in " + SERVER_PASS_FILE)


def ssh_psql(password: str, sql: str, csv: bool = False) -> str:
    """Run SQL on server via stdin, return raw output."""
    import shlex

    full_sql = f"COPY ({sql}) TO STDOUT WITH CSV" if csv else sql
    # Pipe SQL via stdin to avoid shell-quoting hell
    remote_cmd = "docker exec -i healthvault_postgres psql -U healthvault -d healthvault -t -A"
    cmd = [
        SSHPASS_BIN,
        "-p",
        password,
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        SERVER,
        remote_cmd,
    ]
    result = subprocess.run(cmd, input=full_sql, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"psql failed: {result.stderr}")
    return result.stdout


def fetch_broken_rows(password: str) -> list[dict]:
    """Fetch nutrition_log rows where at least one item has amount=0/NULL and calories>0."""
    import csv as csv_mod
    import io

    sql = (
        f"SELECT id, date::text, items::text FROM nutrition_log "
        f"WHERE user_id={USER_ID} AND date >= '{START_DATE}' ORDER BY date, meal_time"
    )
    raw = ssh_psql(password, sql, csv=True)
    rows = []
    reader = csv_mod.reader(io.StringIO(raw))
    for parts in reader:
        if len(parts) != 3:
            continue
        log_id, date, items_json = parts
        try:
            items = json.loads(items_json)
        except json.JSONDecodeError:
            continue
        needs_fix = False
        for it in items:
            amt = it.get("amount")
            cal = it.get("calories", 0) or 0
            if (amt is None or float(amt or 0) == 0) and float(cal) > 0:
                needs_fix = True
                break
        if needs_fix:
            rows.append({"id": int(log_id), "date": date, "items": items})
    return rows


def build_updated_items(items: list[dict]) -> Tuple[list[dict], list[dict]]:
    """Return (new_items, change_log)."""
    new_items = []
    changes = []
    for it in items:
        amt = it.get("amount")
        cal = float(it.get("calories", 0) or 0)
        food = it.get("food") or ""
        if (amt is None or float(amt or 0) == 0) and cal > 0:
            est, category = estimate_amount_from_calories(food, cal)
            new_it = {**it, "amount": est, "amount_source": "estimated_from_calories", "amount_category": category}
            new_items.append(new_it)
            changes.append({"food": food, "calories": cal, "amount": est, "category": category})
        else:
            new_items.append(it)
    return new_items, changes


def update_row(password: str, log_id: int, new_items: list[dict]) -> None:
    items_json = json.dumps(new_items, ensure_ascii=False).replace("'", "''")
    sql = f"UPDATE nutrition_log SET items='{items_json}'::jsonb WHERE id={log_id}"
    ssh_psql(password, sql)


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Show changes without applying")
    group.add_argument("--apply", action="store_true", help="Apply changes to DB")
    args = parser.parse_args()

    password = get_server_password()
    print(f"🔍 Fetching broken rows (user_id={USER_ID}, date >= {START_DATE})...")
    rows = fetch_broken_rows(password)
    print(f"   Found {len(rows)} rows with zero/null amount items")

    total_items_changed = 0
    for row in rows:
        new_items, changes = build_updated_items(row["items"])
        if not changes:
            continue
        total_items_changed += len(changes)
        print(f"\n📅 {row['date']} (log_id={row['id']}):")
        for c in changes:
            print(f"   • {c['food'][:60]:<60} {c['calories']:>5.0f} ккал → {c['amount']:>4.0f}г  [{c['category']}]")
        if args.apply:
            update_row(password, row["id"], new_items)

    print(f"\n{'✅ Applied' if args.apply else '🔎 Dry run'}: {total_items_changed} items in {len(rows)} rows")
    if args.dry_run:
        print("   Run with --apply to persist changes")


if __name__ == "__main__":
    main()
