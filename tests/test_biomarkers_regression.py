# tests/test_biomarkers_regression.py
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "import"))

from core.health.biomarkers import aggregate_biomarkers

FAMILY = Path(os.path.expanduser("~/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/FamilyHealth"))
BIO_DIR = Path(__file__).resolve().parent.parent / "telegram-bot"

# telegram_id → папка FamilyHealth (см. config/users.py — здесь дублируем намеренно,
# чтобы тест не зависел от рантайм-конфига)
USERS = {
    895655: "Александр Лысковский — Здоровье",
    REDACTED_ID: "Дмитрий REDACTED — Здоровье",
}


def _kb_rows(folder: str):
    """Строки [{date, values}] из blood_tests+hormones+vitamins — как kb_to_blood_tests."""
    kb = json.loads((FAMILY / folder / "knowledge_base.json").read_text())
    rows = []
    for section in ("blood_tests", "hormones", "vitamins"):
        for e in kb.get(section, []):
            if e.get("date"):
                rows.append({"date": e["date"], "values": e.get("values") or {}})
    return rows


@pytest.mark.parametrize("tid,folder", list(USERS.items()))
def test_new_aggregate_superset_of_old_json(tid, folder):
    old_file = BIO_DIR / f"biomarkers_{tid}.json"
    kb_path = FAMILY / folder / "knowledge_base.json"
    if not old_file.exists() or not kb_path.exists():
        pytest.skip(f"no local biomarkers_{tid}.json or KB")

    old = json.loads(old_file.read_text())
    new = aggregate_biomarkers(_kb_rows(folder))

    missing = []
    for key, old_rec in old.items():
        if key == "_meta":
            continue
        if key not in new:
            missing.append(key)
            continue
        # value совпадает (старый формат: old_rec["value"])
        if abs(new[key]["value"] - old_rec["value"]) > 1e-6:
            missing.append(f"{key}:value {old_rec['value']}→{new[key]['value']}")
    assert not missing, f"потеряны/изменены маркеры для {tid}: {missing}"
