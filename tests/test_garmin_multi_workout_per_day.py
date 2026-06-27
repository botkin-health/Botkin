"""Тест: несколько тренировок Garmin в один день записываются в workouts.

Регрессия на баг: дедупликация шла по date, а не по source.
Если силовая уже вставлена → йога за тот же день молча пропускалась.
Фикс: ключ existing = source (garmin_<activity_id>).
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_activity(activity_id: int, type_key: str, start: str, duration_sec: int = 3600) -> dict:
    return {
        "activityId": activity_id,
        "activityType": {"typeKey": type_key},
        "startTimeLocal": start,
        "duration": duration_sec,
        "distance": 0,
        "calories": 100,
    }


class _FakeCursor:
    def __init__(self, existing_sources: dict):
        self._existing = list(existing_sources.items())
        self._update_calls: list[tuple] = []

    def execute(self, sql, params=None):
        if params is not None:
            self._update_calls.append(params)

    def fetchall(self):
        return self._existing

    def close(self):
        pass


class _FakeConn:
    def __init__(self, existing_sources: dict):
        self.cursor_obj = _FakeCursor(existing_sources)
        self.committed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True


# ── tests ─────────────────────────────────────────────────────────────────────


def test_two_workouts_same_day_both_inserted(tmp_path):
    """Силовая + йога в один день → обе должны попасть в to_insert."""
    acts_dir = tmp_path / "activities"
    acts_dir.mkdir()

    # Имена файлов должны начинаться с даты >= since, иначе f.name[:10] < since → пропуск
    (acts_dir / "2026-06-27_1001.json").write_text(
        json.dumps(_make_activity(1001, "strength_training", "2026-06-27 09:00:00"))
    )
    (acts_dir / "2026-06-27_1002.json").write_text(
        json.dumps(_make_activity(1002, "yoga", "2026-06-27 18:00:00", 2700))
    )

    conn = _FakeConn(existing_sources={})
    captured_inserts = []

    import scripts.util.server_backfill_postgres as sbp

    with (
        patch.object(sbp, "GARMIN_ACTS", acts_dir),
        patch("psycopg2.extras.execute_values", side_effect=lambda cur, sql, rows: captured_inserts.extend(rows)),
    ):
        result = sbp.sync_workouts(conn, user_id=895655, since="2026-01-01", dry_run=False)

    assert result["inserted"] == 2, f"Ожидалось 2, получено {result['inserted']}"
    sources = [row[8] for row in captured_inserts]
    assert "garmin_1001" in sources
    assert "garmin_1002" in sources
    types = [row[2] for row in captured_inserts]
    assert "strength_training" in types
    assert "yoga" in types


def test_existing_activity_not_reinserted(tmp_path):
    """Активность уже в БД → не вставляем повторно."""
    acts_dir = tmp_path / "activities"
    acts_dir.mkdir()
    (acts_dir / "2026-06-27_1001.json").write_text(
        json.dumps(_make_activity(1001, "strength_training", "2026-06-27 09:00:00"))
    )

    conn = _FakeConn(existing_sources={"garmin_1001": None})
    captured_inserts = []

    import scripts.util.server_backfill_postgres as sbp

    with (
        patch.object(sbp, "GARMIN_ACTS", acts_dir),
        patch("psycopg2.extras.execute_values", side_effect=lambda cur, sql, rows: captured_inserts.extend(rows)),
    ):
        result = sbp.sync_workouts(conn, user_id=895655, since="2026-01-01", dry_run=False)

    assert result["inserted"] == 0
    assert captured_inserts == []


def test_yoga_type_mapped_correctly(tmp_path):
    """typeKey=yoga → workout_type=yoga (не фильтруется и не маппится в другое)."""
    acts_dir = tmp_path / "activities"
    acts_dir.mkdir()
    (acts_dir / "2026-06-27_2001.json").write_text(
        json.dumps(_make_activity(2001, "yoga", "2026-06-27 07:00:00", 2700))
    )

    conn = _FakeConn(existing_sources={})
    captured_inserts = []

    import scripts.util.server_backfill_postgres as sbp

    with (
        patch.object(sbp, "GARMIN_ACTS", acts_dir),
        patch("psycopg2.extras.execute_values", side_effect=lambda cur, sql, rows: captured_inserts.extend(rows)),
    ):
        result = sbp.sync_workouts(conn, user_id=895655, since="2026-01-01", dry_run=False)

    assert result["inserted"] == 1
    assert captured_inserts[0][2] == "yoga"  # workout_type — 3-й элемент кортежа


def test_unknown_type_key_passed_through(tmp_path):
    """Неизвестный typeKey ('stretching') → сохраняется as-is, не дропается."""
    acts_dir = tmp_path / "activities"
    acts_dir.mkdir()
    (acts_dir / "2026-06-27_3001.json").write_text(
        json.dumps(_make_activity(3001, "stretching", "2026-06-27 06:00:00", 1800))
    )

    conn = _FakeConn(existing_sources={})
    captured_inserts = []

    import scripts.util.server_backfill_postgres as sbp

    with (
        patch.object(sbp, "GARMIN_ACTS", acts_dir),
        patch("psycopg2.extras.execute_values", side_effect=lambda cur, sql, rows: captured_inserts.extend(rows)),
    ):
        result = sbp.sync_workouts(conn, user_id=895655, since="2026-01-01", dry_run=False)

    assert result["inserted"] == 1
    assert captured_inserts[0][2] == "stretching"


def test_distance_update_uses_source_not_date(tmp_path):
    """UPDATE дистанции происходит по source='garmin_<id>', не по date."""
    acts_dir = tmp_path / "activities"
    acts_dir.mkdir()
    run = _make_activity(4001, "running", "2026-06-27 07:00:00", 1800)
    run["distance"] = 5000  # 5 км
    (acts_dir / "2026-06-27_4001.json").write_text(json.dumps(run))

    conn = _FakeConn(existing_sources={"garmin_4001": None})  # есть, без дистанции

    import scripts.util.server_backfill_postgres as sbp

    with (
        patch.object(sbp, "GARMIN_ACTS", acts_dir),
        patch("psycopg2.extras.execute_values"),
    ):
        result = sbp.sync_workouts(conn, user_id=895655, since="2026-01-01", dry_run=False)

    assert result["updated"] == 1
    update_params = conn.cursor_obj._update_calls
    assert any("garmin_4001" in str(p) for p in update_params), (
        f"Ожидали source='garmin_4001' в UPDATE-параметрах, получили: {update_params}"
    )
