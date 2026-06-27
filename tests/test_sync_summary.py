"""Регресс на баг 17.06.2026: /sync завис на «Глюкоза…», сводка не доставлялась.

Корень: бот шлёт по умолчанию parse_mode=HTML. Текст ошибки источника
(LibreLinkUp 476: «476 Client Error: <none> for url: …») попадал в сводку,
Telegram парсил `<none>` как HTML-тег → Bad Request: Unsupported start tag
«none» → и edit_text, и fallback answer падали → сводка не показывалась.

Фикс: сводка /sync — это plain text (HTML в ней не нужен), слать parse_mode=None.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOT_ROOT = PROJECT_ROOT / "telegram-bot"
for p in [str(PROJECT_ROOT), str(BOT_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

# Текст ошибки с угловыми скобками — ровно то, что отдаёт LibreLinkUp при 476.
DANGEROUS_ERR = "476 Client Error: <none> for url: https://api-eu.libreview.io/llu/auth/login"


@pytest.mark.asyncio
async def test_sync_summary_sent_as_plain_text_when_error_has_angle_brackets():
    from handlers import sync_cmd

    sync_cmd._LAST_RUN.clear()  # сбросить кулдауны

    progress_msg = AsyncMock()
    progress_msg.edit_text = AsyncMock()

    message = AsyncMock()
    message.answer = AsyncMock(return_value=progress_msg)

    command = MagicMock()
    command.args = "glucose"  # один источник, чтобы не гонять все

    with (
        patch.object(sync_cmd, "is_admin", return_value=True),
        patch.object(
            sync_cmd, "_run_script", new=AsyncMock(return_value=(sync_cmd.OUTCOME_UNAVAILABLE, DANGEROUS_ERR))
        ),
    ):
        await sync_cmd.cmd_sync(message, command, user_id=895655)

    # Сводку отрисовали редактированием прогресс-сообщения
    progress_msg.edit_text.assert_awaited_once()
    call = progress_msg.edit_text.call_args

    # Опасный текст реально попал в сводку (иначе тест бесполезен)
    summary = call.args[0]
    assert "<none>" in summary

    # Корень фикса: сводка слётся как plain text (parse_mode явно None),
    # иначе Telegram уронит её на парсинге «<none>».
    assert "parse_mode" in call.kwargs, "parse_mode должен передаваться явно"
    assert call.kwargs["parse_mode"] is None
