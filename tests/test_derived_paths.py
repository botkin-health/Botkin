"""#480: производные per-user файлы живут на bind-mount, а не внутри контейнера.

`/app/telegram-bot/` — слой образа: каждый деплой пересоздаёт контейнер и стирает
оттуда workouts_log/env_data/biomarkers. До ближайшего ночного синка (окно
04–20 UTC) агент и дашборд молча деградируют к обеднённым источникам.
"""

import pytest

from core.infra import derived_paths
from core.infra.derived_paths import (
    DERIVED_KINDS,
    derived_path,
    derived_read_path,
    legacy_derived_path,
)


@pytest.fixture(autouse=True)
def _no_env_override(monkeypatch):
    """Раскладка проверяется по умолчанию, а не по BOTKIN_DERIVED_DIR из окружения."""
    monkeypatch.delenv("BOTKIN_DERIVED_DIR", raising=False)


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
    """Первый запуск после выката: канона ещё нет, старый файл читается."""
    monkeypatch.setenv("BOTKIN_DERIVED_DIR", str(tmp_path / "derived"))
    monkeypatch.setattr(derived_paths, "_REPO_ROOT", tmp_path)
    legacy = legacy_derived_path("workouts_log", 42)
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text('{"workouts": []}')

    assert derived_read_path("workouts_log", 42) == legacy


def test_canonical_wins_over_legacy_once_written(tmp_path, monkeypatch):
    monkeypatch.setenv("BOTKIN_DERIVED_DIR", str(tmp_path / "derived"))
    monkeypatch.setattr(derived_paths, "_REPO_ROOT", tmp_path)
    legacy = legacy_derived_path("workouts_log", 42)
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text('{"workouts": []}')
    canonical = derived_path("workouts_log", 42)
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text('{"workouts": [1]}')

    assert derived_read_path("workouts_log", 42) == canonical


def test_read_returns_canonical_when_nothing_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("BOTKIN_DERIVED_DIR", str(tmp_path / "derived"))
    monkeypatch.setattr(derived_paths, "_REPO_ROOT", tmp_path)

    assert derived_read_path("workouts_log", 42) == derived_path("workouts_log", 42)


def test_ensure_dir_creates_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("BOTKIN_DERIVED_DIR", str(tmp_path / "derived"))
    from core.infra.derived_paths import ensure_derived_dir

    p = ensure_derived_dir("biomarkers", 7)
    assert p.parent.is_dir()


def test_plain_path_has_no_side_effects(tmp_path, monkeypatch):
    """Резолвер пути не должен трогать ФС — эффект только у ensure_/write_."""
    monkeypatch.setenv("BOTKIN_DERIVED_DIR", str(tmp_path / "derived"))

    p = derived_path("env_data", 7)

    assert not p.parent.exists()


def test_atomic_write_leaves_no_tmp_file(tmp_path, monkeypatch):
    monkeypatch.setenv("BOTKIN_DERIVED_DIR", str(tmp_path / "derived"))
    from core.infra.derived_paths import write_derived_atomically

    p = write_derived_atomically("env_data", 7, '{"a": 1}')

    assert p.read_text() == '{"a": 1}'
    assert list(p.parent.glob("*.tmp")) == []
