#!/usr/bin/env python3
"""Единая синхронизация здоровья одного/всех пользователей KB → сервер.

Две идемпотентные стадии:
  1. KB → bind-mount kb_<tid>.json   (для агентских /kb_value, /list_kb_keys)
  2. KB → Postgres blood_tests сырьё (для /recent_biomarkers, /phenoage, дашборда)

Дашборд читает биомаркеры из Postgres, поэтому отдельная стадия
biomarkers_<id>.json больше не нужна (см. generate_biomarkers_json --legacy).

Usage:
    python3 scripts/sync_user_health.py --user 895655 [--apply]
    python3 scripts/sync_user_health.py --all [--apply]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "import"))

from config.users import KB_USERS
import sync_family_kb as sfk  # stage 1 (upload kb_<id>.json)
import kb_to_blood_tests as k2bt  # stage 2 (KB → Postgres)


def sync_user(tid: int, folder: str, apply: bool) -> dict:
    """Синхронизирует одного пользователя. Возвращает summary dict."""
    local = sfk.FAMILY_HEALTH / folder / "knowledge_base.json"
    result = {"tid": tid, "folder": folder, "stage1": "skip", "stage2": "skip"}
    if not local.exists():
        result["error"] = "no local KB"
        return result
    if not apply:
        result["stage1"] = result["stage2"] = "dry-run"
        return result

    # Stage 1: KB → bind-mount kb_<tid>.json
    result["stage1"] = "ok" if sfk.upload(local, tid) else "fail"

    # Stage 2: KB → Postgres blood_tests
    kb = k2bt._load_kb(folder)
    rows = list(k2bt._extract_rows(kb, tid))
    ins, upd = k2bt._psql_copy_via_python(rows)
    result["stage2"] = f"{ins} new, {upd} upd"
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--user", type=int)
    g.add_argument("--all", action="store_true")
    ap.add_argument("--apply", action="store_true", help="Без флага — dry-run")
    args = ap.parse_args(argv)

    users = KB_USERS if args.all else {args.user: KB_USERS[args.user]}
    for tid, folder in users.items():
        r = sync_user(tid, folder, args.apply)
        print(
            f"  {tid} {folder}: stage1={r['stage1']} stage2={r['stage2']}"
            + (f" ⚠ {r['error']}" if r.get("error") else "")
        )
    if not args.apply:
        print("\nDry-run. Повтори с --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
