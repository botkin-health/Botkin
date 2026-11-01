"""Единый вход (голос = текст) и режим диалога (аудит обвязки, задачи 2–3).

- В свежем разговоре с агентом реплика уходит агенту, роутер еды не зовётся.
- Явная запись («Обед: гречка 200 г») и в диалоге идёт парсером к карточке.
- Голос после расшифровки идёт тем же входом: «151/92 пульс 65» — запись АД без LLM.
- `log_meal_text` агента в чате бота даёт черновик карточки, а не запись в БД.
"""

import json
import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOT_ROOT = PROJECT_ROOT / "telegram-bot"
for p in [str(PROJECT_ROOT), str(BOT_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

LLM_ANALYZE = "core.llm.router.analyze_message"
ASK_AGENT = "core.agent_chat.ask_agent"
DIALOG = "core.agent_chat.dialog_active"
SAVE_BP = "helpers.db_save.save_bp_to_db"

USER_ID = 100301


def _msg(text: str | None):
    msg = MagicMock()
    msg.from_user = MagicMock()
    msg.from_user.id = USER_ID
    msg.text = text
    msg.photo = None
    msg.chat = MagicMock()
    msg.chat.id = USER_ID
    msg.answer = AsyncMock(return_value=MagicMock(message_id=901))
    msg.reply = AsyncMock()
    msg.bot = MagicMock()
    msg.bot.edit_message_text = AsyncMock()
    return msg


@pytest.fixture(autouse=True)
def _clean_state():
    from services.state import state_manager

    state_manager.clear_state(str(USER_ID))
    yield
    state_manager.clear_state(str(USER_ID))


async def _run(text: str, in_dialog: bool, router_result=None):
    from handlers.text import handle_text_message

    agent = MagicMock(return_value="ок")
    router = MagicMock(return_value=router_result or {"type": "other", "data": {}})
    with (
        patch(LLM_ANALYZE, router),
        patch(ASK_AGENT, agent),
        patch(DIALOG, return_value=in_dialog),
        patch("logging.FileHandler", return_value=logging.NullHandler()),
    ):
        await handle_text_message(_msg(text), USER_ID, MagicMock())
    return agent, router


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    ["у меня есть квашенная капуста", "вчера выпил пару бокалов шампанского", "54", "позавчера"],
)
async def test_dialog_reply_goes_to_agent_without_router(text):
    agent, router = await _run(text, in_dialog=True)
    router.assert_not_called()
    assert agent.call_args.args[1] == text


@pytest.mark.asyncio
async def test_explicit_log_in_dialog_goes_to_parser():
    food = {
        "type": "food",
        "data": {"dish_name": "Обед", "items": [{"name": "гречка", "weight_g": 200, "calories": 220}]},
    }
    agent, router = await _run("Обед: гречка 200 г", in_dialog=True, router_result=food)
    router.assert_called_once()
    agent.assert_not_called()


@pytest.mark.asyncio
async def test_outside_dialog_food_mention_goes_to_parser():
    _, router = await _run("у меня есть квашенная капуста", in_dialog=False)
    router.assert_called_once()


@pytest.mark.asyncio
async def test_voice_uses_text_entry_bp_fast_path():
    from handlers.voice import handle_voice_message

    msg = _msg(None)
    msg.voice = MagicMock(file_id="f", file_unique_id="u")
    bot = MagicMock()
    bot.send_chat_action = AsyncMock()
    bot.get_file = AsyncMock(return_value=MagicMock(file_path="x"))
    bot.download_file = AsyncMock()
    save_bp = MagicMock(return_value=True)
    router = MagicMock()
    with (
        patch("handlers.voice.voice_service.transcribe", AsyncMock(return_value="151/92 пульс 65")),
        patch(SAVE_BP, save_bp),
        patch(LLM_ANALYZE, router),
        patch(DIALOG, return_value=False),
        patch("logging.FileHandler", return_value=logging.NullHandler()),
    ):
        await handle_voice_message(msg, bot, USER_ID, MagicMock())
    router.assert_not_called()
    kw = save_bp.call_args.kwargs
    assert (kw["systolic"], kw["diastolic"], kw["pulse"]) == (151, 92, 65)


def test_agent_meal_text_returns_preview_not_write():
    from core.agent_chat import _preview_meal_text

    sink: list = []
    items = [{"product": "гречка", "weight": 200, "calories": 220}]
    totals = {"calories": 220, "protein": 8, "fats": 2, "carbs": 42}
    with (
        patch(LLM_ANALYZE, return_value={"type": "food", "data": {"dish_name": "Гречка"}}),
        patch("core.food.nutrition.process_llm_food_data", return_value=(items, totals)),
    ):
        out = json.loads(_preview_meal_text(USER_ID, {"text": "гречка 200 г", "slot": "lunch"}, sink))
    assert out["status"] == "preview_shown"
    assert sink[0]["meal_name"] == "Обед"
    assert sink[0]["totals"]["calories"] == 220


def test_agent_meal_text_rejects_non_food():
    from core.agent_chat import _preview_meal_text

    sink: list = []
    with patch(LLM_ANALYZE, return_value={"type": "other", "data": {}}):
        out = json.loads(_preview_meal_text(USER_ID, {"text": "как дела"}, sink))
    assert out["status"] == "rejected"
    assert sink == []


@pytest.mark.asyncio
async def test_agent_preview_renders_card_and_waits_confirmation():
    from zoneinfo import ZoneInfo

    from handlers.text import show_agent_meal_preview
    from services.state import state_manager

    msg = _msg("да, запиши")
    preview = {
        "text": "гречка 200 г",
        "date": None,
        "slot": "lunch",
        "as_plan": False,
        "meal_name": "Обед",
        "items": [{"product": "гречка", "weight": 200, "calories": 220, "protein": 8, "fats": 2, "carbs": 42}],
        "totals": {"calories": 220, "protein": 8, "fats": 2, "carbs": 42, "fiber": 0},
    }
    await show_agent_meal_preview(msg, str(USER_ID), preview, ZoneInfo("Asia/Dubai"))
    st = state_manager.get_state(str(USER_ID))
    assert st.state == "waiting_confirmation"
    assert st.data["meal_time"] == "13:00"
    assert st.data["preview_message_id"] == 901
    assert msg.answer.call_args.kwargs.get("reply_markup") is not None
