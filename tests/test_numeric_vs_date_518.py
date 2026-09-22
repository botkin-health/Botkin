"""Регрессия #518: короткий числовой ответ («7.2», «1.5», «5.5») не должен

приниматься за дату ДД.ММ регэкспом в `extract_date_from_text()` (шаг 2).

Сценарий: агент спросил «какой сегодня сахар?» / «сколько таблеток выпил?»,
пользователь ответил голым числом вроде «7.2». Регэксп `^(\\d{1,2})[./](\\d{1,2})`
(шаг 2 extract_date_from_text) трактует «7» как день, «2» как месяц → дата
2026-02-07, а `clean_text` становится пустой строкой. Дальше срабатывает
реройт #514 (`_is_lone_date_answer`) — агент получает ТОЛЬКО служебную
директиву о дате, самого числа «7.2» в тексте нет. Агент может записать
данные не за тот день и без значения — тихая порча медданных.

При этом «7.2» — ровно тот «короткий числовой ответ», который #198
(`_looks_like_short_value` + `agent_last_turn_was_question`) обязан отдать
агенту КАК ЗНАЧЕНИЕ.

Решение (см. отчёт): если всё сообщение целиком выглядит как короткое
числовое значение (`_looks_like_short_value` по ИСХОДНОМУ тексту), оно не
трактуется как дата — `extract_date_from_text()` для него не вызывается,
custom_date остаётся None, а исходный текст уходит дальше по маршруту #198.
Для неоднозначных «одиночных» дат вида ДД.ММ/ДД/ММ (например «15.09» без
остального текста) это тоже применяется — они не режутся на дату, а идут
агенту как есть, потому что агент видит контекст диалога (какой вопрос он
задавал) и может сам разобраться, число это или дата.

Второй прицеп этого же дефекта — эвристика «вечером/перед сном» (case 4 в
extract_date_from_text). Она пишет ВЧЕРАШНЮЮ дату, если сейчас утро и в
тексте есть маркер вечера, но НЕ вырезает слово (это осознанно — эвристика
написана для food-парсера, где «Я вечером выпил кефир» утром — это рассказ о
вчерашнем вечере). Но с #510 эта дата стала уходить агенту тоже — а для
агента предложение вроде «Запиши тренировку: пробежка 5 км, вечером ещё
поплаваю», написанное в 9 утра, говорит о БУДУЩЕМ вечере сегодняшнего дня,
не о вчера. Проверяем, что агент НЕ получает директиву с датой в этом случае
(парсер еды по-прежнему получает custom_date — это не трогаем).
"""

import logging
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

MSK = timezone(timedelta(hours=3))

LLM_ANALYZE = "core.llm.router.analyze_message"
ASK_AGENT = "core.agent_chat.ask_agent"
AGENT_LAST_TURN_WAS_QUESTION = "core.agent_chat.agent_last_turn_was_question"
GET_USER_TZ = "handlers.text.get_user_tz"

USER_ID = 895655


def _ago(days: int) -> str:
    return (datetime.now(MSK) - timedelta(days=days)).strftime("%Y-%m-%d")


def _tz_with_local_hour(hour: int) -> timezone:
    """Фиксированный offset-tz, в котором СЕЙЧАС локально ~hour часов."""
    utc_hour = datetime.now(timezone.utc).hour
    return timezone(timedelta(hours=(hour - utc_hour) % 24))


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


async def _run_and_capture_agent_text(text: str, tz_hour: int | None = None) -> str:
    """Прогоняет handle_text_message и возвращает текст, переданный в ask_agent."""
    from handlers.text import handle_text_message

    msg = _make_text_message(USER_ID, text)
    captured = {}

    def _fake_ask_agent(user_id, user_text, *args, **kwargs):
        captured["user_text"] = user_text
        return "ок"

    with ExitStack() as stack:
        stack.enter_context(patch(LLM_ANALYZE, return_value={"type": "other", "data": {}}))
        stack.enter_context(patch(ASK_AGENT, side_effect=_fake_ask_agent))
        stack.enter_context(patch(AGENT_LAST_TURN_WAS_QUESTION, return_value=True))
        stack.enter_context(patch("logging.FileHandler", return_value=logging.NullHandler()))
        if tz_hour is not None:
            stack.enter_context(patch(GET_USER_TZ, return_value=_tz_with_local_hour(tz_hour)))
        await handle_text_message(msg, USER_ID, MagicMock())

    assert "user_text" in captured, "ask_agent не был вызван"
    return captured["user_text"]


# ── Короткие числовые ответы не должны стать датой ───────────────────────────


@pytest.mark.asyncio
async def test_numeric_answer_72_reaches_agent_as_number_not_date():
    agent_text = await _run_and_capture_agent_text("7.2")
    assert "7.2" in agent_text, f"число потеряно: {agent_text!r}"
    assert "[Система" not in agent_text, f"вместо числа агент получил директиву о дате: {agent_text!r}"
    assert "2026-02-07" not in agent_text


@pytest.mark.asyncio
async def test_numeric_answer_15_reaches_agent_as_number_not_date():
    agent_text = await _run_and_capture_agent_text("1.5")
    assert "1.5" in agent_text
    assert "[Система" not in agent_text


@pytest.mark.asyncio
async def test_numeric_answer_55_reaches_agent_as_number_not_date():
    agent_text = await _run_and_capture_agent_text("5.5")
    assert "5.5" in agent_text
    assert "[Система" not in agent_text


# ── Регрессия #514 — словесная дата всё ещё должна доходить как дата ────────


@pytest.mark.asyncio
async def test_pozavchera_still_reaches_agent_as_explicit_date():
    agent_text = await _run_and_capture_agent_text("позавчера")
    assert _ago(2) in agent_text


# ── Регрессия #510 — дата в начале фразы всё ещё должна доходить ────────────


@pytest.mark.asyncio
async def test_dd_mm_date_with_extra_text_still_reaches_agent_as_explicit_date():
    agent_text = await _run_and_capture_agent_text("15.09 была тренировка")
    assert "2026-09-15" in agent_text or "-09-15" in agent_text
    assert "тренировка" in agent_text


# ── Эвристика "вечером" не должна уходить агенту директивой ─────────────────


@pytest.mark.asyncio
async def test_evening_heuristic_date_not_sent_to_agent_in_the_morning():
    """9 утра, фраза про вечер СЕГОДНЯШНЕГО дня — не должно уйти как "вчера"."""
    agent_text = await _run_and_capture_agent_text("Запиши тренировку: пробежка 5 км, вечером ещё поплаваю", tz_hour=9)
    assert "[Система" not in agent_text, f"агент получил ложную директиву о вчерашней дате: {agent_text!r}"
    assert _ago(1) not in agent_text
