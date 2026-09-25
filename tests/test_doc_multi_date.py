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
            RuntimeError("timeout again"),
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


# ── ревью #564 ───────────────────────────────────────────────────────────────


def _lab_page(tag: str) -> str:
    return "Печеночные пробы АЛТ АСТ ГГТ лаборатория " + tag * 5000


@pytest.mark.asyncio
async def test_numeric_only_page_is_not_dropped_by_readability_gate():
    """Страница таблицы из дат и чисел сама «без букв», но документ читается целиком."""
    responses = [
        _fake_response({"date": "2026-07-14", "doc_kind": "lab_panel", "values": {"ALT": 29}}),
        _fake_response({"date": "2023-03-01", "doc_kind": "lab_panel", "values": {"ALT": 12}}),
    ]
    call = AsyncMock(side_effect=responses)
    digits = "\n".join(f"01.03.20{i:02d} 5.4 141 4.2 12.2 10.9" for i in range(300))
    with patch.object(doc_extractor, "_call_anthropic", new=call):
        out = await doc_extractor.extract_medical_data_from_pages([_lab_page("а"), digits])
    assert call.await_count == 2
    assert sorted(e["date"] for e in out["series"]) == ["2023-03-01", "2026-07-14"]


@pytest.mark.asyncio
async def test_unreadable_long_document_skips_model():
    call = AsyncMock()
    with patch.object(doc_extractor, "_call_anthropic", new=call):
        out = await doc_extractor.extract_medical_data_from_pages(["." * 7000, "#" * 7000])
    assert call.await_count == 0
    assert out["_unreadable_text"] is True


@pytest.mark.asyncio
async def test_later_parts_get_document_head_as_context():
    """Шапка первой страницы (дата взятия, единицы) — контекст каждой следующей части."""
    call = AsyncMock(return_value=_fake_response({"date": "2026-07-14", "doc_kind": "lab_panel", "values": {"ALT": 1}}))
    pages = ["ШАПКА мг/дл " + _lab_page("а"), _lab_page("б"), _lab_page("в")]
    with patch.object(doc_extractor, "_call_anthropic", new=call):
        await doc_extractor.extract_medical_data_from_pages(pages)
    texts = [[b["text"] for b in c.args[0][0]["content"]] for c in call.await_args_list]
    assert len(texts) == 3
    assert not any("Начало документа" in t for t in texts[0])
    for later in texts[1:]:
        assert "ШАПКА мг/дл" in later[0] and "Начало документа" in later[0]
    # Конец предыдущей страницы — там стоит заголовок таблицы, строки которой идут дальше.
    assert pages[1][-100:] in texts[2][0]
    assert pages[0][-100:] in texts[1][0]


@pytest.mark.asyncio
async def test_failed_parts_counted_with_total():
    call = AsyncMock(
        side_effect=[
            _fake_response({"date": "2026-07-14", "doc_kind": "lab_panel", "values": {"ALT": 29}}),
            RuntimeError("timeout"),
            _fake_response({"date": "2025-12-12", "doc_kind": "lab_panel", "values": {"ALT": 21}}),
            RuntimeError("timeout again"),
        ]
    )
    with patch.object(doc_extractor, "_call_anthropic", new=call):
        out = await doc_extractor.extract_medical_data_from_pages([_lab_page("а"), _lab_page("б"), _lab_page("в")])
    assert out["_chunks_failed"] == 1
    assert out["_chunks_total"] == 3


def test_preview_warns_about_failed_parts():
    from handlers.doc_upload import _preview_text

    doc = {**_series_doc(), "_chunks_failed": 2, "_chunks_total": 15}
    assert "Не получилось разобрать 2 из 15 частей" in _preview_text(doc)
    assert "Не получилось разобрать" not in _preview_text(_series_doc())


def test_merge_keeps_rejected_rows_of_parts():
    parts = [
        {"date": "2026-07-14", "doc_kind": "lab_panel", "values": {"ALT": 29}, "_series_rejected": ["'2023': not_iso"]},
        {"date": "2025-12-12", "doc_kind": "lab_panel", "values": {"ALT": 21}},
    ]
    assert doc_extractor.merge_extractions(parts)["_series_rejected"] == ["'2023': not_iso"]


def test_series_document_is_lab_for_agent():
    from core.health.profile_documents import _is_lab

    assert _is_lab({"extracted": _series_doc()})


