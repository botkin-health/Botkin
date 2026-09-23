"""Guard'ы веток weight/bp в handle_text_message не должны молча глотать сообщение.

Найдено в E2E на дев-стенде 23.09.2026. Агент спросил «Скажи значение — и я
запишу.» (без «?», поэтому реройт #198 не сработал), пользователь ответил
«7.2». LLM-роутер вернул type=weight. Guard ветки weight («не правдоподобный
вес → отдаём в агент») делал `msg_type = None` — но выполнение УЖЕ было внутри
выбранной ветки `elif msg_type == "weight"`, и переприсвоение переменной не
переносит его в `else` (агент). Код выходил из цепочки: ни ответа, ни ошибки,
пользователь не получал ничего.

Тот же приём стоял в ветке bp для вопросов про диапазон давления
(«в интервале 140-120/85-70, нужно ли пить таблетки?») — прецедент из
CLAUDE.md, 28.05.2026.

Тесты гоняют полный маршрут «сообщение → handle_text_message → ask_agent».
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

LLM_ANALYZE = "core.llm.router.analyze_message"
ASK_AGENT = "core.agent_chat.ask_agent"
AGENT_LAST_TURN_WAS_QUESTION = "core.agent_chat.agent_last_turn_was_question"
SAVE_WEIGHT = "helpers.db_save.save_weight_to_db"

USER_ID = 895655


def _make_text_message(user_id: int, text: str):
    msg = MagicMock()
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.text = text
    msg.photo = None
    msg.chat = MagicMock()
    msg.chat.id = user_id
    msg.answer = AsyncMock(return_value=MagicMock(message_id=779))
    msg.bot = MagicMock()
    msg.bot.edit_message_text = AsyncMock()
    return msg


@pytest.fixture(autouse=True)
def _clean_state():
    from services.state import state_manager

    state_manager.clear_state(str(USER_ID))
    yield
    state_manager.clear_state(str(USER_ID))


async def _run(text: str, router_result: dict):
    """Возвращает (текст, переданный в ask_agent или None, мок save_weight)."""
    from handlers.text import handle_text_message

    msg = _make_text_message(USER_ID, text)
    captured = {}

    def _fake_ask_agent(user_id, user_text, *args, **kwargs):
        captured["user_text"] = user_text
        return "ок"

    save_weight = MagicMock(return_value=True)
    with (
        patch(LLM_ANALYZE, return_value=router_result),
        patch(ASK_AGENT, side_effect=_fake_ask_agent),
        patch(AGENT_LAST_TURN_WAS_QUESTION, return_value=False),
        patch(SAVE_WEIGHT, save_weight),
        patch("logging.FileHandler", return_value=logging.NullHandler()),
    ):
        await handle_text_message(msg, USER_ID, MagicMock())
    return captured.get("user_text"), save_weight


@pytest.mark.asyncio
async def test_implausible_weight_reaches_agent_not_silence():
    """«7.2» → роутер сказал weight → 7.2 кг неправдоподобно → должно дойти до агента."""
    agent_text, save_weight = await _run("7.2", {"type": "weight", "data": {"weight": 7.2}})
    assert agent_text is not None, "ask_agent не вызван — сообщение молча потеряно"
    assert "7.2" in agent_text
    save_weight.assert_not_called()


@pytest.mark.asyncio
async def test_bp_range_question_reaches_agent_not_silence():
    """Вопрос про диапазон давления — прецедент 28.05.2026 — должен дойти до агента."""
    text = "Если у меня давление в интервале 140-120 /85-70, нужно ли мне пить таблетки?"
    agent_text, _ = await _run(text, {"type": "bp", "data": {"systolic": 120, "diastolic": 85}})
    assert agent_text is not None, "ask_agent не вызван — вопрос про давление молча потерян"
    assert "таблетки" in agent_text


@pytest.mark.asyncio
async def test_plausible_weight_still_saved_not_sent_to_agent():
    """Регрессия: нормальный вес по-прежнему сохраняется парсером, агент не зовётся."""
    agent_text, save_weight = await _run("74.5", {"type": "weight", "data": {"weight": 74.5}})
    save_weight.assert_called_once()
    assert agent_text is None


@pytest.mark.asyncio
async def test_bp_with_unrealistic_values_reaches_agent_not_silence():
    """Третий провал той же природы: роутер вернул bp, но цифры нереалистичны
    (или их нет) — ни `if`, ни `elif` ветки bp не срабатывали, код выходил из
    цепочки молча."""
    agent_text, _ = await _run("давление 300 на 200", {"type": "bp", "data": {"systolic": 300, "diastolic": 200}})
    assert agent_text is not None, "ask_agent не вызван — замер с нереалистичными цифрами молча потерян"
