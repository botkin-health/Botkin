"""Сухой прогон переприменения нормализации к сохранённым документам (#561)."""

import importlib.util
import json
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "renormalize_documents", Path(__file__).resolve().parents[1] / "scripts" / "renormalize_documents.py"
)
rn = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rn)


def test_already_normalized_document_has_no_diff():
    stored = {
        "date": "2026-09-13",
        "doc_kind": "lab_panel",
        "summary": None,
        "values": {"Hb": 119},
        "allergies": [],
        "conditions": ["Угри (L70.0)"],
    }
    new, changed = rn.renormalize(stored)
    assert changed == [] and new == stored


def test_legacy_document_diff_and_input_untouched():
    stored = {"date": "2026-01-10", "values": {}, "conditions": ["Скрининг (Z12.4)", "Угри (L70.0)"]}
    snapshot = json.loads(json.dumps(stored))
    new, changed = rn.renormalize(stored)
    assert changed == ["_dropped_conditions", "allergies", "conditions"]
    assert new["conditions"] == ["Угри (L70.0)"]
    assert stored == snapshot


def test_main_reports_without_writing_kb(tmp_path, monkeypatch, capsys):
    kb = tmp_path / "kb" / "kb_1.json"
    kb.parent.mkdir()
    docs = {
        "documents": [
            {
                "added_at": "2026-09-25",
                "extracted": {"date": "2026-09-13", "values": {}, "allergies": [], "conditions": []},
            },
            {"added_at": "2026-01-10", "extracted": {"doc_kind": "smear_pcr", "values": {"WBC": 1.2}}},
            {"added_at": "2026-01-11", "file": "no-extracted.jpg"},
            {"added_at": "2026-09-25", "file": "archived.jpg", "auto_archived": True, "extracted": {}},
        ]
    }
    kb.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
    before = kb.read_text(encoding="utf-8")
    monkeypatch.setattr(rn, "DATA", tmp_path)
    monkeypatch.setattr(sys, "argv", ["renormalize_documents.py"])

    rn.main()

    assert kb.read_text(encoding="utf-8") == before
    out = capsys.readouterr().out
    assert "Документов: 2, изменились бы: 1" in out
    (report,) = (tmp_path / "eval" / "doc").glob("renormalize_*.jsonl")
    (row,) = [json.loads(line) for line in report.read_text(encoding="utf-8").splitlines()]
    assert row["idx"] == 1 and row["new"]["values"] == {}

    monkeypatch.setattr(sys, "argv", ["renormalize_documents.py", "--since", "2026-09-01"])
    rn.main()
    assert "Документов: 1, изменились бы: 0" in capsys.readouterr().out
