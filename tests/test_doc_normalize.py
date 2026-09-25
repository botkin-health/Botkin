# tests/test_doc_normalize.py
"""Правила нормализации разбора документа (#561) — таблицами «вход → выход», без сети."""

import copy
from datetime import date

import pytest

from core.health import doc_normalize
from core.health.doc_normalize import KINDS, kind_of, normalize_extracted

TODAY = date(2026, 9, 26)


def _norm(payload: dict) -> dict:
    return normalize_extracted(copy.deepcopy(payload), today=TODAY)


# ── дата ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("payload", "date_out", "rejected"),
    [
        ({"date": "2026-09-24", "date_label": "Дата печати", "values": {"Hb": 119}}, None, "print_or_issue_date"),
        ({"date": "2028-09-13", "date_label": "Дата приема", "values": {}}, None, "future"),
        ({"date": "13.09.2026", "values": {}}, None, "not_iso"),
        ({"date": "2026-09-13", "date_label": "Дата взятия материала", "values": {"Hb": 119}}, "2026-09-13", None),
    ],
)
def test_date(payload, date_out, rejected):
    out = _norm(payload)
    assert out["date"] == date_out
    assert out.get("_date_rejected") == rejected
    assert out["values"] == payload["values"]
    assert out.get("date_label") == payload.get("date_label")


def test_date_of_tomorrow_utc_is_allowed_for_user_timezones():
    today = date(2026, 9, 25)
    ok, far = {"date": "2026-09-26"}, {"date": "2026-09-27"}
    doc_normalize.sanitize_date(ok, today=today)
    doc_normalize.sanitize_date(far, today=today)
    assert ok["date"] == "2026-09-26"
    assert far["date"] is None and far["_date_rejected"] == "future"


# ── аллергии и диагнозы ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("payload", "allergies", "conditions"),
    [
        (
            {"values": {}, "allergies": ["пыльца", "кошки"], "conditions": ["Бронхиальная астма (J45.0)"]},
            ["пыльца", "кошки"],
            ["Бронхиальная астма (J45.0)"],
        ),
        ({"values": {"Hb": 155}}, [], []),
        ({"values": {}, "allergies": "пыльца", "conditions": None}, [], []),
    ],
)
def test_qualitative_lists(payload, allergies, conditions):
    out = _norm(payload)
    assert out["allergies"] == allergies
    assert out["conditions"] == conditions


@pytest.mark.parametrize(
    ("conditions", "kept", "dropped"),
    [
        # Отсеиваются только Z00–Z13 (осмотры, обследования, скрининг); статусы Z14+ —
        # стент, трансплантат, диализ, беременность — важны для агента (ревью #560).
        (
            [
                "Гинекологическое обследование (общее) (рутинное) (Z01.4)",
                "Угри обыкновенные (L70.0)",
                "Наличие коронарного стента (Z95.5)",
                "Наблюдение за нормальной беременностью Z34",
                "Скрининг на злокачественные новообразования (Z12.4)",
            ],
            [
                "Угри обыкновенные (L70.0)",
                "Наличие коронарного стента (Z95.5)",
                "Наблюдение за нормальной беременностью Z34",
            ],
            2,
        ),
        (["Синдром Золлингера-Эллисона (E16.4)", "Zinc deficiency (E60)"], None, 0),
    ],
)
def test_z_codes(conditions, kept, dropped):
    out = _norm({"values": {}, "conditions": conditions})
    assert out["conditions"] == (kept if kept is not None else conditions)
    assert len(out.get("_dropped_conditions", [])) == dropped


# ── тип документа и резюме ───────────────────────────────────────────────────


def test_smear_values_are_dropped_and_summary_kept():
    out = _norm(
        {
            "date": "2026-09-08",
            "doc_kind": "smear_pcr",
            "doc_type": "Мазок и флороценоз",
            "summary": "Лейкоциты 1–2 в п/зр; Gardnerella не обнаружена.",
            "values": {"leukocytes": 50000, "WBC": 1.2},
        }
    )
    assert out["values"] == {}
    assert out["_dropped_values"] == {"leukocytes": 50000, "WBC": 1.2}
    assert out["summary"].startswith("Лейкоциты")
    assert out["doc_type"] == "Мазок и флороценоз"


@pytest.mark.parametrize(
    ("raw_kind", "kind_out"),
    [
        ("LAB_PANEL", "lab_panel"),
        ("Lab panel", "lab_panel"),
        # Незнакомый тип — не «other», иначе теряется строка blood_tests.
        ("questionnaire", None),
        ("lab_panel | imaging", None),
        # Нет типа — поле не добавляем (старые читатели работают как раньше).
        (None, None),
    ],
)
def test_doc_kind(raw_kind, kind_out):
    payload = {"date": "2026-09-13", "values": {"Hb": 119}}
    if raw_kind is not None:
        payload["doc_kind"] = raw_kind
    out = _norm(payload)
    assert out.get("doc_kind") == kind_out
    assert out["values"] == {"Hb": 119}