@pytest.mark.asyncio
async def test_failed_part_retried_once():
    call = AsyncMock(
        side_effect=[
            _fake_response({"date": "2026-07-14", "doc_kind": "lab_panel", "values": {"ALT": 29}}),
            RuntimeError("max_tokens"),
            _fake_response({"date": "2024-01-10", "doc_kind": "lab_panel", "values": {"ALT": 18}}),
            _fake_response({"date": "2025-12-12", "doc_kind": "lab_panel", "values": {"ALT": 21}}),
        ]
    )
    with patch.object(doc_extractor, "_call_anthropic", new=call):
        out = await doc_extractor.extract_medical_data_from_pages([_lab_page("а"), _lab_page("б"), _lab_page("в")])
    assert call.await_count == 4
    assert "_chunks_failed" not in out
    assert sorted(e["date"] for e in out["series"]) == ["2024-01-10", "2025-12-12", "2026-07-14"]


@pytest.mark.asyncio
async def test_parts_use_medium_effort_plain_documents_default():
    call = AsyncMock(return_value=_fake_response({"date": "2026-07-14", "doc_kind": "lab_panel", "values": {"ALT": 1}}))
    with patch.object(doc_extractor, "_call_anthropic", new=call):
        await doc_extractor.extract_medical_data_from_pages([_lab_page("а"), _lab_page("б"), _lab_page("в")])
        await doc_extractor.extract_medical_data(b"x", "image/jpeg")
    efforts = [c.args[1] if len(c.args) > 1 else None for c in call.await_args_list]
    assert efforts == ["medium", "medium", "medium", None]


# ── единица строки сводной таблицы ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_row_unit_overrides_shared_unit():
    """Витамин D одной даты — в нмоль/л, остальных — в нг/мл: пересчитывается только эта дата."""
    payload = {
        "doc_kind": "lab_panel",
        "values": {},
        "units": {"vitamin_D": "нг/мл"},
        "series": [
            {"date": "2026-07-14", "values": {"vitamin_D": 77.7}, "units": {"vitamin_D": "нмоль/л"}},
            {"date": "2025-12-12", "values": {"vitamin_D": 24.3}},
        ],
    }
    out = await _extract(payload)
    by_date = {e["date"]: e for e in out["series"]}
    assert by_date["2026-07-14"]["values"]["vitamin_D"] == pytest.approx(31.13, abs=0.01)
    assert by_date["2026-07-14"]["units"] == {"vitamin_D": "нг/мл"}
    assert by_date["2025-12-12"]["values"]["vitamin_D"] == 24.3
    assert out["units"]["vitamin_D"] == "нг/мл"


@pytest.mark.asyncio
async def test_testosterone_ng_ml_converted_to_nmol_l():
    payload = {
        "doc_kind": "lab_panel",
        "values": {},
        "units": {"testosterone": "нмоль/л"},
        "series": [
            {"date": "2022-05-11", "values": {"testosterone": 3.617}, "units": {"testosterone": "нг/мл"}},
            {"date": "2025-12-12", "values": {"testosterone": 17.4}},
        ],
    }
    out = await _extract(payload)
    by_date = {e["date"]: e["values"]["testosterone"] for e in out["series"]}
    assert by_date == {"2022-05-11": pytest.approx(12.54, abs=0.01), "2025-12-12": 17.4}


@pytest.mark.asyncio
async def test_plain_document_vitamin_d_nmol_converted():
    out = await _extract({"date": "2026-07-14", "values": {"vitamin_D": 77.7}, "units": {"vitamin_D": "nmol/L"}})
    assert out["values"]["vitamin_D"] == pytest.approx(31.13, abs=0.01)
    assert out["units"]["vitamin_D"] == "нг/мл"


def test_row_unit_survives_collapse_and_merge():
    data = {"series": [{"date": "2026-07-14", "values": {"vitamin_D": 77.7}, "units": {"vitamin_D": "нмоль/л"}}]}
    doc_extractor._normalize_series(data)
    assert data["units"] == {"vitamin_D": "нмоль/л"}
    parts = [
        {"date": None, "series": [{"date": "2026-07-14", "values": {"D": 1}, "units": {"D": "нмоль/л"}}]},
        {"date": "2025-12-12", "values": {"D": 2}},
    ]
    merged = doc_extractor.merge_extractions(parts)
    assert merged["series"][1]["units"] == {"D": "нмоль/л"}
    assert "units" not in merged["series"][0]


async def _rows(payload):
    out = await _extract(payload)
    res = build_blood_test_rows(out, stored_name=STORED, user_id=1)
    return {r["test_date"]: r["values"] for r in res.rows}, res


