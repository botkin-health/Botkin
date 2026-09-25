"""Сводные документы с несколькими датами (#559).

Досье, собранное вручную, — это таблицы «дата × показатели» за 2015–2026 годы.
Раньше всем значениям ставилась одна дата (показатели разных лет в динамике одним
днём), после #558 дата честно пустая — и таблица не попадала в динамику вовсе.
Теперь экстрактор отдаёт `series` — запись на дату, и в blood_tests идёт строка на
каждую дату.
"""

import json
from contextlib import contextmanager
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from core.health import doc_extractor
from core.health.doc_duplicates import find_similar_document
from core.health.doc_to_blood_test import build_blood_test_row, build_blood_test_rows
from database.crud import get_all_blood_tests

STORED = "2026-08-10_a1ead4ae.pdf"
USER_ID = 4242


def _fake_response(payload: dict) -> dict:
    return {"content": [{"text": json.dumps(payload, ensure_ascii=False)}]}


async def _extract(payload: dict) -> dict:
    with patch.object(doc_extractor, "_call_anthropic", new=AsyncMock(return_value=_fake_response(payload))):
        return await doc_extractor.extract_medical_data(b"x", "image/jpeg")


LIPIDS = {
    "date": None,
    "doc_kind": "lab_panel",
    "doc_type": "Липидный профиль (динамика)",
    "summary": "Сводная таблица липидного профиля",
    "values": {},
    "units": {"cholesterol": "ммоль/л"},
    "series": [
        {"date": "2026-07-14", "laboratory": "лаборатория A", "values": {"cholesterol": 5.09, "LDL": 2.18}},
        {"date": "2016-04-02", "laboratory": None, "values": {"cholesterol": 4.62, "LDL": "—"}},
        {"date": "2025-12-12", "laboratory": "лаборатория B", "values": {"cholesterol": 6.01, "LDL": 4.39}},
    ],
}


# ── экстрактор: series ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_series_sorted_by_date_top_level_empty():
    out = await _extract(LIPIDS)
    assert [e["date"] for e in out["series"]] == ["2016-04-02", "2025-12-12", "2026-07-14"]
    assert out["date"] is None
    assert out["values"] == {}
    assert out["series"][2]["laboratory"] == "лаборатория A"


@pytest.mark.asyncio
async def test_series_dash_cell_dropped():
    out = await _extract(LIPIDS)
    assert out["series"][0]["values"] == {"cholesterol": 4.62}


@pytest.mark.asyncio
async def test_series_lab_panel_summary_dropped():
    """Резюме анализов с числами не храним и у таблицы (#562)."""
    out = await _extract(LIPIDS)
    assert out["summary"] is None


@pytest.mark.asyncio
async def test_series_month_only_date_rejected_not_guessed():
    payload = {
        **LIPIDS,
        "series": [
            {"date": "2023-03", "values": {"cholesterol": 5.68}},
            {"date": "2026-07-14", "values": {"cholesterol": 5.09}},
            {"date": "2025-12-12", "values": {"cholesterol": 6.01}},
        ],
    }
    out = await _extract(payload)
    assert [e["date"] for e in out["series"]] == ["2025-12-12", "2026-07-14"]
    assert out["_series_rejected"] == ["'2023-03': not_iso"]


def test_series_future_date_rejected():
    data = {"series": [{"date": "2030-01-01", "values": {"Hb": 1}}, {"date": "2026-01-01", "values": {"Hb": 2}}]}
    doc_extractor._normalize_series(data, today=date(2026, 9, 26))
    assert "series" not in data
    assert data["date"] == "2026-01-01"
    assert data["_series_rejected"] == ["'2030-01-01': future"]


@pytest.mark.asyncio
async def test_single_date_series_collapses_to_plain_document():
    """Таблица из одной даты — обычный бланк: читатели документа не должны знать о series."""
    payload = {
        "date": None,
        "laboratory": None,
        "doc_kind": "lab_panel",
        "values": {},
        "series": [{"date": "2026-07-14", "laboratory": "лаборатория A", "values": {"TSH": 1.2, "FT4": 14.1}}],
    }
    out = await _extract(payload)
    assert "series" not in out
    assert out["date"] == "2026-07-14"
    assert out["values"] == {"TSH": 1.2, "FT4": 14.1}
    assert out["laboratory"] == "лаборатория A"


