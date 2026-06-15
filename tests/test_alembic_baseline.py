"""Регресс-гард Alembic baseline (#83).

Дёшево ловит две поломки, которые иначе всплыли бы только на проде/в CI-миграции:
1. случайное удаление/переименование ORM-модели (рассинхрон моделей и схемы);
2. появление второго alembic-head без явного слияния (ветвление миграций).
"""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from database.models import Base

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Полный набор ORM-таблиц (без служебной alembic_version — она не ORM-модель).
EXPECTED_TABLES = {
    "activity_log",
    "agent_conversations",
    "audit_log",
    "blood_pressure_logs",
    "blood_tests",
    "body_measurements",
    "daily_summaries",
    "llm_usage_log",
    "nutrition_log",
    "sleep_records",
    "supplements_log",
    "user_settings",
    "users",
    "weights",
    "workouts",
}

BASELINE_REVISION = "711fd5e3f1e8"


def _alembic_config() -> Config:
    """Config с абсолютными путями — не зависит от cwd при запуске pytest."""
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "database" / "alembic"))
    return cfg


def test_all_orm_tables_registered():
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_single_alembic_head_is_baseline():
    heads = ScriptDirectory.from_config(_alembic_config()).get_heads()
    assert heads == [BASELINE_REVISION]