@pytest.mark.asyncio
async def test_row_in_other_unconvertible_unit_kept_out_of_dynamics():
    """Пролактин 2022 в мкОд/мл среди нг/мл: пересчитать нечем — в динамику не пишем."""
    rows, res = await _rows(
        {
            "doc_kind": "lab_panel",
            "values": {},
            "units": {"prolactin": "нг/мл", "testosterone": "нмоль/л"},
            "series": [
                {"date": "2020-06-19", "values": {"prolactin": 7.34, "testosterone": 18.4}},
                {
                    "date": "2022-05-11",
                    "values": {"prolactin": 91.94, "testosterone": 3.617},
                    "units": {"prolactin": "мкОд/мл", "testosterone": "нг/мл"},
                },
            ],
        }
    )
    assert rows["2022-05-11"] == {"testosterone": pytest.approx(12.54, abs=0.01)}
    assert rows["2020-06-19"] == {"prolactin": 7.34, "testosterone": 18.4}
    assert any("prolactin: единица строки не та" in w for w in res.warnings)


@pytest.mark.asyncio
async def test_row_unit_duplicating_shared_convertible_unit_kept():
    """Модель продублировала общую «мг/дл» в строках — пересчитано, в динамике все даты."""
    rows, _ = await _rows(
        {
            "doc_kind": "lab_panel",
            "values": {},
            "units": {"hs_CRP": "мг/дл"},
            "series": [
                {"date": "2024-01-01", "values": {"hs_CRP": 0.3}, "units": {"hs_CRP": "мг/дл"}},
                {"date": "2025-01-01", "values": {"hs_CRP": 0.4}, "units": {"hs_CRP": "мг/дл"}},
            ],
        }
    )
    assert rows == {"2024-01-01": {"hs_CRP": 3.0}, "2025-01-01": {"hs_CRP": 4.0}}


@pytest.mark.asyncio
async def test_row_unit_latin_spelling_of_shared_unit_kept():
    rows, _ = await _rows(
        {
            "doc_kind": "lab_panel",
            "values": {},
            "units": {"Hb": "г/л"},
            "series": [
                {"date": "2024-01-01", "values": {"Hb": 150}, "units": {"Hb": "g/L"}},
                {"date": "2025-01-01", "values": {"Hb": 148}},
            ],
        }
    )
    assert rows == {"2024-01-01": {"Hb": 150}, "2025-01-01": {"Hb": 148}}


@pytest.mark.asyncio
async def test_row_units_without_shared_minority_dropped():
    """Общей единицы нет, у строк свои: значение в редкой единице — не в динамику."""
    rows, _ = await _rows(
        {
            "doc_kind": "lab_panel",
            "values": {},
            "units": {},
            "series": [
                {"date": "2022-05-11", "values": {"prolactin": 91.9}, "units": {"prolactin": "мкМЕ/мл"}},
                {"date": "2023-01-01", "values": {"prolactin": 7.3}, "units": {"prolactin": "нг/мл"}},
                {"date": "2024-01-01", "values": {"prolactin": 6.9}, "units": {"prolactin": "нг/мл"}},
            ],
        }
    )
    assert "2022-05-11" not in rows
    assert rows["2023-01-01"] == {"prolactin": 7.3}


def test_merge_unit_taken_from_part_with_values():
    parts = [
        {"date": "2026-01-01", "doc_kind": "lab_panel", "values": {"ALT": 1}, "units": {"vitamin_D": "нмоль/л"}},
        {"date": "2025-01-01", "doc_kind": "lab_panel", "values": {"vitamin_D": 31.1}, "units": {"vitamin_D": "нг/мл"}},
    ]
    assert doc_extractor.merge_extractions(parts)["units"]["vitamin_D"] == "нг/мл"


@pytest.mark.asyncio
async def test_context_tail_starts_at_line_boundary():
    """Конец предыдущей части режется по строке: обрубок «.03.2023» — другая дата."""
    call = AsyncMock(return_value=_fake_response({"date": "2026-07-14", "doc_kind": "lab_panel", "values": {"ALT": 1}}))
    # Граница 1500 символов с конца попадает внутрь «11.03.2023».
    second = "Печеночные пробы " + "б" * 3000 + "\n11.03.2023 5.4\n" + "б" * 1488
    pages = [_lab_page("а"), second, _lab_page("в")]
    with patch.object(doc_extractor, "_call_anthropic", new=call):
        await doc_extractor.extract_medical_data_from_pages(pages)
    context = call.await_args_list[2].args[0][0]["content"][0]["text"]
    tail = context.split("…\n", 1)[1]
    assert tail.startswith("б")
    assert "03.2023" not in tail


