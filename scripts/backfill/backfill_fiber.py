#!/usr/bin/env python3
"""
Backfill клетчатки (fiber) для исторических записей nutrition_log.

Берёт все записи где totals.fiber IS NULL или 0,
отправляет список продуктов в GPT-4o-mini,
получает оценку клетчатки на продукт,
обновляет items и totals в БД.

Стоимость: ~$0.02 (GPT-4o-mini, ~87 запросов)
"""

import os
import sys
import json
import time
import subprocess
import psycopg2
from openai import OpenAI
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv

load_dotenv(BASE_DIR / ".env")

POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "***REMOVED-SECRET***")
SERVER = "root@116.203.213.137"
SSH_OPTS = ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10"]
LOCAL_PORT = 15432
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
USER_ID = 895655

client = OpenAI(api_key=OPENAI_KEY)


def run_sql(query: str) -> list:
    """Выполняет SQL через SSH + psql внутри контейнера."""
    # Убираем переносы строк — psql через -c не любит многострочный SQL
    query_oneline = " ".join(query.split())
    cmd = [
        "ssh",
        *SSH_OPTS,
        SERVER,
        f"docker exec healthvault_postgres psql -U healthvault -d healthvault -t -A -F'|' -c \"{query_oneline}\"",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, shell=False)
    if result.returncode != 0:
        raise Exception(f"SQL error: {result.stderr}")
    lines = [l for l in result.stdout.strip().split("\n") if l]
    return lines


def run_update(log_id: int, items_json: str, totals_json: str):
    """Обновляет одну запись через psql heredoc."""
    # Экранируем одинарные кавычки для SQL
    items_safe = items_json.replace("'", "''")
    totals_safe = totals_json.replace("'", "''")
    sql = f"UPDATE nutrition_log SET items='{items_safe}'::jsonb, totals='{totals_safe}'::jsonb WHERE id={log_id};"
    cmd = [
        "ssh",
        *SSH_OPTS,
        SERVER,
        f"docker exec healthvault_postgres psql -U healthvault -d healthvault -c {json.dumps(sql)}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"Update error: {result.stderr}")


def estimate_fiber_gpt(items: list) -> dict:
    """
    Отправляет список продуктов в GPT-4o-mini.
    Возвращает {item_name: fiber_g} для каждого продукта.
    """
    if not items:
        return {}

    lines = "\n".join(
        f"- {it.get('name') or it.get('food', 'unknown')}: {it.get('weight') or it.get('amount') or 100}г"
        for it in items
    )
    prompt = (
        "Для каждого продукта посчитай, сколько граммов ПИЩЕВЫХ ВОЛОКОН (клетчатки, dietary fiber) "
        "содержится в указанной порции.\n\n"
        "Ориентир содержания клетчатки на 100г продукта:\n"
        "- Овощи (огурец, помидор, капуста, морковь): 1–3г/100г\n"
        "- Фрукты (яблоко, груша, банан): 1.5–3г/100г\n"
        "- Зелень (укроп, петрушка, шпинат): 2–4г/100г\n"
        "- Крупы варёные (гречка, рис, овсянка): 1–3г/100г\n"
        "- Бобовые: 5–15г/100г\n"
        "- Хлеб: 2–8г/100г\n"
        "- Мясо, рыба, яйца, молочка: 0г\n"
        "- Масла, алкоголь: 0г\n\n"
        "ВАЖНО: клетчатка в порции << веса порции. Пример: огурец 150г → 1.5г клетчатки (НЕ 150г!).\n\n"
        'Верни ТОЛЬКО JSON: {"название продукта": граммы_клетчатки}\n\n'
        f"{lines}"
    )

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=300,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content
    return json.loads(raw)


def run():
    # Берём записи где fiber не заполнена
    lines = run_sql(f"""
        SELECT id, items::text, totals::text
        FROM nutrition_log
        WHERE user_id = {USER_ID}
          AND (totals->>'fiber' IS NULL OR (totals->>'fiber')::float = 0)
        ORDER BY date, id
    """)
    print(f"Найдено {len(lines)} записей без клетчатки")

    updated = 0
    errors = 0

    for i, line in enumerate(lines):
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        row_id = int(parts[0])
        try:
            items = json.loads(parts[1])
            totals = json.loads(parts[2]) if parts[2] else {}
        except Exception:
            continue

        if not items:
            continue

        try:
            fiber_map = estimate_fiber_gpt(items)

            new_items = []
            total_fiber = 0.0
            for item in items:
                name = item.get("name") or item.get("food", "")
                fiber_val = fiber_map.get(name)
                if fiber_val is None:
                    for k, v in fiber_map.items():
                        if k.lower() in name.lower() or name.lower() in k.lower():
                            fiber_val = v
                            break
                fiber_val = float(fiber_val) if fiber_val is not None else 0.0
                # Sanity check: fiber не может быть больше 15% от веса продукта
                amount = item.get("weight") or item.get("amount") or 100
                max_fiber = float(amount) * 0.15
                if fiber_val > max_fiber:
                    fiber_val = round(max_fiber * 0.3, 1)  # консервативная оценка
                item["fiber"] = round(fiber_val, 1)
                total_fiber += fiber_val
                new_items.append(item)

            new_totals = dict(totals)
            new_totals["fiber"] = round(total_fiber, 1)

            run_update(row_id, json.dumps(new_items, ensure_ascii=False), json.dumps(new_totals, ensure_ascii=False))
            updated += 1

            if updated % 20 == 0:
                print(f"  {updated}/{len(lines)}...")
            time.sleep(0.05)

        except Exception as e:
            print(f"  Ошибка для id={row_id}: {e}")
            errors += 1

    print(f"\n✅ Обновлено: {updated}, ошибок: {errors}")


if __name__ == "__main__":
    run()
