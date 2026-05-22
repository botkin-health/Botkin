"""Тесты snapshot helper'а — фиксации состояния юзера до изменений."""

import json
import time

from scripts.onboard.snapshot import (
    UserSnapshot,
    save_snapshot,
    load_latest_snapshot,
)


def test_save_snapshot_writes_json(tmp_path):
    snap = UserSnapshot(
        telegram_id=999,
        cohort="external",
        pack_name="generic",
        agent_system_prompt="",
        kb_existed_on_server=False,
    )
    path = save_snapshot(snap, snapshots_dir=tmp_path)

    assert path.exists()
    data = json.loads(path.read_text())
    assert data["telegram_id"] == 999
    assert data["cohort"] == "external"
    assert data["kb_existed_on_server"] is False
    assert "timestamp" in data


def test_load_latest_picks_most_recent(tmp_path):
    """Если несколько снапшотов, берём последний по timestamp."""
    snap_a = UserSnapshot(999, "external", "generic", "", False)
    snap_b = UserSnapshot(999, "family", "respiratory_allergic", "promptB", True)

    save_snapshot(snap_a, snapshots_dir=tmp_path)
    # симуляция времени — пишем второй с явно более поздним именем
    time.sleep(0.01)
    save_snapshot(snap_b, snapshots_dir=tmp_path)

    latest = load_latest_snapshot(telegram_id=999, snapshots_dir=tmp_path)
    assert latest.cohort == "family"
    assert latest.pack_name == "respiratory_allergic"


def test_load_latest_returns_none_when_missing(tmp_path):
    # Branch 1: dir exists but contains no matching snapshot files
    assert load_latest_snapshot(telegram_id=12345, snapshots_dir=tmp_path) is None
    # Branch 2: dir does not exist at all (the `if not exists: return None` guard)
    assert load_latest_snapshot(telegram_id=12345, snapshots_dir=tmp_path / "subdir") is None
