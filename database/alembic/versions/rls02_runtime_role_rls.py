"""RLS как второй рубеж: hv_system, политики на всех таблицах с владельцем (ADR-0013)

Revision ID: rls02
Revises: pathash01
Create Date: 2026-11-09

Что делает (только postgres — sqlite-тесты гоняют create_all):

* функция ``app_current_user_id()`` — единое чтение ``app.user_id``;
* роль ``hv_system`` (NOLOGIN, BYPASSRLS, не superuser) + DML-гранты — для
  явных межпользовательских путей (планировщик, админка, bootstrap по токену);
* ``hv_app``: явно NOSUPERUSER NOBYPASSRLS, DML на все таблицы (в т.ч. users —
  бот регистрирует пользователей);
* RLS + политика ``user_isolation`` для hv_app на ВСЕХ таблицах с владельцем,
  строго ``владелец = app_current_user_id()``; пустой контекст = ноль строк;
* политика ``agent_conversations_self`` (пустой контекст = видно всё, роль
  public) заменена на строгую.

Пароли ролей и LOGIN — НЕ здесь: ``scripts/ops/db_roles.sh`` на стенде.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "rls02"
down_revision: Union[str, None] = "pathash01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# таблица → колонка владельца
OWNED_TABLES: dict[str, str] = {
    "activity_log": "user_id",
    "agent_conversations": "user_id",
    "blood_pressure_logs": "user_id",
    "blood_tests": "user_id",
    "body_measurements": "user_id",
    "cgm_connections": "telegram_id",
    "cgm_followers": "owner_user_id",
    "daily_summaries": "user_id",
    "ecg_records": "user_id",
    "food_interactions": "user_id",
    "glucose_readings": "user_id",
    "health_reports": "user_id",
    "heart_rate_events": "user_id",
    "llm_usage_log": "user_id",
    "nutrition_log": "user_id",
    "personal_access_tokens": "user_id",
    "sleep_records": "user_id",
    "supplements_log": "user_id",
    "user_feedback": "user_id",
    "user_products": "user_id",
    "user_settings": "user_id",
    "users": "telegram_id",
    "weights": "user_id",
    "workouts": "user_id",
}

# Таблицы, у которых RLS был ДО этой ревизии (для downgrade).
_RLS_BEFORE = {
    "activity_log",
    "agent_conversations",
    "audit_log",
    "blood_pressure_logs",
    "cgm_connections",
    "cgm_followers",
    "ecg_records",
    "funnel_events",
    "glucose_readings",
    "heart_rate_events",
    "nutrition_log",
    "supplements_log",
    "user_settings",
    "verified_products",
    "weights",
}

_OLD_POLICY = "(({col} = (NULLIF(current_setting('app.user_id'::text, true), ''::text))::bigint))"


def _pg() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _table_exists(name: str) -> bool:
    return bool(op.get_bind().exec_driver_sql(f"SELECT to_regclass('public.{name}') IS NOT NULL").scalar())


def upgrade() -> None:
    if not _pg():
        return

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.app_current_user_id() RETURNS bigint
            LANGUAGE sql STABLE PARALLEL SAFE
            AS $$ SELECT NULLIF(current_setting('app.user_id', true), '')::bigint $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hv_app') THEN
                CREATE ROLE hv_app LOGIN;
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hv_system') THEN
                CREATE ROLE hv_system NOLOGIN;
            END IF;
        END
        $$;
        ALTER ROLE hv_app NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION;
        ALTER ROLE hv_system NOSUPERUSER BYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION;
        """
    )

    for role in ("hv_app", "hv_system"):
        op.execute(
            f"""
            GRANT USAGE ON SCHEMA public TO {role};
            GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role};
            GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role};
            GRANT EXECUTE ON FUNCTION public.app_current_user_id() TO {role};
            ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role};
            ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {role};
            """
        )
    # Миграции и служебная таблица — не дело рантайма.
    op.execute("REVOKE ALL ON TABLE alembic_version FROM hv_app, hv_system")

    op.execute("DROP POLICY IF EXISTS agent_conversations_self ON agent_conversations")

    for table, col in OWNED_TABLES.items():
        if not _table_exists(table):
            continue
        op.execute(
            f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            DROP POLICY IF EXISTS user_isolation ON {table};
            CREATE POLICY user_isolation ON {table} FOR ALL TO hv_app
                USING ({col} = public.app_current_user_id())
                WITH CHECK ({col} = public.app_current_user_id());
            """
        )

    # funnel_events: hv_app только ПИШЕТ свои события (log_event в сессии
    # пользователя), читать воронку — админке через hv_system.
    if _table_exists("funnel_events"):
        op.execute(
            """
            DROP POLICY IF EXISTS funnel_admin_only ON funnel_events;
            DROP POLICY IF EXISTS funnel_insert_own ON funnel_events;
            CREATE POLICY funnel_insert_own ON funnel_events FOR INSERT TO hv_app
                WITH CHECK (user_id = public.app_current_user_id());
            """
        )


def downgrade() -> None:
    if _pg() and _table_exists("funnel_events"):
        op.execute(
            """
            DROP POLICY IF EXISTS funnel_insert_own ON funnel_events;
            CREATE POLICY funnel_admin_only ON funnel_events FOR ALL TO hv_app USING (false);
            """
        )
    if not _pg():
        return

    for table, col in OWNED_TABLES.items():
        if not _table_exists(table):
            continue
        op.execute(f"DROP POLICY IF EXISTS user_isolation ON {table}")
        if table == "agent_conversations":
            continue
        if table in _RLS_BEFORE:
            op.execute(f"CREATE POLICY user_isolation ON {table} TO hv_app USING {_OLD_POLICY.format(col=col)}")
        else:
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.execute(
        """
        CREATE POLICY agent_conversations_self ON public.agent_conversations
            USING (((current_setting('app.user_id'::text, true) = ''::text)
                    OR ((current_setting('app.user_id'::text, true))::bigint = user_id)));
        """
    )

    op.execute(
        """
        DROP FUNCTION IF EXISTS public.app_current_user_id();
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM hv_system;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE USAGE, SELECT ON SEQUENCES FROM hv_system;
        REVOKE ALL ON ALL TABLES IN SCHEMA public FROM hv_system;
        REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM hv_system;
        REVOKE ALL ON SCHEMA public FROM hv_system;
        DROP ROLE IF EXISTS hv_system;
        REVOKE INSERT, UPDATE, DELETE ON TABLE users FROM hv_app;
        """
    )
