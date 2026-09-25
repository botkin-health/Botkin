#!/usr/bin/env python3
"""Сухой прогон: переприменить нормализацию разбора к сохранённым документам /doc (#561).

Берёт `documents[].extracted` из `data/kb/kb_<uid>.json`, прогоняет через
`core.health.doc_normalize.normalize_extracted` и показывает, что изменилось бы.
Модель не вызывается. Ничего не пишет: переписанный `extracted` разошёлся бы с
производными данными (строки `blood_tests`, диагнозы в медпрофиле) — запись вместе
с их синхронизацией вынесена в отдельную задачу.

Документы, разобранные после #558/#559, уже прошли те же правила — у них разница
должна быть нулевой. Ненулевая разница у свежего документа — признак того, что
правила изменились или стали неидемпотентными.

Гонять с прод-сервера:

    docker exec healthvault_bot python scripts/renormalize_documents.py

Отчёт с самими значениями (личные данные) — в data/eval/doc/renormalize_<ts>.jsonl
(gitignored); в stdout — только счётчики и имена изменившихся полей.
"""

from __future__ import annotations

import argparse
import copy
import glob
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATA = Path(os.environ.get("BOTKIN_DATA_DIR", "/app/data"))


def renormalize(extracted: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """(нормализованная копия, изменившиеся поля верхнего уровня). Вход не меняется."""
    from core.health.doc_normalize import normalize_extracted

    new = normalize_extracted(copy.deepcopy(extracted))
    changed = sorted(k for k in set(extracted) | set(new) if extracted.get(k) != new.get(k))
    return new, changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--since", help="только документы, добавленные с этой даты (ГГГГ-ММ-ДД)")
    args = parser.parse_args()

    out = DATA / "eval" / "doc" / f"renormalize_{datetime.now():%Y%m%d_%H%M%S}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    total, changed_docs = 0, 0
    fields: Counter[str] = Counter()
    with out.open("w", encoding="utf-8") as f:
        for kb_path in sorted(glob.glob(str(DATA / "kb" / "kb_*.json"))):
            uid = Path(kb_path).stem[3:]
            docs = json.loads(Path(kb_path).read_text(encoding="utf-8")).get("documents") or []
            for i, entry in enumerate(docs):
                # Пустой extracted — документ не разбирался (архив, нечитаемый); экстрактор
                # пустой ответ тоже не нормализует.
                if (
                    not isinstance(entry, dict)
                    or not isinstance(entry.get("extracted"), dict)
                    or not entry["extracted"]
                ):
                    continue
                if args.since and str(entry.get("added_at") or "") < args.since:
                    continue
                total += 1
                new, changed = renormalize(entry["extracted"])
                if not changed:
                    continue
                changed_docs += 1
                fields.update(changed)
                row = {
                    "uid": uid,
                    "idx": i,
                    "added_at": entry.get("added_at"),
                    "changed": changed,
                    "old": {k: entry["extracted"].get(k) for k in changed},
                    "new": {k: new.get(k) for k in changed},
                }
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                print(uid, i, entry.get("added_at"), changed, flush=True)
    print(f"Документов: {total}, изменились бы: {changed_docs}")
    for field, n in fields.most_common():
        print(f"  {field}: {n}")
    print("Отчёт:", out)


if __name__ == "__main__":
    main()