@pytest.mark.parametrize(
    ("kind", "summary", "values", "kept"),
    [
        # Модель пишет «в пределах нормы» и при значениях выше нормы — резюме анализов с
        # числами не храним вовсе (#558).
        ("lab_panel", "Определён ионизированный кальций. Показатель в пределах нормы.", {"RBC": 6.18}, False),
        (
            "lab_panel",
            "Представлены результаты общего анализа крови с лейкоцитарной формулой и СОЭ; "
            "все показатели находятся в пределах указанных референсных значений.",
            {"RBC": 6.18},
            False,
        ),
        ("lab_panel", "Все показатели в пределах референсных значений.", {"Hb": 119}, False),
        # Бланк анализа без чисел — резюме единственный носитель результата (ревью #562).
        ("lab_panel", "Антитела к ВГС — не обнаружены; HBsAg — не обнаружен.", {}, True),
        ("imaging", "Размеры матки в норме. Заключение: патологии не выявлено.", {}, True),
    ],
)
def test_summary(kind, summary, values, kept):
    out = _norm({"doc_kind": kind, "summary": summary, "values": values})
    assert out["summary"] == (summary if kept else None)
    assert out["values"] == values


# ── единицы ──────────────────────────────────────────────────────────────────


def test_crp_in_mg_dl_converted_to_mg_l():
    out = _norm({"values": {"hs_CRP": 0.07, "ferritin": 15.78}, "units": {"hs_CRP": "мг/дл", "ferritin": "нг/мл"}})
    assert out["values"]["hs_CRP"] == pytest.approx(0.7)
    assert out["units"]["hs_CRP"] == "мг/л"
    assert out["values"]["ferritin"] == 15.78
    assert out["_unit_conversions"] == ["hs_CRP: мг/дл → мг/л ×10"]


@pytest.mark.parametrize(
    ("key", "value", "unit", "expected", "converted"),
    [
        ("CRP", 3.0, "мг/л", 3.0, False),
        ("CRP", 0.3, "mg/dL", 3.0, True),
        ("hsCRP", 0.07, "мг/дл", 0.7, True),
    ],
)
def test_crp_units(key, value, unit, expected, converted):
    out = _norm({"values": {key: value}, "units": {key: unit}})
    assert out["values"][key] == pytest.approx(expected)
    assert ("_unit_conversions" in out) is converted


# ── справочник типов ─────────────────────────────────────────────────────────


def test_kind_properties():
    assert [k for k, v in KINDS.items() if not v.writes_blood_tests] == ["smear_pcr", "other"]
    assert [k for k, v in KINDS.items() if not v.keeps_values] == ["smear_pcr"]
    assert [k for k, v in KINDS.items() if not v.keeps_summary_with_values] == ["lab_panel"]
    assert [k for k, v in KINDS.items() if v.compares_analytes] == ["lab_panel"]


@pytest.mark.parametrize("extracted", [None, {}, {"doc_kind": None}, {"doc_kind": "questionnaire"}])
def test_document_without_kind_behaves_as_before_558(extracted):
    kind = kind_of(extracted)
    assert kind.writes_blood_tests and kind.keeps_values and kind.keeps_summary_with_values
    assert not kind.compares_analytes


# ── идемпотентность: условие переприменения к сохранённым документам ─────────

_IDEMPOTENCY_CASES = [
    {"date": "2026-09-24", "date_label": "Дата печати", "values": {"Hb": 119}},
    {"date": "13.09.2026", "values": {}},
    {"doc_kind": "smear_pcr", "summary": "Лейкоциты 1–2 в п/зр", "values": {"WBC": 1.2}},
    {"doc_kind": "lab_panel", "summary": "Всё в норме", "values": {"RBC": 6.18}},
    {"doc_kind": "Lab panel", "values": {"hs_CRP": 0.07}, "units": {"hs_CRP": "мг/дл"}},
    {"values": {}, "allergies": "пыльца", "conditions": ["Скрининг (Z12.4)", "Угри (L70.0)"]},
    {
        "doc_kind": "lab_panel",
        "values": {},
        "units": {"vitamin_D": "нмоль/л", "testosterone": "нг/мл"},
        "series": [
            {"date": "2026-07-14", "values": {"vitamin_D": 77.7}},
            {"date": "2025-12-12", "values": {"vitamin_D": 31.1}, "units": {"vitamin_D": "нг/мл"}},
            {"date": "2022-03-01", "values": {"testosterone": 5.2, "LDL": "—"}},
            {"date": "03.2023", "values": {"LDL": 2.1}},
        ],
    },
    {
        "doc_kind": "smear_pcr",
        "values": {},
        "series": [{"date": "2026-07-14", "values": {"x": 1}}, {"date": "2025-12-12", "values": {"x": 2}}],
    },
    {"date": "2026-07-14", "values": {"ALT": 29}, "series": [{"date": "2026-07-14", "values": {"AST": 22}}]},
]


@pytest.mark.parametrize("payload", _IDEMPOTENCY_CASES)
def test_normalization_is_idempotent(payload):
    once = _norm(payload)
    twice = normalize_extracted(copy.deepcopy(once), today=TODAY)
    assert twice == once
