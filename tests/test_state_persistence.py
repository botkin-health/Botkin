"""Состояние переживает рестарт процесса бота (ADR-0012).

Прецедент 30.10.2026: превью супа собрано в 20:59:20, рестарт от деплоя в
20:59:29 → «Сохранить» ответил «Состояние истекло», запись не попала в
nutrition_log. Рестарт имитируем новым экземпляром StateManager на том же каталоге.
"""

import json
import time
from datetime import date, datetime, time as dtime
from pathlib import Path

from services.state import StateManager, UserState
from services.state_helpers import build_meal_state_data


def _meal_preview(user_id: str) -> UserState:
    return UserState(
        user_id=user_id,
        state="waiting_confirmation",
        data=build_meal_state_data(
            dish_name="Суп",
            meal_items=[{"name": "Суп", "calories": 120, "weight": 300, "fiber": 2.0}],
            meal_totals={"calories": 120, "protein": 5, "fats": 4, "carbs": 15},
            photo_paths=["/app/data/media/nutrition/2026-10-30/abc.jpg"],
            meal_time="23:59",
            slot="dinner",
            menu_ocr=True,
            product_label={"per_100g": {"calories": 40}},
        ),
    )


def test_preview_survives_restart(tmp_path):
    before = StateManager(state_dir=tmp_path)
    preview = _meal_preview("895655")
    before.set_state("895655", preview)

    after = StateManager(state_dir=tmp_path)  # «рестарт контейнера»
    restored = after.get_state("895655")

    assert restored is not None
    assert restored.state == "waiting_confirmation"
    assert restored.user_id == "895655"
    assert restored.data == preview.data


def test_non_json_types_round_trip(tmp_path):
    data = {
        "media_path": Path("/app/data/media/voice/1.ogg"),
        "date": date(2026, 10, 30),
        "at": datetime(2026, 10, 30, 20, 59, 20),
        "meal_time": dtime(20, 59),
        "pair": (1, 2),
        "nested": {"paths": [Path("/a"), Path("/b")]},
    }
    StateManager(state_dir=tmp_path).set_state("1", UserState("1", "waiting_description", data))

    restored = StateManager(state_dir=tmp_path).get_state("1").data
    assert restored["media_path"] == Path("/app/data/media/voice/1.ogg")
    assert restored["date"] == date(2026, 10, 30)
    assert restored["at"] == datetime(2026, 10, 30, 20, 59, 20)
    assert restored["meal_time"] == dtime(20, 59)
    assert restored["pair"] == [1, 2]
    assert restored["nested"]["paths"] == [Path("/a"), Path("/b")]


def test_int_and_str_user_id_share_file(tmp_path):
    StateManager(state_dir=tmp_path).set_state(42, UserState("42", "waiting_confirmation", {"x": 1}))
    assert StateManager(state_dir=tmp_path).get_state("42").data == {"x": 1}


def test_clear_state_removes_file(tmp_path):
    mgr = StateManager(state_dir=tmp_path)
    mgr.set_state("7", UserState("7", "waiting_confirmation", {}))
    mgr.clear_state("7")

    assert not list(tmp_path.glob("*.json"))
    assert StateManager(state_dir=tmp_path).get_state("7") is None


def test_expired_state_not_restored_and_purged(tmp_path):
    StateManager(state_dir=tmp_path).set_state("7", UserState("7", "waiting_confirmation", {}))
    payload = json.loads((tmp_path / "7.json").read_text())
    payload["updated_at"] = time.time() - 3600
    (tmp_path / "7.json").write_text(json.dumps(payload))

    assert StateManager(state_dir=tmp_path, ttl_seconds=60).get_state("7") is None
    assert not (tmp_path / "7.json").exists()

    (tmp_path / "8.json").write_text(json.dumps({**payload, "user_id": "8"}))
    StateManager(state_dir=tmp_path, ttl_seconds=60)  # чистка при старте
    assert not (tmp_path / "8.json").exists()


def test_expired_in_memory_state_dropped(tmp_path):
    mgr = StateManager(state_dir=tmp_path, ttl_seconds=0.01)
    mgr.set_state("7", UserState("7", "waiting_confirmation", {}))
    time.sleep(0.05)
    assert mgr.get_state("7") is None


def test_unserializable_data_stays_in_memory_and_drops_stale_file(tmp_path):
    mgr = StateManager(state_dir=tmp_path)
    mgr.set_state("7", UserState("7", "waiting_confirmation", {"v": 1}))
    weird = UserState("7", "waiting_confirmation", {"obj": object()})
    mgr.set_state("7", weird)

    assert mgr.get_state("7") is weird
    # старая копия {"v": 1} не должна всплыть после рестарта
    assert StateManager(state_dir=tmp_path).get_state("7") is None


def test_corrupt_file_ignored(tmp_path):
    (tmp_path / "7.json").write_text("{not json")
    assert StateManager(state_dir=tmp_path).get_state("7") is None
    assert not (tmp_path / "7.json").exists()


def test_unsafe_key_memory_only(tmp_path):
    mgr = StateManager(state_dir=tmp_path)
    mgr.set_state("../evil", UserState("x", "s", {}))
    assert mgr.get_state("../evil") is not None
    assert not list(tmp_path.parent.glob("evil*"))
    assert not list(tmp_path.glob("*.json"))


def test_memory_only_mode():
    mgr = StateManager()
    mgr.set_state("1", UserState("1", "s", {}))
    assert mgr.get_state("1").state == "s"
    mgr.clear_state("1")
    assert mgr.get_state("1") is None
