"""Тесты парсера тренировок Health Auto Export (#100).

HAE шлёт тренировки отдельным POST с `data.workouts[]`. Формат между вики HAE
и примером из issue немного расходится (поле `name` vs `workoutActivityType`,
длительность в секундах vs `{qty, units}`), поэтому парсер должен понимать обе
схемы. `_hae_workouts_to_rows` превращает их в строки таблицы `workouts`.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

from webhook.apple_health import _hae_workouts_to_rows  # noqa: E402

USER = 485132


def test_empty_list_returns_empty():
    assert _hae_workouts_to_rows([], USER) == []


def test_wiki_v2_shape_seconds_and_name():
    rows = _hae_workouts_to_rows(
        [
            {
                "id": "ABC",
                "name": "Running",
                "start": "2026-06-14 08:00:00 +0300",
                "end": "2026-06-14 08:45:00 +0300",
                "duration": 2700,  # секунды
                "distance": {"qty": 5.2, "units": "km"},
                "activeEnergyBurned": {"qty": 350, "units": "kcal"},
            }
        ],
        USER,
    )
    assert len(rows) == 1
    r = rows[0]
    assert r["user_id"] == USER
    assert r["date"] == "2026-06-14"
    assert r["workout_type"] == "Running"
    assert r["duration_minutes"] == 45
    assert r["distance_km"] == 5.2
    assert r["calories_burned"] == 350
    assert r["source"] == "hae_ABC"
    assert isinstance(r["start_time"], datetime)
    assert isinstance(r["end_time"], datetime)


def test_issue_shape_hk_type_and_minutes():
    rows = _hae_workouts_to_rows(
        [
            {
                "workoutActivityType": "HKWorkoutActivityTypeRunning",
                "duration": {"qty": 45, "units": "min"},
                "distance": {"qty": 5.2, "units": "km"},
                "activeEnergy": {"qty": 350, "units": "kcal"},
                "startDate": "2026-06-14 08:00:00 +0300",
                "endDate": "2026-06-14 08:45:00 +0300",
                "sourceName": "Apple Watch",
            }
        ],
        USER,
    )
    r = rows[0]
    assert r["workout_type"] == "Running"  # префикс HKWorkoutActivityType снят
    assert r["duration_minutes"] == 45
    assert r["date"] == "2026-06-14"
    assert r["calories_burned"] == 350


def test_miles_converted_to_km():
    rows = _hae_workouts_to_rows(
        [
            {
                "name": "Walking",
                "start": "2026-06-14 08:00:00 +0300",
                "end": "2026-06-14 08:30:00 +0300",
                "duration": 1800,
                "distance": {"qty": 1.0, "units": "mi"},
            }
        ],
        USER,
    )
    assert abs(rows[0]["distance_km"] - 1.60934) < 0.001


def test_missing_optionals_are_none():
    rows = _hae_workouts_to_rows(
        [
            {
                "name": "Yoga",
                "start": "2026-06-14 07:00:00 +0300",
                "end": "2026-06-14 07:30:00 +0300",
                "duration": 1800,
            }
        ],
        USER,
    )
    r = rows[0]
    assert r["distance_km"] is None
    assert r["calories_burned"] is None
    assert r["workout_type"] == "Yoga"
    assert r["duration_minutes"] == 30


def test_total_energy_fallback_for_calories():
    rows = _hae_workouts_to_rows(
        [
            {
                "name": "Ride",
                "start": "2026-06-14 07:00:00 +0300",
                "end": "2026-06-14 07:30:00 +0300",
                "duration": 1800,
                "totalEnergy": {"qty": 200, "units": "kcal"},
            }
        ],
        USER,
    )
    assert rows[0]["calories_burned"] == 200


def test_source_fallback_without_id_is_stable():
    w = {
        "name": "Run",
        "start": "2026-06-14 08:00:00 +0300",
        "end": "2026-06-14 08:45:00 +0300",
        "duration": 2700,
    }
    r1 = _hae_workouts_to_rows([w], USER)[0]
    r2 = _hae_workouts_to_rows([w], USER)[0]
    assert r1["source"].startswith("hae_")
    assert r1["source"] == r2["source"]  # детерминированный → дедуп работает


def test_workout_without_dates_skipped():
    assert _hae_workouts_to_rows([{"name": "Broken"}], USER) == []


def test_unknown_type_defaults_to_workout():
    rows = _hae_workouts_to_rows(
        [{"start": "2026-06-14 08:00:00 +0300", "end": "2026-06-14 08:45:00 +0300", "duration": 2700}],
        USER,
    )
    assert rows[0]["workout_type"] == "Workout"


# --- Legacy v1: нет duration / нет id (#174) ----------------------------------


def test_v1_duration_computed_from_start_end_when_missing():
    # v1 legacy не присылает duration → считаем из start/end
    rows = _hae_workouts_to_rows(
        [{"name": "Run", "start": "2026-06-14 08:00:00 +0300", "end": "2026-06-14 08:50:00 +0300"}],
        USER,
    )
    assert rows[0]["duration_minutes"] == 50


def test_v1_duration_none_when_no_duration_and_no_end():
    rows = _hae_workouts_to_rows([{"name": "Run", "start": "2026-06-14 08:00:00 +0300"}], USER)
    assert rows[0]["duration_minutes"] is None


def test_v1_source_from_name_start_end_when_no_id():
    # две v1-тренировки с одинаковым стартом, но разным концом — НЕ должны схлопнуться
    w1 = {"name": "Run", "start": "2026-06-14 08:00:00 +0300", "end": "2026-06-14 08:30:00 +0300"}
    w2 = {"name": "Run", "start": "2026-06-14 08:00:00 +0300", "end": "2026-06-14 09:00:00 +0300"}
    rows = _hae_workouts_to_rows([w1, w2], USER)
    assert rows[0]["source"] != rows[1]["source"]
    assert "Run" in rows[0]["source"]


def test_v2_with_id_source_and_duration_unchanged():
    rows = _hae_workouts_to_rows(
        [
            {
                "id": "ABC",
                "name": "Run",
                "start": "2026-06-14 08:00:00 +0300",
                "end": "2026-06-14 08:45:00 +0300",
                "duration": 2700,
            }
        ],
        USER,
    )
    assert rows[0]["source"] == "hae_ABC"  # id-путь не тронут
    assert rows[0]["duration_minutes"] == 45  # из duration, не из start/end


# --- Вставка с дедупом (фейковая БД, без реального Postgres) -------------------


class _FakeDB:
    """Минимальный stub SQLAlchemy session: SELECT отдаёт preset existing-source,
    INSERT-вызовы копятся в self.inserts."""

    def __init__(self, existing_sources):
        self._existing = [(s,) for s in existing_sources]
        self.inserts = []

    def execute(self, stmt, params=None):
        sql = str(stmt).upper()
        if sql.strip().startswith("SELECT"):
            return list(self._existing)
        self.inserts.append(params)
        return None


def _rows(*sources):
    base = {
        "user_id": USER,
        "date": "2026-06-14",
        "workout_type": "Running",
        "duration_minutes": 45,
        "start_time": datetime(2026, 6, 14, 8, 0, 0),
        "end_time": datetime(2026, 6, 14, 8, 45, 0),
        "calories_burned": 350,
        "distance_km": 5.2,
    }
    return [{**base, "source": s} for s in sources]


def test_insert_skips_existing_sources():
    from webhook.apple_health import _insert_new_workouts

    db = _FakeDB(existing_sources={"hae_A"})
    inserted = _insert_new_workouts(db, USER, _rows("hae_A", "hae_B"))
    assert inserted == 1
    assert [p["source"] for p in db.inserts] == ["hae_B"]


def test_insert_dedups_within_same_batch():
    from webhook.apple_health import _insert_new_workouts

    db = _FakeDB(existing_sources=set())
    inserted = _insert_new_workouts(db, USER, _rows("hae_A", "hae_A", "hae_B"))
    assert inserted == 2
    assert [p["source"] for p in db.inserts] == ["hae_A", "hae_B"]


def test_insert_empty_returns_zero():
    from webhook.apple_health import _insert_new_workouts

    db = _FakeDB(existing_sources=set())
    assert _insert_new_workouts(db, USER, []) == 0
    assert db.inserts == []