def test_same_date_entries_merged_first_value_wins():
    data = {
        "series": [
            {"date": "2026-07-14", "values": {"ALT": 29}},
            {"date": "2026-07-14", "values": {"ALT": 30, "AST": 22}},
            {"date": "2025-12-12", "values": {"ALT": 21}},
        ]
    }
    doc_extractor._normalize_series(data)
    assert data["series"][1] == {"date": "2026-07-14", "laboratory": None, "values": {"ALT": 29, "AST": 22}}


def test_top_level_dated_values_join_series():
    data = {
        "date": "2026-07-14",
        "laboratory": "A",
        "values": {"ALT": 29},
        "series": [{"date": "2025-12-12", "values": {"ALT": 21}}],
    }
    doc_extractor._normalize_series(data)
    assert data["date"] is None and data["values"] == {}
    assert [(e["date"], e["values"]) for e in data["series"]] == [
        ("2025-12-12", {"ALT": 21}),
        ("2026-07-14", {"ALT": 29}),
    ]


def test_no_series_leaves_plain_document_untouched():
    data = {"date": "2026-07-14", "values": {"Hb": 150}}
    doc_extractor._normalize_series(data)
    assert data == {"date": "2026-07-14", "values": {"Hb": 150}}


@pytest.mark.asyncio
async def test_smear_series_dropped():
    payload = {
        "doc_kind": "smear_pcr",
        "values": {},
        "series": [{"date": "2026-01-01", "values": {"WBC": 2}}, {"date": "2026-02-01", "values": {"WBC": 3}}],
    }
    out = await _extract(payload)
    assert "series" not in out
    assert len(out["_dropped_series"]) == 2


@pytest.mark.asyncio
async def test_units_converted_for_every_date():
    """Единицы у таблицы общие: СРБ мг/дл пересчитывается в каждой дате, а не только в первой."""
    payload = {
        "doc_kind": "lab_panel",
        "values": {},
        "units": {"hs_CRP": "мг/дл"},
        "series": [
            {"date": "2026-01-01", "values": {"hs_CRP": 0.07}},
            {"date": "2026-02-01", "values": {"hs_CRP": 0.1}},
        ],
    }
    out = await _extract(payload)
    assert [e["values"]["hs_CRP"] for e in out["series"]] == [0.7, 1.0]
    assert out["units"]["hs_CRP"] == "мг/л"


# ── длинный документ: части ──────────────────────────────────────────────────


def test_chunk_pages_keeps_pages_whole():
    pages = ["a" * 5000, "b" * 5000, "c" * 2000, "d" * 9000]
    chunks = doc_extractor.chunk_pages(pages, limit=8000)
    assert chunks == ["a" * 5000, "b" * 5000 + "\n" + "c" * 2000, "d" * 9000]


def test_merge_parts_with_different_dates_gives_series():
    parts = [
        {
            "date": "2026-07-14",
            "laboratory": "A",
            "doc_kind": "lab_panel",
            "values": {"ALT": 29},
            "allergies": ["кошка"],
        },
        {
            "date": None,
            "doc_kind": "lab_panel",
            "series": [LIPIDS["series"][0], LIPIDS["series"][2]],
            "allergies": ["Кошка", "пыль"],
        },
        {},
    ]
    merged = doc_extractor.merge_extractions(parts)
    assert merged["series"] == [
        {"date": "2025-12-12", "laboratory": "лаборатория B", "values": {"cholesterol": 6.01, "LDL": 4.39}},
        {"date": "2026-07-14", "laboratory": "A", "values": {"ALT": 29, "cholesterol": 5.09, "LDL": 2.18}},
    ]
    assert merged["allergies"] == ["кошка", "пыль"]
    assert merged["_chunks"] == 2


