"""Тесты разбора давления с РЕАЛЬНЫМ временем замера.

Автоматизация «Показатели здоровья» идёт с группировкой «День» (это нужно для
суточных сумм энергии), поэтому давление схлопывалось в одно значение с полуночной
меткой, а v2 писал его условным временем 08:00. Все записи в базе получали
одинаковую метку, и сопоставить эпизод тахикардии с давлением было нечем.

Лечение — отдельная автоматизация только под давление, без суточной группировки.
Эти тесты фиксируют разбор её пакета.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

from webhook.apple_health import _hae_bp_measurements  # noqa: E402


def _metric(name: str, points: list[dict]) -> dict:
    return {"name": name, "units": "mmHg", "data": points}


def test_empty_returns_empty():
    assert _hae_bp_measurements([]) == []


def test_pairs_systolic_and_diastolic_by_timestamp():
    rows = _hae_bp_measurements(
        [
            _metric("blood_pressure_systolic", [{"date": "2026-09-14 11:23:00 +0300", "qty": 112}]),
            _metric("blood_pressure_diastolic", [{"date": "2026-09-14 11:23:00 +0300", "qty": 80}]),
        ]
    )
    assert len(rows) == 1
    assert rows[0]["systolic"] == 112
    assert rows[0]["diastolic"] == 80
    assert rows[0]["measured_at"].isoformat() == "2026-09-14T11:23:00+03:00"


def test_several_measurements_per_day_kept_separately():
    """Ровно та причина, по которой всё затевалось: два замера — две строки."""
    rows = _hae_bp_measurements(
        [
            _metric(
                "blood_pressure_systolic",
                [
                    {"date": "2026-09-14 08:05:00 +0300", "qty": 118},
                    {"date": "2026-09-14 21:40:00 +0300", "qty": 106},
                ],
            ),
            _metric(
                "blood_pressure_diastolic",
                [
                    {"date": "2026-09-14 08:05:00 +0300", "qty": 84},
                    {"date": "2026-09-14 21:40:00 +0300", "qty": 76},
                ],
            ),
        ]
    )
    assert [r["systolic"] for r in rows] == [118, 106]  # по возрастанию времени
    assert [r["measured_at"].hour for r in rows] == [8, 21]


def test_midnight_point_ignored_as_daily_aggregate():
    """Полночь = суточный агрегат при группировке «День», реального времени нет."""
    rows = _hae_bp_measurements(
        [
            _metric("blood_pressure_systolic", [{"date": "2026-09-14 00:00:00 +0300", "qty": 112}]),
            _metric("blood_pressure_diastolic", [{"date": "2026-09-14 00:00:00 +0300", "qty": 80}]),
        ]
    )
    assert rows == []


def test_half_measurement_dropped():
    """Только систолическое без диастолического — половина замера, не пишем."""
    rows = _hae_bp_measurements(
        [_metric("blood_pressure_systolic", [{"date": "2026-09-14 11:23:00 +0300", "qty": 112}])]
    )
    assert rows == []


def test_timestamps_must_match_exactly():
    """Разное время = разные замеры, склеивать нельзя."""
    rows = _hae_bp_measurements(
        [
            _metric("blood_pressure_systolic", [{"date": "2026-09-14 11:23:00 +0300", "qty": 112}]),
            _metric("blood_pressure_diastolic", [{"date": "2026-09-14 11:24:00 +0300", "qty": 80}]),
        ]
    )
    assert rows == []


def test_combined_blood_pressure_metric():
    """Некоторые версии HAE шлют пару одной метрикой."""
    rows = _hae_bp_measurements(
        [_metric("blood_pressure", [{"date": "2026-09-14 11:23:00 +0300", "systolic": 112, "diastolic": 80}])]
    )
    assert len(rows) == 1 and rows[0]["systolic"] == 112 and rows[0]["diastolic"] == 80


def test_avg_used_when_no_qty():
    rows = _hae_bp_measurements(
        [
            _metric("blood_pressure_systolic", [{"date": "2026-09-14 11:23:00 +0300", "Avg": 111.6}]),
            _metric("blood_pressure_diastolic", [{"date": "2026-09-14 11:23:00 +0300", "Avg": 79.4}]),
        ]
    )
    assert rows[0]["systolic"] == 112 and rows[0]["diastolic"] == 79  # округление


def test_garbage_ignored():
    rows = _hae_bp_measurements(
        [
            _metric("blood_pressure_systolic", ["не словарь", {"date": "вчера", "qty": 112}, {"qty": 118}]),
            _metric("blood_pressure_diastolic", [{"date": "2026-09-14 11:23:00 +0300", "qty": 80}]),
            _metric("step_count", [{"date": "2026-09-14 11:23:00 +0300", "qty": 900}]),
        ]
    )
    assert rows == []


def test_other_metrics_do_not_leak_in():
    rows = _hae_bp_measurements([_metric("heart_rate", [{"date": "2026-09-14 11:23:00 +0300", "qty": 67}])])
    assert rows == []
