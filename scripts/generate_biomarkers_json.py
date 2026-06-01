#!/usr/bin/env python3
"""
Генерирует telegram-bot/biomarkers_895655.json из knowledge_base.json Александра.

Запускать локально после добавления новых анализов в knowledge_base.json,
затем деплоить: scripts/deploy_biomarkers.sh

Usage:
    python3 scripts/generate_biomarkers_json.py
    python3 scripts/generate_biomarkers_json.py --deploy   # + автодеплой на сервер
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

KB_PATH = Path.home() / (
    "Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/FamilyHealth/Александр Лысковский — Здоровье/knowledge_base.json"
)
OUT_PATH = Path(__file__).resolve().parent.parent / "telegram-bot" / "biomarkers_895655.json"

SERVER = "root@116.203.213.137"
SSH_OPTS = ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10"]


def build_biomarkers(kb: dict) -> dict:
    """Тонкая обёртка над core.health.biomarkers.aggregate_biomarkers.
    Сохранена для обратной совместимости (legacy biomarkers_<id>.json)."""
    import sys
    from pathlib import Path as _P

    sys.path.insert(0, str(_P(__file__).resolve().parent.parent))
    from core.health.biomarkers import aggregate_biomarkers

    rows = []
    for section in ("blood_tests", "hormones", "vitamins"):
        for e in kb.get(section, []):
            if e.get("date"):
                rows.append({"date": e["date"], "values": e.get("values") or {}})
    return aggregate_biomarkers(rows)


def deploy(path: Path) -> None:
    remote_tmp = "/tmp/biomarkers_895655.json"
    print(f"📤 Uploading to {SERVER}...")
    subprocess.run(
        ["scp", *SSH_OPTS, str(path), f"{SERVER}:{remote_tmp}"],
        check=True,
    )
    print("🐳 Copying into Docker container...")
    subprocess.run(
        [
            "ssh",
            *SSH_OPTS,
            SERVER,
            f"docker cp {remote_tmp} healthvault_bot:/app/biomarkers_895655.json && "
            f"docker cp {remote_tmp} healthvault_bot:/app/telegram-bot/biomarkers_895655.json && "
            f"echo 'Deployed OK'",
        ],
        check=True,
    )


def warn_empty_values(kb: dict) -> None:
    """Выводит предупреждение для записей с пустым или отсутствующим полем values."""
    sections = ["blood_tests", "urine_tests", "hormones", "vitamins"]
    found = 0
    for section in sections:
        for entry in kb.get(section, []):
            vals = entry.get("values") or entry.get("results")
            if not vals:
                date = entry.get("date", "?")
                lab = entry.get("laboratory", entry.get("lab", "?"))
                print(f"⚠️  Пустые values: {section} {date} {lab}")
                found += 1
    if found:
        print(f"   Итого {found} записей с пустыми values — они не попадут в biomarkers JSON.")
        print("   Добавь данные в knowledge_base.json или оставь как есть (не влияет на деплой).")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deploy", action="store_true", help="Deploy to server after generating")
    args = parser.parse_args()

    print(f"📖 Reading {KB_PATH}")
    kb = json.loads(KB_PATH.read_text())

    warn_empty_values(kb)

    bio = build_biomarkers(kb)
    print(f"✅ Built {len(bio)} biomarkers")

    if os.getenv("BOTKIN_LEGACY_BIOMARKERS_JSON") == "1":
        OUT_PATH.write_text(json.dumps(bio, indent=2, ensure_ascii=False) + "\n")
        print(f"💾 Saved to {OUT_PATH} (legacy mode)")
    else:
        print(
            "ℹ️  biomarkers_<id>.json больше не нужен дашборду (читает Postgres). "
            "Для legacy-файла запусти с BOTKIN_LEGACY_BIOMARKERS_JSON=1."
        )

    if args.deploy:
        deploy(OUT_PATH)
        # ── 3-stage pipeline после --deploy ──
        # Все три источника читают разное и должны быть синхронизированы:
        #   1) biomarkers_<id>.json (flat, для дашборда) — ⤴ уже сделано через deploy()
        #   2) PostgreSQL blood_tests (для агента → /recent_biomarkers) — через kb_to_blood_tests.py
        #   3) /app/data/kb/kb_<id>.json (для агента → /kb_value, /list_kb_keys) — через sync_family_kb.py
        # Прецедент: 24.05.2026 — забыли (2) и (3), агент утверждал «последний
        # анализ 19 марта» хотя дашборд уже знал майскую панель. Чтобы не
        # повторялось — теперь автомат для всех трёх. Идемпотентно.
        scripts_dir = Path(__file__).resolve().parent
        print()
        print("🗄️  Stage 2/3: KB → Postgres blood_tests (agent /recent_biomarkers)...")
        try:
            subprocess.run(
                [
                    sys.executable,
                    str(scripts_dir / "import" / "kb_to_blood_tests.py"),
                    "--user-id",
                    "895655",
                    "--folder",
                    "Александр Лысковский — Здоровье",
                ],
                check=True,
            )
        except subprocess.CalledProcessError as e:
            print(
                f"   ⚠️ kb_to_blood_tests упал (код {e.returncode}) — "
                f"biomarkers JSON залит, но агент-БД отстаёт. "
                f"Запусти руками: python3 scripts/import/kb_to_blood_tests.py --user-id 895655 ..."
            )
        print()
        print("🗄️  Stage 3/3: KB → /app/data/kb/kb_*.json для ВСЕЙ семьи (agent /kb_value, /open_questions)...")
        # Без `--user` синкается каждый member семьи (USERS в sync_family_kb.py).
        # Раньше синкался только Александр — поэтому KB папы/Андрея/Олега могли
        # отставать неделями, и агент получал null на get_kb_value у них.
        # Прецедент 21.05.2026: бот не видел papa's blood_tests хотя в локальном
        # KB они были. Прецедент 25.05.2026: бот не упомянул open_questions
        # папы (K/Mg/ТТГ) — не видел свежий KB.
        try:
            subprocess.run(
                [
                    sys.executable,
                    str(scripts_dir / "sync_family_kb.py"),
                    "--apply",
                ],
                check=True,
            )
        except subprocess.CalledProcessError as e:
            print(
                f"   ⚠️ sync_family_kb упал (код {e.returncode}) — "
                f"kb_*.json на сервере отстаёт. "
                f"Запусти руками: python3 scripts/sync_family_kb.py --apply"
            )
        print()
        print("🚀 Done! Biomarkers updated on server (3/3 sources sync'd).")
    else:
        print("\nRun with --deploy to push to server, or run scripts/deploy_biomarkers.sh")


if __name__ == "__main__":
    main()
