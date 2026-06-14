from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Корень проекта в sys.path, чтобы пакет `database` импортировался при запуске alembic.
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from database.models import Base  # noqa: E402

# MetaData моделей для autogenerate.
target_metadata = Base.metadata

# DATABASE_URL из окружения — единый источник истины; alembic.ini URL не хранит.
_db_url = os.getenv("DATABASE_URL")
if not _db_url:
    raise RuntimeError("DATABASE_URL не задана — нужна для запуска миграций alembic.")
config.set_main_option("sqlalchemy.url", _db_url)

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def _compare_server_default(
    context, inspected_column, metadata_column, inspected_default, metadata_default, rendered_metadata_default
):
    """Хук autogenerate: гасит ложный дифф по no-op-дефолту users.smoking_status.

    На проде колонка имеет формальный `DEFAULT NULL::character varying` (no-op — NULL и так
    дефолт). В ORM мы его НЕ объявляем, иначе ломается create_all на SQLite в тестах.
    Возвращаем False («дефолты совпадают»), чтобы alembic check оставался пустым.
    Для всех остальных колонок отдаём None — alembic решает сам (поведение по умолчанию).
    """
    table = getattr(metadata_column.table, "name", None)
    if table == "users" and metadata_column.name == "smoking_status":
        return False
    return None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=_compare_server_default,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
