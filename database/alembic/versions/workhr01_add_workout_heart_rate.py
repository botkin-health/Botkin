"""add workouts.avg_heart_rate / workouts.max_heart_rate

Revision ID: workhr01
Revises: agerr01
Create Date: 2026-09-22

Нужны для agent tool `POST /api/agent/log_workout` (#500): family-пользователь
без wearable-интеграции (Huawei Health, интеграции нет) просил залогировать
велотренажёр включая пульс. Таблица `workouts` раньше несла только
type/duration/distance/calories — пульс негде было хранить.

Обратно совместимо: новые колонки nullable, старые писатели (HAE-канал,
Garmin-импорт) их не трогают.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "workhr01"
down_revision: Union[str, None] = "agerr01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("workouts", sa.Column("avg_heart_rate", sa.SmallInteger(), nullable=True))
    op.add_column("workouts", sa.Column("max_heart_rate", sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("workouts", "max_heart_rate")
    op.drop_column("workouts", "avg_heart_rate")
