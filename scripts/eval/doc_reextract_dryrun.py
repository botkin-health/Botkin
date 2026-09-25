#!/usr/bin/env python3
"""Сухой прогон: переразбор уже сохранённых документов /doc новым экстрактором (#558).

Ничего не пишет ни в KB, ни в blood_tests — только сравнивает сохранённый `extracted`
с новым разбором и складывает отчёт в data/eval/doc/reextract_<ts>.jsonl (личные
данные — gitignored). По отчёту решаем, что и у кого исправлять.
"""

from __future__ import annotations

import asyncio
import glob
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

DATA = Path(os.environ.get("BOTKIN_DATA_DIR", "/app/data"))


def _load(path: Path) -> tuple[bytes, str]:
    ext = path.suffix.lower()
    if ext == ".pdf":
        import fitz

        doc = fitz.open(path)
        text = "\n".join(page.get_text() for page in doc).strip()
        if text:
            return text.encode(), "text/plain"
        return doc[0].get_pixmap(dpi=150).tobytes("jpeg"), "image/jpeg"
    return path.read_bytes(), "image/png" if ext == ".png" else "image/jpeg"


def _diff(old: dict, new: dict) -> dict:
    ov, nv = old.get("values") or {}, new.get("values") or {}
    changed = {k: (ov.get(k), nv.get(k)) for k in set(ov) | set(nv) if ov.get(k) != nv.get(k)}
    return {
        "date": (old.get("date"), new.get("date")) if old.get("date") != new.get("date") else None,
        "values_changed": changed,
        "conditions": (old.get("conditions"), new.get("conditions"))
        if (old.get("conditions") or []) != (new.get("conditions") or [])
        else None,
    }


async def main() -> None:
    from core.health.doc_extractor import extract_medical_data

    out = DATA / "eval" / "doc" / f"reextract_{datetime.now():%Y%m%d_%H%M%S}.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for kb_path in sorted(glob.glob(str(DATA / "kb" / "kb_*.json"))):
            uid = Path(kb_path).stem[3:]
            docs = json.loads(Path(kb_path).read_text(encoding="utf-8")).get("documents") or []
            for i, entry in enumerate(docs):
                if not isinstance(entry, dict) or not entry.get("file"):
                    continue
                path = DATA / "uploads" / uid / entry["file"]
                if not path.exists():
                    continue
                content, mime = _load(path)
                new = await extract_medical_data(content, mime)
                old = entry.get("extracted") or {}
                row = {
                    "uid": uid,
                    "idx": i,
                    "file": entry["file"],
                    "added_at": entry.get("added_at"),
                    "user_confirmed": entry.get("user_confirmed"),
                    "old": old,
                    "new": new,
                    "diff": _diff(old, new),
                }
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                f.flush()
                print(
                    uid,
                    i,
                    entry["file"],
                    "date",
                    row["diff"]["date"],
                    "Δvalues",
                    len(row["diff"]["values_changed"]),
                    "kind",
                    new.get("doc_kind"),
                    flush=True,
                )
    print("Результаты:", out)


if __name__ == "__main__":
    asyncio.run(main())
