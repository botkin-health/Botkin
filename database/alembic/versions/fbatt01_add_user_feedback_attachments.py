"""add user_feedback.attachments (вложения фидбека из мини-аппа)

Revision ID: fbatt01
Revises: workuq01
Create Date: 2026-10-17

Nullable JSONB: список {name, mime, size, file_id?} — метаданные вложений и
Telegram file_id, полученный при пересылке файла администратору. Сами файлы в БД
не хранятся. Идемпотентно (IF NOT EXISTS).
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fbatt01"
down_revision: Union[str, None] = "workuq01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE user_feedback ADD COLUMN IF NOT EXISTS attachments JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE user_feedback DROP COLUMN IF EXISTS attachments")
