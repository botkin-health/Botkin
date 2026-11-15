"""add nutrition_day_status (полнота дня питания для адаптивного TDEE)

Revision ID: ndstat01
Revises: rls03
Create Date: 2026-11-15

Частично внесённые дни (забыл ресторан, пиво) занижают средний рацион в
адаптивном TDEE, а с ним и дневную цель на недели вперёд: пользователь ест как
обычно, а бот показывает «перебор». Утренний вопрос «вчера всё внёс?» пишет
сюда ответ; неполные дни исключаются из расчёта.

RLS — как в rls02/rls03 (postgres-only): строго свои строки.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ndstat01"
down_revision: Union[str, None] = "rls03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _pg() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "nutrition_day_status",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.telegram_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "date"),
    )
    if not _pg():
        return
    op.execute(
        """
        GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE nutrition_day_status TO hv_app;
        ALTER TABLE nutrition_day_status ENABLE ROW LEVEL SECURITY;
        CREATE POLICY user_isolation ON nutrition_day_status FOR ALL TO hv_app
            USING (user_id = public.app_current_user_id())
            WITH CHECK (user_id = public.app_current_user_id());
        """
    )


def downgrade() -> None:
    if _pg():
        op.execute("DROP POLICY IF EXISTS user_isolation ON nutrition_day_status;")
    op.drop_table("nutrition_day_status")