@pytest.mark.asyncio
async def test_row_already_in_target_unit_kept_when_shared_is_converted():
    """Общая — нмоль/л (пересчитывается), у строки своя — уже нг/мл: обе даты в динамике."""
    rows, _ = await _rows(
        {
            "doc_kind": "lab_panel",
            "values": {},
            "units": {"vitamin_D": "нмоль/л"},
            "series": [
                {"date": "2023-01-01", "values": {"vitamin_D": 75}},
                {"date": "2024-01-01", "values": {"vitamin_D": 31}, "units": {"vitamin_D": "нг/мл"}},
            ],
        }
    )
    assert rows["2023-01-01"]["vitamin_D"] == pytest.approx(30.05, abs=0.01)
    assert rows["2024-01-01"] == {"vitamin_D": 31}


def test_foreign_unit_detected_after_merge_of_parts():
    """Строка в чужой единице одна в своей части — видна только на склеенном документе."""
    parts = [
        {
            "date": None,
            "doc_kind": "lab_panel",
            "units": {"prolactin": "нг/мл"},
            "series": [
                {"date": "2020-06-19", "values": {"prolactin": 7.34}},
                {"date": "2025-12-12", "values": {"prolactin": 6.71}},
            ],
        },
        {
            "date": "2022-05-11",
            "doc_kind": "lab_panel",
            "values": {"prolactin": 91.94},
            "units": {"prolactin": "мкМЕ/мл"},
        },
    ]
    merged = doc_extractor.merge_extractions(parts)
    rows = {r["test_date"]: r["values"] for r in build_blood_test_rows(merged, stored_name=STORED, user_id=1).rows}
    assert "2022-05-11" not in rows
    assert rows["2020-06-19"] == {"prolactin": 7.34}


@pytest.mark.parametrize(
    "a,b",
    [
        ("мкмоль/л", "µmol/L"),
        ("мкмоль/л", "μmol/l"),
        ("мкМЕ/мл", "µIU/mL"),
        ("×10⁹/л", "x10^9/L"),
        ("10*9/л", "10^9/л"),
        ("мЕд/л", "mU/L"),
        ("фл", "fL"),
        ("мм/ч", "mm/h"),
        ("Ед/л", "U/L"),
        ("г/л", "g/L"),
        ("%", "%"),
        ("нг/мл", "мкг/л"),
        ("пг/мл", "нг/л"),
        ("мкМЕ/мл", "мМЕ/л"),
        ("Ед/л", "МЕ/л"),
        ("10^9/л", "тыс/мкл"),
        ("мм/час", "мм/ч"),
        ("г/л.", "г/л"),
        ("мМЕ/мл", "IU/L"),
        ("мЕд/мл", "МЕ/л"),
        ("µU/mL", "мкЕд/мл"),
        ("uU/mL", "мкЕд/мл"),
    ],
)
def test_unit_spellings_equal(a, b):
    from core.health.doc_to_blood_test import unit_key

    assert unit_key(a) == unit_key(b)


def test_different_units_not_equal():
    from core.health.doc_to_blood_test import unit_key

    assert unit_key("нг/мл") != unit_key("мкМЕ/мл")
    assert unit_key("нмоль/л") != unit_key("нг/мл")


@pytest.mark.asyncio
async def test_same_scale_units_from_different_labs_kept():
    """Ферритин нг/мл и мкг/л, ТТГ мкМЕ/мл и мМЕ/л — одна шкала, все даты в динамике."""
    rows, _ = await _rows(
        {
            "doc_kind": "lab_panel",
            "values": {},
            "units": {"ferritin": "нг/мл", "TSH": "мкМЕ/мл"},
            "series": [
                {"date": "2020-01-01", "values": {"ferritin": 300, "TSH": 2.1}},
                {"date": "2023-01-01", "values": {"ferritin": 90, "TSH": 2.5}, "units": {"TSH": "мМЕ/л"}},
                {"date": "2024-01-01", "values": {"ferritin": 60, "TSH": 2.7}, "units": {"TSH": "мМЕ/л"}},
                {
                    "date": "2025-01-01",
                    "values": {"ferritin": 43.8, "TSH": 3.0},
                    "units": {"ferritin": "мкг/л", "TSH": "мМЕ/л"},
                },
            ],
        }
    )
    assert len(rows) == 4
    assert all(set(v) == {"ferritin", "TSH"} for v in rows.values())
