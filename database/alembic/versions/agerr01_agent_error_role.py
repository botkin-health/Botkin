"""agent_conversations.role += 'error' — фиксируем несостоявшиеся ходы агента

Revision ID: agerr01
Revises: nlplan01
Create Date: 2026-09-22

Прецедент 24–25.08.2026: пользователь написал боту семь сообщений подряд и не
получил ни одного ответа — ~27 часов тишины, закончившейся репликой «Похоже
Botkin насовсем помер...». Разбираться пришлось месяц спустя, потому что в
данных сбой выглядит как его отсутствие: реплики пользователя в
`agent_conversations` есть (ask_agent коммитит их до вызова модели), а
ответов нет — и «не смог ответить» неотличимо от «не отвечал, потому что
никто не спрашивал».

Обработчики ошибок в хендлерах есть (529/503/429/generic), но они живут в
процессе: если процесс умер или задачу отменили раньше, чем цикл ретраев
завершился, ветка `except` не выполнится никогда, и в базе не останется
ничего. Отдельная роль делает такой ход видимым: и человеку при разборе, и
сторожу `scripts/server/check_stalled_turns.py`.

CHECK расширяется, не сужается — миграция обратно совместима: старые строки
все проходят новый предикат.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "agerr01"
down_revision: Union[str, None] = "nlplan01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OLD_ROLES = "'user', 'assistant', 'tool_use', 'tool_result'"
_NEW_ROLES = _OLD_ROLES + ", 'error'"


def upgrade() -> None:
    op.execute("ALTER TABLE agent_conversations DROP CONSTRAINT IF EXISTS agent_conversations_role_check")
    op.execute(
        "ALTER TABLE agent_conversations ADD CONSTRAINT agent_conversations_role_check "
        f"CHECK (role = ANY (ARRAY[{_NEW_ROLES}]))"
    )


def downgrade() -> None:
    # Строки с новой ролью пришлось бы удалить, иначе старый CHECK не наложится.
    op.execute("DELETE FROM agent_conversations WHERE role = 'error'")
    op.execute("ALTER TABLE agent_conversations DROP CONSTRAINT IF EXISTS agent_conversations_role_check")
    op.execute(
        "ALTER TABLE agent_conversations ADD CONSTRAINT agent_conversations_role_check "
        f"CHECK (role = ANY (ARRAY[{_OLD_ROLES}]))"
    )
