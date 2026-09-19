"""#480: производные per-user файлы живут на bind-mount, а не внутри контейнера.

`/app/telegram-bot/` — слой образа: каждый деплой пересоздаёт контейнер и стирает
оттуда workouts_log/env_data/biomarkers. До ближайшего ночного синка (окно
04–20 UTC) агент и дашборд молча деградируют к обеднённым источникам.
"""

import pytest

from core.infra.derived_paths import (
    DERIVED_KINDS,
    derived_path,
    derived_read_path,
    legacy_derived_path,
)


def test_path_layout_is_per_user_directory():
    p = derived_path("workouts_log", 123456789)
    assert p.name == "workouts_log.json"
    assert p.parent.name == "123456789"
    assert p.parent.parent.name == "derived"
    assert p.parent.parent.parent.name == "data"


def test_all_kinds_have_paths():
    for kind in DERIVED_KINDS:
        assert derived_path(kind, 1).name == f"{kind}.json"


def test_unknown_kind_rejected():
    with pytest.raises(ValueError):
        derived_path("something_else", 1)


def test_legacy_path_is_old_container_local_location():
    p = legacy_derived_path("workouts_log", 123456789)
    assert p.name == "workouts_log_123456789.json"
    assert p.parent.name == "telegram-bot"


def test_read_prefers_new_location(tmp_path, monkeypatch):
    monkeypatch.setenv("BOTKIN_DERIVED_DIR", str(tmp_path / "derived"))
    new = derived_path("env_data", 42)
    new.parent.mkdir(parents=True, exist_ok=True)
    new.write_text("{}")
    assert derived_read_path("env_data", 42) == new


def test_read_falls_back_to_legacy_until_migration(tmp_path, monkeypatch):
    """Первый запуск после выката: нового файла ещё нет, старый может быть."""
    monkeypatch.setenv("BOTKIN_DERIVED_DIR", str(tmp_path / "derived"))
    legacy = legacy_derived_path("workouts_log", 42)
    assert not derived_path("workouts_log", 42).exists()
    expected = legacy if legacy.exists() else derived_path("workouts_log", 42)
    assert derived_read_path("workouts_log", 42) == expected


def test_write_path_creates_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("BOTKIN_DERIVED_DIR", str(tmp_path / "derived"))
    from core.infra.derived_paths import derived_write_path

    p = derived_write_path("biomarkers", 7)
    assert p.parent.is_dir()
