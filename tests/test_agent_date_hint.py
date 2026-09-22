"""Регрессия #510: «вчера»/«позавчера»/дата должны доходить до агента.

`extract_date_from_text()` (handlers/text.py) вырезает из сообщения слова
«вчера» / «позавчера» / «yesterday» и даты вида ДД.ММ, возвращая дату отдельно
в `custom_date`. Раньше `custom_date` применялась только детерминированными
парсерами (еда/добавки) — если сообщение уходило в BotkinClaw (агента), тот
получал текст уже БЕЗ слова о дате и без `custom_date`, и событие ложилось на
сегодня (баг подтверждён на дев-стенде: «вчера крутил велотренажёр 40 минут» →
`log_workout` без `start_time` → запись на сегодня).

Эти тесты гоняют полный маршрут «входящее сообщение → handle_text_message →
ask_agent», а не прямой вызов `ask_agent` (именно прямой вызов маскировал
баг при диагностике #502 — см. issue #510). Проверяем, что текст, с которым
реально вызывается `ask_agent`, несёт явную дату, для всех вырезаемых форм:
«вчера», «позавчера», «yesterday», «day before yesterday», ДД.ММ, ДД/ММ.

Заодно регрессия на то, что фикс НЕ трогает детерминированные парсеры —
«позавчера принял омега-3» по-прежнему должен использовать `custom_date`
напрямую (тестами добавок/еды, не здесь) и не проходить через ask_agent.
"""

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

MSK = timezone(timedelta(hours=3))

LLM_ANALYZE = "core.llm.router.analyze_message"
ASK_AGENT = "core.agent_chat.ask_agent"

USER_ID = 895655


def _ago(days: int) -> str:
    return (datetime.now(MSK) - timedelta(days=days)).strftime("%Y-%m-%d")


def _make_text_message(user_id: int, text: str):
    msg = MagicMock()
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.text = text
    msg.photo = None
    msg.chat = MagicMock()
    msg.chat.id = user_id
    msg.answer = AsyncMock(return_value=MagicMock(message_id=778))
    msg.bot = MagicMock()
    msg.bot.edit_message_text = AsyncMock()
    return msg


@pytest.fixture(autouse=True)
def _clean_state():
    from services.state import state_manager

    state_manager.clear_state(str(USER_ID))
    yield
    state_manager.clear_state(str(USER_ID))


async def _run_and_capture_agent_text(text: str) -> str:
    """Прогоняет handle_text_message и возвращает текст, переданный в ask_agent."""
    from handlers.text import handle_text_message

    msg = _make_text_message(USER_ID, text)
    captured = {}

    def _fake_ask_agent(user_id, user_text, *args, **kwargs):
        captured["user_text"] = user_text
        return "ок"

    with (
        patch(LLM_ANALYZE, return_value={"type": "other", "data": {}}),
        patch(ASK_AGENT, side_effect=_fake_ask_agent),
        patch("logging.FileHandler", return_value=logging.NullHandler()),
    ):
        await handle_text_message(msg, USER_ID, MagicMock())

    assert "user_text" in captured, "ask_agent не был вызван"
    return captured["user_text"]


@pytest.mark.asyncio
async def test_yesterday_reaches_agent_as_explicit_date():
    agent_text = await _run_and_capture_agent_text("вчера крутил велотренажёр 40 минут, 12 км, сжёг 300 ккал")
    assert _ago(1) in agent_text
    # Слово вырезано парсером дат (как и раньше) — агент получает вместо него
    # служебную директиву с явной датой.
    assert "велотренажёр" in agent_text


@pytest.mark.asyncio
async def test_day_before_yesterday_reaches_agent_as_explicit_date():
    agent_text = await _run_and_capture_agent_text("позавчера бегал 5 км")
    assert _ago(2) in agent_text
    assert "бегал" in agent_text


@pytest.mark.asyncio
async def test_english_yesterday_reaches_agent_as_explicit_date():
    agent_text = await _run_and_capture_agent_text("yesterday did strength training")
    assert _ago(1) in agent_text
    assert "strength training" in agent_text


@pytest.mark.asyncio
async def test_english_day_before_yesterday_reaches_agent_as_explicit_date():
    agent_text = await _run_and_capture_agent_text("day before yesterday did yoga")
    assert _ago(2) in agent_text
    assert "yoga" in agent_text


@pytest.mark.asyncio
async def test_dd_mm_dot_date_reaches_agent_as_explicit_date():
    text = "15.03 была силовая тренировка"
    agent_text = await _run_and_capture_agent_text(text)
    assert "2026-03-15" in agent_text or "-03-15" in agent_text
    assert "силовая" in agent_text


@pytest.mark.asyncio
async def test_dd_mm_slash_date_reaches_agent_as_explicit_date():
    text = "15/03 была силовая тренировка"
    agent_text = await _run_and_capture_agent_text(text)
    assert "-03-15" in agent_text
    assert "силовая" in agent_text


@pytest.mark.asyncio
async def test_no_date_leaves_text_untouched():
    """Без относительной/явной даты в тексте — директива не добавляется."""
    agent_text = await _run_and_capture_agent_text("сегодня бегал 5 км")
    assert agent_text == "сегодня бегал 5 км"
    assert "[Система" not in agent_text
