#!/usr/bin/env python3
"""Синхронизация KB FamilyHealth/<имя>/knowledge_base.json → server kb_<telegram_id>.json.

Запуск ВРУЧНУЮ по запросу (не в cron) — данные меняются редко, автомат не нужен.

Использование:
    python3 scripts/sync_family_kb.py             # все известные пользователи, по умолчанию dry-run
    python3 scripts/sync_family_kb.py --apply     # реально загрузить на сервер
    python3 scripts/sync_family_kb.py --user 895655 --apply  # только один

Логика:
- Маппинг telegram_id → имя папки в FamilyHealth (см. USERS ниже)
- Сравнивает md5 локального файла с тем что на сервере
- Если разные → backup сервер-версии в *.backup_YYYYMMDD, перезаписывает kb_<id>.json
- НЕ делает merge — local рассматривается как source of truth.
  Если на сервере есть данные которых нет локально (как было до 22.05) —
  предварительно прогнать через scripts/util/merge_kb.py (TBD) и положить результат
  в FamilyHealth/<name>/knowledge_base.json.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FAMILY_HEALTH = Path.home() / "Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/FamilyHealth"
SERVER = "root@116.203.213.137"
SERVER_KB_DIR = "/opt/healthvault/data/kb"

# telegram_id → имя папки в FamilyHealth
USERS = {
    895655: "Александр Лысковский — Здоровье",
    33831673: "Павел Храпкин — Здоровье",
    830908046: "Игорь Лысковский — Здоровье",
    836757955: "Андрей Походня — Здоровье",
    1137554647: "Олег Лысковский — Здоровье",
    5162726004: "Валерия Лысковская — Здоровье",
    # Ника, Катя — добавить когда есть knowledge_base.json
}


def md5(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.md5(path.read_bytes()).hexdigest()


SSH_OPTS = ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10"]


def get_server_md5(telegram_id: int, _sshpass: str = "") -> str:
    """Удалённо считаем md5 файла на сервере (прямой ssh по ключу)."""
    result = subprocess.run(
        ["ssh", *SSH_OPTS, SERVER, f"md5sum {SERVER_KB_DIR}/kb_{telegram_id}.json 2>/dev/null | awk '{{print $1}}'"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def upload(local: Path, telegram_id: int, _sshpass: str = "") -> bool:
    """SCP файл на сервер с backup существующей версии (прямой ssh по ключу)."""
    remote = f"{SERVER}:{SERVER_KB_DIR}/kb_{telegram_id}.json"

    # Backup
    subprocess.run(
        [
            "ssh",
            *SSH_OPTS,
            SERVER,
            f"[ -f {SERVER_KB_DIR}/kb_{telegram_id}.json ] && "
            f"cp {SERVER_KB_DIR}/kb_{telegram_id}.json "
            f"{SERVER_KB_DIR}/kb_{telegram_id}.json.backup_$(date +%Y%m%d) || true",
        ],
        capture_output=True,
    )

    # Upload
    r = subprocess.run(
        ["scp", *SSH_OPTS, str(local), remote],
        capture_output=True,
        text=True,
    )
    return r.returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Реально загружать (без флага — dry-run)")
    ap.add_argument("--user", type=int, help="Один пользователь по telegram_id")
    args = ap.parse_args()

    users = {args.user: USERS[args.user]} if args.user else USERS

    needs_upload = []
    for tid, folder in users.items():
        local = FAMILY_HEALTH / folder / "knowledge_base.json"
        if not local.exists():
            print(f"  ⊘ {tid} {folder}: knowledge_base.json не найден локально")
            continue
        local_md5 = md5(local)
        server_md5 = get_server_md5(tid)

        if local_md5 == server_md5:
            print(f"  ✓ {tid} {folder}: совпадает ({local_md5[:8]}…)")
        elif not server_md5:
            print(f"  ✚ {tid} {folder}: на сервере нет, будет загружен ({local.stat().st_size // 1024} KB)")
            needs_upload.append((tid, folder, local))
        else:
            print(f"  ⚠ {tid} {folder}: РАЗНЫЕ ({local_md5[:8]} vs {server_md5[:8]})")
            needs_upload.append((tid, folder, local))

    if not needs_upload:
        print("\nВсё синхронизировано. Менять нечего.")
        return

    if not args.apply:
        print("\nЭто dry-run. Чтобы реально загрузить — повтори с --apply.")
        print(f"Будет загружено: {len(needs_upload)} файла(ов).")
        return

    print(f"\nЗагружаю {len(needs_upload)} файлов…")
    for tid, folder, local in needs_upload:
        ok = upload(local, tid)
        status = "✅" if ok else "❌"
        print(f"  {status} kb_{tid}.json ← {folder}")

    print("\nГотово. На сервере backup'ы старых версий в *.backup_YYYYMMDD.")
    print("Перезапусти контейнер если он не подхватит сразу (bind-mount должен работать live):")
    print("  ssh root@116.203.213.137 'docker restart healthvault_bot'")


if __name__ == "__main__":
    main()
