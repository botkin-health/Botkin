"""add food_interactions table (#193)

Revision ID: food0inter01
Revises: rep0health01
Create Date: 2026-06-28

Наблюдаемость пищевого pipeline: сырое сообщение пользователя, распознанный
состав, ответ бота и связь с nutrition_log + статус. Пишется в дополнение к
nutrition_log (не вместо). nutrition_log_id — без FK намеренно: аудит-след
переживает удаление/правку самой записи еды.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "food0inter01"
down_revision: Union[str, None] = "rep0health01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    json_type = postgresql.JSONB() if is_postgres else sa.JSON()

    op.create_table(
        "food_interactions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("media_path", sa.Text(), nullable=True),
        sa.Column("recognized", json_type, nullable=True),
        sa.Column("bot_reply", sa.Text(), nullable=True),
        # nutrition_log_id — без FK намеренно (аудит-след переживает удаление еды).
        sa.Column("nutrition_log_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'saved'")),
        sa.CheckConstraint("source IN ('text','photo','voice')", name="food_interactions_source_check"),
        sa.CheckConstraint("status IN ('saved','cancelled','edited')", name="food_interactions_status_check"),
    )
    op.create_index(
        "idx_food_inter_user_created",
        "food_interactions",
        ["user_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_food_inter_user_created", table_name="food_interactions")
    op.drop_table("food_interactions")