def test_merge_continuation_page_attaches_to_only_date():
    """Страница-продолжение без даты у документа с одной датой — к этой дате (обычный многостраничный бланк)."""
    parts = [
        {"date": "2026-07-14", "laboratory": "A", "doc_kind": "lab_panel", "values": {"ALT": 29}},
        {"date": None, "doc_kind": "lab_panel", "values": {"AST": 22}},
    ]
    merged = doc_extractor.merge_extractions(parts)
    assert "series" not in merged
    assert merged["date"] == "2026-07-14"
    assert merged["values"] == {"AST": 22, "ALT": 29}


def test_merge_undated_values_stay_out_of_series_when_many_dates():
    parts = [
        {"date": "2026-07-14", "doc_kind": "lab_panel", "values": {"ALT": 29}},
        {"date": "2025-12-12", "doc_kind": "lab_panel", "values": {"ALT": 21}},
        {"date": None, "doc_kind": "lab_panel", "values": {"AST": 22}},
    ]
    merged = doc_extractor.merge_extractions(parts)
    assert len(merged["series"]) == 2
    assert merged["values"] == {"AST": 22}
    assert merged["date"] is None


@pytest.mark.asyncio
async def test_short_pdf_single_call():
    call = AsyncMock(return_value=_fake_response({"date": "2026-07-14", "values": {"Hb": 150}}))
    with patch.object(doc_extractor, "_call_anthropic", new=call):
        out = await doc_extractor.extract_medical_data_from_pages(["Общий анализ крови Hb 150"] * 3)
    assert call.await_count == 1
    assert out["date"] == "2026-07-14"


@pytest.mark.asyncio
async def test_long_pdf_split_and_merged():
    responses = [
        _fake_response({"date": "2026-07-14", "doc_kind": "lab_panel", "values": {"ALT": 29}}),
        _fake_response({"date": "2025-12-12", "doc_kind": "lab_panel", "values": {"ALT": 21}}),
    ]
    call = AsyncMock(side_effect=responses)
    pages = ["Печеночные пробы АЛТ " + "x" * 7000, "Печеночные пробы АЛТ " + "y" * 7000]
    with patch.object(doc_extractor, "_call_anthropic", new=call):
        out = await doc_extractor.extract_medical_data_from_pages(pages)
    assert call.await_count == 2
    assert sorted(e["date"] for e in out["series"]) == ["2025-12-12", "2026-07-14"]


@pytest.mark.asyncio
async def test_long_pdf_failed_part_is_counted():
    call = AsyncMock(
        side_effect=[
            _fake_response({"date": "2026-07-14", "doc_kind": "lab_panel", "values": {"ALT": 29}}),
            RuntimeError("timeout"),
        ]
    )
    pages = ["Печеночные пробы АЛТ " + "x" * 7000, "Печеночные пробы АЛТ " + "y" * 7000]
    with patch.object(doc_extractor, "_call_anthropic", new=call):
        out = await doc_extractor.extract_medical_data_from_pages(pages)
    assert out["date"] == "2026-07-14"
    assert out["_chunks_failed"] == 1


# ── строки blood_tests ───────────────────────────────────────────────────────


def _series_doc():
    return {
        "doc_kind": "lab_panel",
        "laboratory": "досье",
        "date": None,
        "values": {},
        "series": [
            {"date": "2016-04-02", "laboratory": None, "values": {"cholesterol": 4.62}},
            {"date": "2026-07-14", "laboratory": "лаборатория A", "values": {"cholesterol": 5.09, "LDL": 2.18}},
        ],
    }


def test_series_gives_row_per_date():
    res = build_blood_test_rows(_series_doc(), stored_name=STORED, user_id=1)
    assert res.reason == "ok"
    assert [r["test_date"] for r in res.rows] == ["2016-04-02", "2026-07-14"]
    assert res.rows[0]["test_type"] == "досье · a1ead4ae"
    assert res.rows[1]["test_type"] == "лаборатория A · a1ead4ae"
    assert res.rows[1]["values"] == {"cholesterol": 5.09, "LDL": 2.18}
    assert res.marker_count == 3


