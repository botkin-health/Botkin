"""Регрессия #514: одиночный ответ-дата («позавчера») на вопрос агента не должен
уходить в парсер еды и получать «🤷 Не понял, что это. Это еда?».

Сценарий из issue:
1. Пользователь: «капотен и пропущенные утренние таблетки были несколько дней назад»
2. Агент (по #507) переспрашивает: «какой именно день?»
3. Пользователь отвечает ровно так, как спросили: «позавчера»
4. БАГ (до фикса): бот отвечал «Это еда?» — сообщение до агента не доходило.

Причина: `extract_date_from_text()` вырезает слово о дате; если сообщение
состояло ТОЛЬКО из него, остаётся пустая строка, которая проваливается
в парсер еды (#198 `_looks_like_short_value` не ловит словесные даты, только
короткие числа/АД).

Эти тесты гоняют полный маршрут «входящее сообщение → handle_text_message →
ask_agent/food-парсер», как и tests/test_agent_date_hint.py (#510) — именно
такие тесты на полный маршрут ловят класс багов, которые прямой вызов
ask_agent маскирует.

Покрытие:
  - одиночная дата после вопроса агента → в агента, с датой в хинте
  - одиночная дата БЕЗ предшествующего вопроса → тоже в агента (не «это еда?»)
  - все формы: «вчера», «позавчера», «yesterday», «day before yesterday»,
    «15.09», «15/09»
  - негативный случай: «Вчера ужинал овсянкой» — обычное сообщение о еде
    по-прежнему уходит в парсер еды и логируется вчерашним днём (не сломано)
"""

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

MSK = timezone(timedelta(hours=3))

LLM_ANALYZE = "core.llm.router.analyze_message"
ASK_AGENT = "core.agent_chat.ask_agent"
AGENT_LAST_TURN_WAS_QUESTION = "core.agent_chat.agent_last_turn_was_question"
PROCESS_LLM_FOOD_DATA = "core.food.nutrition.process_llm_food_data"

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


async def _run_and_capture_agent_text(text: str, agent_last_turn_was_question: bool = True) -> str:
    """Прогоняет handle_text_message и возвращает текст, переданный в ask_agent.

    Падает assert'ом, если сообщение НЕ дошло до ask_agent (значит, ушло в
    парсер еды / показало «это еда?» — именно баг #514).
    """
    from handlers.text import handle_text_message

    msg = _make_text_message(USER_ID, text)
    captured = {}

    def _fake_ask_agent(user_id, user_text, *args, **kwargs):
        captured["user_text"] = user_text
        return "ок"

    with (
        patch(LLM_ANALYZE, return_value={"type": "other", "data": {}}),
        patch(ASK_AGENT, side_effect=_fake_ask_agent),
        patch(AGENT_LAST_TURN_WAS_QUESTION, return_value=agent_last_turn_was_question),
        patch("logging.FileHandler", return_value=logging.NullHandler()),
    ):
        await handle_text_message(msg, USER_ID, MagicMock())

    assert "user_text" in captured, (
        f"ask_agent не был вызван для {text!r} — сообщение ушло в парсер еды ('это еда?'), баг #514 не починен"
    )
    return captured["user_text"]


# ── Одиночная дата ПОСЛЕ вопроса агента ──────────────────────────────────────


@pytest.mark.asyncio
async def test_lone_day_before_yesterday_after_agent_question_reaches_agent():
    """Сценарий issue #514 дословно: «позавчера» одним словом после вопроса агента."""
    agent_text = await _run_and_capture_agent_text("позавчера", agent_last_turn_was_question=True)
    assert _ago(2) in agent_text


@pytest.mark.asyncio
async def test_lone_yesterday_after_agent_question_reaches_agent():
    agent_text = await _run_and_capture_agent_text("вчера", agent_last_turn_was_question=True)
    assert _ago(1) in agent_text


@pytest.mark.asyncio
async def test_lone_english_yesterday_reaches_agent():
    agent_text = await _run_and_capture_agent_text("yesterday", agent_last_turn_was_question=True)
    assert _ago(1) in agent_text


@pytest.mark.asyncio
async def test_lone_english_day_before_yesterday_reaches_agent():
    agent_text = await _run_and_capture_agent_text("day before yesterday", agent_last_turn_was_question=True)
    assert _ago(2) in agent_text


@pytest.mark.asyncio
async def test_lone_dd_mm_dot_date_reaches_agent():
    agent_text = await _run_and_capture_agent_text("15.09", agent_last_turn_was_question=True)
    assert "-09-15" in agent_text


@pytest.mark.asyncio
async def test_lone_dd_mm_slash_date_reaches_agent():
    agent_text = await _run_and_capture_agent_text("15/09", agent_last_turn_was_question=True)
    assert "-09-15" in agent_text


# ── Одиночная дата БЕЗ предшествующего вопроса ───────────────────────────────
# Решение (см. отчёт): всё равно уходит в агента, а не в парсер еды — агент
# либо найдёт контекст в своей истории диалога, либо вежливо переспросит, о
# каком событии речь. Это лучше, чем детерминированное «это еда?».


@pytest.mark.asyncio
async def test_lone_date_without_prior_question_still_reaches_agent_not_food_parser():
    agent_text = await _run_and_capture_agent_text("позавчера", agent_last_turn_was_question=False)
    assert _ago(2) in agent_text


# ── Негативный случай: обычная еда со словом «вчера» — НЕ сломано ───────────


@pytest.mark.asyncio
async def test_ordinary_food_message_with_yesterday_still_goes_to_food_parser():
    """«Вчера ужинал овсянкой» — обычное сообщение о еде, не одинокая дата.

    Должно по-прежнему уходить в детерминированный food-парсер (не в агента)
    и логироваться вчерашним днём — это НЕ должно сломаться фиксом #514.
    """
    from handlers.text import handle_text_message
    from services.state import state_manager

    msg = _make_text_message(USER_ID, "вчера ужинал овсянкой")

    fake_router_result = {
        "type": "food",
        "data": {"items": [{"name": "Овсянка", "weight": 200}], "dish_name": "Овсянка"},
    }
    fake_meal_items = [{"name": "Овсянка", "weight": 200, "calories": 150}]
    fake_meal_totals = {"calories": 150, "protein": 5, "fats": 3, "carbs": 25}

    with (
        patch(LLM_ANALYZE, return_value=fake_router_result),
        patch(ASK_AGENT) as mock_ask_agent,
        patch(PROCESS_LLM_FOOD_DATA, return_value=(fake_meal_items, fake_meal_totals)),
        patch("logging.FileHandler", return_value=logging.NullHandler()),
    ):
        await handle_text_message(msg, USER_ID, MagicMock())

    mock_ask_agent.assert_not_called()

    saved_state = state_manager.get_state(str(USER_ID))
    assert saved_state is not None, "Еда должна была создать waiting_confirmation state"
    assert saved_state.state == "waiting_confirmation"
    assert saved_state.data.get("date") == _ago(1), (
        "Дата приёма пищи должна быть вчерашней (custom_date из extract_date_from_text)"
    )
    assert saved_state.data.get("meal_items") == fake_meal_items
