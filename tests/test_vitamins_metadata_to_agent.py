"""vitamins/metadata и правки после ответа агента уходят в BotkinClaw (NS-1019).

Пользователь дописал уточнение к списку лекарств в диалоге с агентом, LLM-роутер
вернул vitamins/metadata, бот ответил шаблоном «Это не приём…» — агент реплику не
увидел, уточнение потерялось. Теперь metadata и правка после свежего хода агента
идут в агента; обычный приём логируется как раньше.
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

LLM_ANALYZE = "core.llm.router.analyze_message"
ASK_AGENT = "core.agent_chat.ask_agent"
LAST_QUESTION = "core.agent_chat.agent_last_turn_was_question"
LAST_FRESH = "core.agent_chat.agent_last_turn_is_fresh"
SAVE_SUPP = "core.health.supplements.save_supplements"

USER_ID = 895655
FOLLOWUP = 'Да, и утренний приём неточно — ты не указал "аспирин"! Итого 3 таблетки утром.'


def _make_text_message(text: str):
    msg = MagicMock()
    msg.from_user = MagicMock()
    msg.from_user.id = USER_ID
    msg.text = text
    msg.photo = None
    msg.chat = MagicMock()
    msg.chat.id = USER_ID
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


async def _run(text: str, router_result: dict, fresh: bool = False):
    from handlers.text import handle_text_message

    msg = _make_text_message(text)
    captured = {}

    def _fake_ask_agent(user_id, user_text, *args, **kwargs):
        captured["user_text"] = user_text
        return "ок"

    save_supp = MagicMock(return_value=True)
    with (
        patch(LLM_ANALYZE, return_value=router_result),
        patch(ASK_AGENT, side_effect=_fake_ask_agent),
        patch(LAST_QUESTION, return_value=False),
        patch(LAST_FRESH, return_value=fresh),
        patch(SAVE_SUPP, save_supp),
        patch("logging.FileHandler", return_value=logging.NullHandler()),
    ):
        await handle_text_message(msg, USER_ID, MagicMock())
    sent = [c.args[0] for c in msg.answer.await_args_list if c.args] + [
        c.kwargs.get("text", "") for c in msg.bot.edit_message_text.await_args_list
    ]
    return captured.get("user_text"), save_supp, sent


@pytest.mark.asyncio
async def test_metadata_goes_to_agent_without_template():
    agent_text, save_supp, sent = await _run(
        FOLLOWUP, {"type": "vitamins", "data": {"action": "metadata", "items": ["Аспирин"]}}
    )
    assert agent_text is not None and "аспирин" in agent_text
    save_supp.assert_not_called()
    assert not any("не приём" in s for s in sent)


@pytest.mark.asyncio
async def test_metadata_without_items_goes_to_agent_too():
    agent_text, save_supp, _ = await _run("вот мои добавки", {"type": "vitamins", "data": {"action": "metadata"}})
    assert agent_text is not None
    save_supp.assert_not_called()


@pytest.mark.asyncio
async def test_followup_after_fresh_agent_turn_goes_to_agent():
    agent_text, save_supp, _ = await _run(
        FOLLOWUP, {"type": "vitamins", "data": {"action": "logged", "items": ["Аспирин"]}}, fresh=True
    )
    assert agent_text is not None
    save_supp.assert_not_called()


@pytest.mark.asyncio
async def test_followup_without_fresh_agent_turn_not_hijacked():
    """Нет свежего хода агента — поведение прежнее (роутер решает)."""
    agent_text, save_supp, _ = await _run(
        FOLLOWUP, {"type": "vitamins", "data": {"action": "logged", "items": ["Аспирин"]}}, fresh=False
    )
    assert agent_text is None
    save_supp.assert_called_once()


@pytest.mark.asyncio
async def test_plain_intake_still_logged_even_after_fresh_agent_turn():
    agent_text, save_supp, _ = await _run(
        "выпил магний", {"type": "vitamins", "data": {"action": "logged", "items": ["Магний"]}}, fresh=True
    )
    assert agent_text is None
    save_supp.assert_called_once()


@pytest.mark.asyncio
async def test_food_followup_not_affected_by_guard():
    """Guard только для vitamins: еда с «и ещё» после хода агента не уходит в агента."""
    from handlers.text import _is_agent_followup_text

    assert not _is_agent_followup_text("и ещё банан")
    assert _is_agent_followup_text("ты не указал аспирин")
    assert _is_agent_followup_text("Да, и утренний приём неточно")
