"""add grip strength columns to body_measurements

Revision ID: grip0stren01
Revises: usrfb0back01
Create Date: 2026-07-04

Сила хвата (динамометрия) — маркер саркопении/функциональной силы.
Ручной ввод через бот/админку, как и остальная антропометрия в этой таблице.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "grip0stren01"
down_revision: Union[str, None] = "usrfb0back01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("body_measurements", sa.Column("grip_right_kg", sa.Float(), nullable=True))
    op.add_column("body_measurements", sa.Column("grip_left_kg", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("body_measurements", "grip_left_kg")
    op.drop_column("body_measurements", "grip_right_kg")
