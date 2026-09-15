"""Тесты парсера лекарств Health Auto Export.

Приём препаратов до 15.09.2026 существовал только в ручных отметках: последняя
была 06.09, и на вопрос «принимаешь ли Кораксан» бот ответить не мог. Apple
ведёт журнал «Медикаменты», HAE умеет его выгружать — пишем в supplements_log,
туда же, куда идут ручные отметки, чтобы приверженность считалась как раньше.

Имя блока и названия полей в HAE документированы плохо, поэтому парсер принимает
несколько вариантов написания — тесты фиксируют именно это поведение.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

from webhook.apple_health import _hae_medications_to_rows, _hae_medication_dosage  # noqa: E402

USER = 836757955

FULL = {
    "name": "Кораксан",
    "dose": {"qty": 1, "units": "таблетка"},
    "date": "2026-09-15 08:30:00 +0300",
    "status": "taken",
}


def test_empty_list_returns_empty():
    assert _hae_medications_to_rows([], USER) == []


def test_full_record_parsed():
    row = _hae_medications_to_rows([FULL], USER)[0]

    assert row["user_id"] == USER
    assert row["date"].isoformat() == "2026-09-15"
    assert row["time"].isoformat() == "08:30:00"
    assert row["supplement_name"] == "Кораксан"
    assert row["dosage"] == "1 таблетка"


def test_skipped_dose_is_not_recorded():
    """Пропуск — тоже факт, но строка в supplements_log означает «принято».

    Записать пропуск как приём значит завысить приверженность — то самое, ради
    чего канал и заводился.
    """
    for status in ("skipped", "Skipped", "notTaken", "not_taken", "unspecified"):
        rec = {**FULL, "status": status}
        assert _hae_medications_to_rows([rec], USER) == [], status


def test_taken_and_unknown_status_are_recorded():
    """Статуса может не быть вовсе — тогда считаем, что приём был."""
    no_status = {k: v for k, v in FULL.items() if k != "status"}
    assert len(_hae_medications_to_rows([no_status], USER)) == 1
    assert len(_hae_medications_to_rows([{**FULL, "status": "taken"}], USER)) == 1


def test_alternative_field_names():
    rec = {
        "medicationName": "Магний хелат",
        "amount": 200,
        "unit": "мг",
        "loggedAt": "2026-09-15 21:00:00 +0300",
    }
    row = _hae_medications_to_rows([rec], USER)[0]

    assert row["supplement_name"] == "Магний хелат"
    assert row["dosage"] == "200 мг"
    assert row["time"].isoformat() == "21:00:00"


def test_record_without_name_skipped():
    rec = {k: v for k, v in FULL.items() if k != "name"}
    assert _hae_medications_to_rows([rec], USER) == []


def test_record_without_parsable_time_skipped():
    """Без времени нечем дедуплицировать повторные выгрузки."""
    assert _hae_medications_to_rows([{**FULL, "date": "вчера"}], USER) == []
    assert _hae_medications_to_rows([{k: v for k, v in FULL.items() if k != "date"}], USER) == []


def test_non_dict_entries_ignored():
    assert _hae_medications_to_rows(["Кораксан", None, 42], USER) == []


def test_dosage_variants():
    assert _hae_medication_dosage({"dose": {"qty": 2.5, "units": "мг"}}) == "2.5 мг"
    assert _hae_medication_dosage({"dose": 1}) == "1"  # единиц нет — только число
    assert _hae_medication_dosage({"unit": "капсула"}) == "капсула"  # числа нет
    assert _hae_medication_dosage({}) is None


def test_dosage_drops_trailing_zeros():
    """1.0 таблетки читается как «1 таблетка», а не «1.0»."""
    assert _hae_medication_dosage({"dose": {"qty": 1.0, "units": "таблетка"}}) == "1 таблетка"


def test_long_name_truncated():
    rec = {**FULL, "name": "Ф" * 300}
    assert len(_hae_medications_to_rows([rec], USER)[0]["supplement_name"]) == 255


def test_several_records_parsed():
    rows = _hae_medications_to_rows(
        [
            FULL,
            {"name": "Омега 3", "date": "2026-09-15 08:31:00 +0300"},
            {"name": "Витамин D3", "date": "2026-09-14 08:30:00 +0300"},
        ],
        USER,
    )
    assert [r["supplement_name"] for r in rows] == ["Кораксан", "Омега 3", "Витамин D3"]
    assert rows[2]["date"].isoformat() == "2026-09-14"
