"""funnel_events: hv_app видит и пишет только свои события (ADR-0014).

rls02 дал hv_app на funnel_events только INSERT. Но ORM вставляет строку с
``RETURNING id``, а Postgres требует, чтобы возвращаемая строка проходила и
SELECT-политику — без неё любой ``log_event`` под hv_app падал с
«new row violates row-level security policy» (найдено e2e на деве 11.11.2026:
сохранение первой еды → first_food_logged). Свои события пользователю видеть
не страшно; чужие и сводная воронка — по-прежнему только через hv_system.

Revision ID: rls03
Revises: rls02
"""

from typing import Sequence, Union

from alembic import op

revision: str = "rls03"
down_revision: Union[str, None] = "rls02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _pg() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def _table_exists(name: str) -> bool:
    return bool(op.get_bind().exec_driver_sql(f"SELECT to_regclass('public.{name}') IS NOT NULL").scalar())


def upgrade() -> None:
    if not _pg() or not _table_exists("funnel_events"):
        return
    op.execute(
        """
        DROP POLICY IF EXISTS funnel_insert_own ON funnel_events;
        DROP POLICY IF EXISTS funnel_own_rows ON funnel_events;
        CREATE POLICY funnel_own_rows ON funnel_events FOR ALL TO hv_app
            USING (user_id = public.app_current_user_id())
            WITH CHECK (user_id = public.app_current_user_id());
        """
    )


def downgrade() -> None:
    if not _pg() or not _table_exists("funnel_events"):
        return
    op.execute(
        """
        DROP POLICY IF EXISTS funnel_own_rows ON funnel_events;
        CREATE POLICY funnel_insert_own ON funnel_events FOR INSERT TO hv_app
            WITH CHECK (user_id = public.app_current_user_id());
        """
    )
