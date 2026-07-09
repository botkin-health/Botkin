"""Tests for команда /doctor_report (#291).

Вторичный путь доставки PDF-отчёта врачу. Проверяет, что хендлер зовёт общий
helper и отвечает успехом/ошибкой в зависимости от результата доставки.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))


def _texts(answer_mock) -> list[str]:
    return [c.args[0] for c in answer_mock.call_args_list if c.args]


@pytest.mark.asyncio
async def test_cmd_doctor_report_success(monkeypatch):
    """Успешная доставка → «готовлю…» + подтверждение, helper вызван с user_id."""
    import database
    from handlers.commands import cmd_doctor_report
    from services import doctor_report

    seen = {}
    monkeypatch.setattr(database, "SessionLocal", lambda: MagicMock())
    monkeypatch.setattr(
        doctor_report,
        "send_doctor_report_to_chat",
        lambda db, uid: seen.update(uid=uid) or {"status": "ok", "sent": True},
    )

    msg = MagicMock()
    msg.answer = AsyncMock()
    await cmd_doctor_report(msg, user_id=895655)

    texts = _texts(msg.answer)
    assert any("Готовлю" in t for t in texts)
    assert any("отправлен" in t for t in texts)
    assert seen["uid"] == 895655


@pytest.mark.asyncio
async def test_cmd_doctor_report_failure(monkeypatch):
    """Сбой доставки → сообщение об ошибке."""
    import database
    from handlers.commands import cmd_doctor_report
    from services import doctor_report

    monkeypatch.setattr(database, "SessionLocal", lambda: MagicMock())
    monkeypatch.setattr(
        doctor_report,
        "send_doctor_report_to_chat",
        lambda db, uid: {"status": "error", "error": "render-failed", "sent": False},
    )

    msg = MagicMock()
    msg.answer = AsyncMock()
    await cmd_doctor_report(msg, user_id=895655)

    texts = _texts(msg.answer)
    assert any("Не удалось" in t for t in texts)
