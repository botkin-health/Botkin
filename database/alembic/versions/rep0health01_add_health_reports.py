"""add health_reports table (#203)

Revision ID: rep0health01
Revises: cgm0glucose01
Create Date: 2026-06-24

Таблица для хранения HTML-отчётов пользователей.
Каждый пользователь имеет один текущий отчёт (UPSERT).
Доступен по публичному токену GET /r/{token} без авторизации.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "rep0health01"
down_revision: Union[str, None] = "cgm0glucose01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    op.create_table(
        "health_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.telegram_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token", sa.Text(), nullable=False, unique=True),
        sa.Column("html", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_health_reports_user_id", "health_reports", ["user_id"])
    op.create_index("ix_health_reports_token", "health_reports", ["token"], unique=True)


def downgrade() -> None:
    op.drop_table("health_reports")
