"""personal_access_tokens: хранить sha256-хэш PAT вместо открытого текста

Revision ID: pathash01
Revises: fbatt01
Create Date: 2026-11-06

До этой ревизии колонка `token` хранила PAT (`pat_<telegram_id>_<hex64>`) открытым
текстом: утечка дампа БД = компрометация всех MCP-токенов пользователей.

Теперь:
  • `token_hash`   — sha256(token) hex, уникальный индекс (по нему exchange ищет строку);
  • `token_prefix` — видимое начало `pat_<id>_<hex6>` для /my_connections;
  • `token` удалена.

Секрет 256-битный, поэтому соль/bcrypt не нужны (перебор бессмыслен), а поиск по
индексу сохраняется. Хэш существующих строк считаем в Python тем же способом, что
`database.crud.hash_pat` (sha256 от UTF-8) — выпущенные токены продолжают работать
без перевыпуска. Перед удалением `token` миграция сверяет каждую строку и падает,
если хоть один хэш не совпал (транзакция откатится, открытый текст останется).

Гранты hv_app — табличные (pat0token01), новые колонки покрываются ими автоматически.

downgrade: открытый текст восстановить нельзя. Возвращаем колонку `token` с
заглушкой `unrecoverable_<id>` и отзываем все токены (`revoked_at = now()`) —
схема совместима со старым кодом, пользователи перевыпускают токен через /connect_mcp.
"""

import hashlib
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "pathash01"
down_revision: Union[str, None] = "fbatt01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PREFIX_RE = re.compile(r"^(.*_)([0-9a-f]+)$")


def _hash(token: str) -> str:
    # Должно совпадать с database.crud.hash_pat — не импортируем код приложения в миграцию.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _prefix(token: str) -> str:
    # Должно совпадать с database.crud.pat_display_prefix.
    m = _PREFIX_RE.match(token)
    return f"{m.group(1)}{m.group(2)[:6]}" if m else token[:12]


def upgrade() -> None:
    op.add_column("personal_access_tokens", sa.Column("token_hash", sa.String(length=64), nullable=True))
    op.add_column("personal_access_tokens", sa.Column("token_prefix", sa.String(length=32), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, token FROM personal_access_tokens")).fetchall()
    for row_id, token in rows:
        bind.execute(
            sa.text("UPDATE personal_access_tokens SET token_hash = :h, token_prefix = :p WHERE id = :id"),
            {"h": _hash(token), "p": _prefix(token), "id": row_id},
        )

    # Самопроверка до удаления открытого текста.
    mismatched = [
        row_id
        for row_id, token, token_hash in bind.execute(
            sa.text("SELECT id, token, token_hash FROM personal_access_tokens")
        ).fetchall()
        if token_hash != _hash(token)
    ]
    if mismatched:
        raise RuntimeError(f"pathash01: token_hash не совпал для id={mismatched} — миграция остановлена")

    op.alter_column("personal_access_tokens", "token_hash", nullable=False)
    op.alter_column("personal_access_tokens", "token_prefix", nullable=False)
    op.create_index("ix_personal_access_tokens_token_hash", "personal_access_tokens", ["token_hash"], unique=True)

    op.drop_index("ix_personal_access_tokens_token", table_name="personal_access_tokens")
    op.drop_column("personal_access_tokens", "token")


def downgrade() -> None:
    op.add_column("personal_access_tokens", sa.Column("token", sa.String(length=128), nullable=True))
    op.execute(
        """
        UPDATE personal_access_tokens
           SET token = 'unrecoverable_' || id::text,
               revoked_at = COALESCE(revoked_at, now())
        """
    )
    op.alter_column("personal_access_tokens", "token", nullable=False)
    op.create_index("ix_personal_access_tokens_token", "personal_access_tokens", ["token"], unique=True)

    op.drop_index("ix_personal_access_tokens_token_hash", table_name="personal_access_tokens")
    op.drop_column("personal_access_tokens", "token_prefix")
    op.drop_column("personal_access_tokens", "token_hash")
