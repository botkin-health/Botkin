"""add unique constraint workouts(user_id, start_time)

Revision ID: workuq01
Revises: workhr01
Create Date: 2026-09-22

Ревью #500 обнаружило схемный дрейф: на проде уже есть
`uq_workouts_user_start UNIQUE (user_id, start_time)` (подтверждено `\\d workouts`
на проде), но эта миграция никогда не попадала в репозиторий — baseline-снимок
(`711fd5e3f1e8_baseline_schema`) снят до того, как constraint добавили вручную.
Из-за рассинхрона `database/models.py` его тоже не описывал, и тестовая
SQLite-схема была беднее прод-схемы: IntegrityError, который реально бросает
Postgres при двух workouts с одинаковым (user_id, start_time), в тестах не
воспроизводился.

Идемпотентно (`DO $$ ... IF NOT EXISTS`): на проде уже есть — no-op; на
свежей БД (дев/тесты с реальным Postgres, не SQLite-фикстуры) — создаётся.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "workuq01"
down_revision: Union[str, None] = "workhr01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONSTRAINT_NAME = "uq_workouts_user_start"


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = '{_CONSTRAINT_NAME}'
            ) THEN
                ALTER TABLE workouts
                    ADD CONSTRAINT {_CONSTRAINT_NAME} UNIQUE (user_id, start_time);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = '{_CONSTRAINT_NAME}'
            ) THEN
                ALTER TABLE workouts DROP CONSTRAINT {_CONSTRAINT_NAME};
            END IF;
        END $$;
        """
    )