def test_plain_document_same_as_single_row():
    doc = {"date": "2026-04-13", "laboratory": "KDL", "values": {"Hb": 148}}
    single = build_blood_test_row(doc, stored_name=STORED, user_id=1)
    res = build_blood_test_rows(doc, stored_name=STORED, user_id=1)
    assert res.rows == (single.row,)
    assert res.reason == single.reason == "ok"


def test_series_of_non_lab_kind_gives_no_rows():
    res = build_blood_test_rows({**_series_doc(), "doc_kind": "other"}, stored_name=STORED, user_id=1)
    assert res.rows == ()
    assert res.reason == "not_lab"


@contextmanager
def _handler_db(test_db):
    with patch("handlers.doc_upload.SessionLocal", return_value=test_db):
        yield


def test_save_series_writes_row_per_date_and_says_so(test_db):
    from handlers.doc_upload import _save_to_blood_tests

    with _handler_db(test_db):
        note = _save_to_blood_tests(USER_ID, _series_doc(), STORED)
        again = _save_to_blood_tests(USER_ID, _series_doc(), STORED)

    rows = get_all_blood_tests(test_db, USER_ID)
    assert sorted(r.test_date.isoformat() for r in rows) == ["2016-04-02", "2026-07-14"]
    assert "Добавил в динамику показателей: 3 (2 даты: 2016-04-02 — 2026-07-14)" in note
    assert "Обновил" in again


def test_plural_dates():
    from handlers.doc_upload import _plural_dates

    assert [_plural_dates(n) for n in (1, 2, 5, 11, 13, 21, 22, 25)] == [
        "дата",
        "даты",
        "дат",
        "дат",
        "дат",
        "дата",
        "даты",
        "дат",
    ]


# ── превью ───────────────────────────────────────────────────────────────────


def test_preview_shows_series_newest_first():
    from handlers.doc_upload import _preview_text

    doc = _series_doc()
    doc["series"] = [{"date": f"20{10 + i}-01-01", "values": {"ALT": i}} for i in range(8)]
    text = _preview_text(doc)
    assert "Сводная таблица:</b> 8 дат, 2010-01-01 — 2017-01-01" in text
    assert text.index("2017-01-01: ALT 7") < text.index("2016-01-01: ALT 6")
    assert "2011-01-01: ALT" not in text
    assert "ещё 2 даты" in text


def test_series_only_document_is_not_empty():
    from handlers.doc_upload import _has_content

    assert _has_content({"values": {}, "series": [{"date": "2026-01-01", "values": {"ALT": 1}}]})


# ── дубли ────────────────────────────────────────────────────────────────────


def test_series_reupload_flagged():
    saved = [{"file": "old.pdf", "extracted": _series_doc()}]
    assert find_similar_document(saved, _series_doc()) is saved[0]


def test_series_not_flagged_against_single_date_blank():
    """Бланк за 14.07 уже сохранён — досье с этой датой среди десяти других не дубль."""
    blank = {"date": "2026-07-14", "doc_kind": "lab_panel", "values": {"cholesterol": 5.09, "LDL": 2.18, "HDL": 2.43}}
    new = _series_doc()
    new["series"] = [
        {"date": f"20{10 + i}-01-01", "values": {"cholesterol": 4 + i / 10, "LDL": 2 + i / 10}} for i in range(5)
    ] + [{"date": "2026-07-14", "values": {"cholesterol": 5.09, "LDL": 2.18}}]
    assert find_similar_document([{"file": "b.pdf", "extracted": blank}], new) is None


def test_blank_not_flagged_against_dossier():
    """Первичный бланк, чьи числа есть в досье, — не дубль досье: бланк ценнее пересказа."""
    blank = {"date": "2026-07-14", "doc_kind": "lab_panel", "values": {"cholesterol": 5.09, "LDL": 2.18, "HDL": 2.43}}
    dossier = _series_doc()
    dossier["series"][1]["values"]["HDL"] = 2.43
    assert find_similar_document([{"file": "d.pdf", "extracted": dossier}], blank) is None
