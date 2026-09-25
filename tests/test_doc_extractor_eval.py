"""Оценка одного ответа экстрактора в eval-скрипте документов (#558)."""

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "doc_extractor_eval", Path(__file__).resolve().parents[1] / "scripts" / "eval" / "doc_extractor_eval.py"
)
ev = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ev)


def test_print_date_detected_and_date_wrong():
    case = {"date": "2026-01-10", "print_date": "2026-01-20", "kind": "lab_panel"}
    s = ev.score_case(case, {"date": "2026-01-20", "values": {"Hb": 130}})
    assert s["date_ok"] is False
    assert s["print_date"] is True


def test_kind_not_applicable_until_extractor_returns_it():
    s = ev.score_case({"date": None, "kind": "imaging"}, {"date": None, "values": {}})
    assert s["kind_ok"] is None
    assert s["date_ok"] is True


def test_smear_with_numbers_and_z_code_flagged():
    case = {"date": "2026-01-10", "kind": "smear_pcr"}
    pred = {
        "date": "2026-01-10",
        "doc_kind": "smear_pcr",
        "values": {"leukocytes": 50000},
        "conditions": ["Гинекологическое обследование (Z01.4)"],
    }
    s = ev.score_case(case, pred)
    assert s["smear_values"] is True
    assert s["z_leak"] is True
    assert s["kind_ok"] is True


def test_non_lab_document_writing_blood_row_is_flagged():
    case = {"date": "2026-01-10", "kind": "smear_pcr"}
    s = ev.score_case(case, {"date": "2026-01-10", "values": {"WBC": 1.2}})
    assert s["non_lab_row"] is True


def test_expect_keys_b12_and_crp():
    case = {"date": "2026-01-10", "kind": "lab_panel", "expect_keys": {"holotranscobalamin": 138.3, "hs_CRP_mg_l": 0.7}}
    bad = ev.score_case(case, {"date": "2026-01-10", "values": {"vitamin_B12": 138.3, "hs_CRP": 0.07}})
    good = ev.score_case(case, {"date": "2026-01-10", "values": {"holotranscobalamin": 138.3, "hs_CRP": 0.7}})
    assert (bad["b12_ok"], bad["crp_ok"]) == (False, False)
    assert (good["b12_ok"], good["crp_ok"]) == (True, True)


def test_expected_real_diagnoses_must_survive():
    case = {"date": "2026-01-10", "kind": "doctor_note", "expect_conditions": ["L70.0"]}
    assert ev.score_case(case, {"conditions": ["Угри обыкновенные (L70.0)"]})["conditions_ok"] is True
    assert ev.score_case(case, {"conditions": []})["conditions_ok"] is False


def test_summarize_ratio_and_markdown():
    rows = [
        {"score": {"date_ok": True}, "latency": 1.0, "cost": 0.01},
        {"score": {"date_ok": False}, "latency": 3.0, "cost": 0.03},
    ]
    summary = ev.summarize("m", rows)
    assert summary["дата верна"] == "1/2"
    assert summary["тип верен"] == "n/a"
    assert summary["p50, с"] == "2.0"
    assert "| m |" in ev.to_markdown([summary])


def test_score_duplicates_counts_caught_and_false():
    cbc = {"Hb": 119, "WBC": 4.6, "RBC": 4.21}
    cases = [
        {"file": "a.jpg", "dup_group": "A"},
        {"file": "b.jpg", "dup_group": "A"},
        {"file": "c.jpg", "dup_group": None},
    ]
    preds = [
        {"date": "2026-09-13", "values": cbc},
        {"date": "2026-09-13", "values": dict(cbc)},
        {"date": "2026-09-13", "values": dict(cbc)},
    ]
    assert ev.score_duplicates(cases, preds) == {"expected": 1, "caught": 1, "false": 1}
