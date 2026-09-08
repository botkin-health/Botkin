"""Правка висящего превью текстом до подтверждения (#427).

Пока карточка "🍽️ Стрипсы с кабачком" ждёт подтверждения (state=waiting_confirmation),
пользователь может текстом уточнить состав вместо кнопок «Сохранить»/«Отмена»:
«без кускуса», «половину», «180 г». Правка обновляет meal_items/meal_totals в
state и правит УЖЕ отправленное сообщение-превью (edit_message_text), не шлёт
новую карточку — если только edit не упал (сообщение устарело/удалено).

Ветка живёт в handlers/text.py::_try_refine_pending_preview, вызывается из
handle_text_message ДО LLM-роутера. multi_meals исключён явно — там
meal_items/meal_totals не на верхнем уровне state.data.
"""

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

USER_ID = 895655

ITEMS = [
    {
        "product": "Куриные стрипсы",
        "weight_g": 150,
        "calories": 250,
        "protein": 30,
        "fats": 12,
        "carbs": 5,
        "fiber": 0,
    },
    {
        "product": "Кускус",
        "weight_g": 60,
        "calories": 215,
        "protein": 7,
        "fats": 1,
        "carbs": 45,
        "fiber": 1.3,
    },
    {
        "product": "Кабачок",
        "weight_g": 100,
        "calories": 30,
        "protein": 1,
        "fats": 1,
        "carbs": 5,
        "fiber": 1,
    },
]
TOTALS = {"calories": 495, "protein": 38, "fats": 14, "carbs": 55, "fiber": 2.3}


def _seed_state(user_id: int = USER_ID, *, multi_meals=None):
    from services.state import UserState, state_manager

    data = {
        "meal_items": ITEMS,
        "meal_totals": TOTALS,
        "meal_name": "Стрипсы с кабачком",
        "preview_message_id": 777,
        "source": "photo",
    }
    if multi_meals is not None:
        data["multi_meals"] = multi_meals
    state_manager.set_state(str(user_id), UserState(user_id=str(user_id), state="waiting_confirmation", data=data))


def _make_text_message(user_id: int, text: str, *, edit_side_effect=None):
    msg = MagicMock()
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.text = text
    msg.photo = None
    msg.chat = MagicMock()
    msg.chat.id = user_id
    msg.answer = AsyncMock(return_value=MagicMock(message_id=778))
    msg.bot = MagicMock()
    if edit_side_effect is not None:
        msg.bot.edit_message_text = AsyncMock(side_effect=edit_side_effect)
    else:
        msg.bot.edit_message_text = AsyncMock()
    return msg


@pytest.fixture(autouse=True)
def _clean_state():
    from services.state import state_manager

    state_manager.clear_state(str(USER_ID))
    yield
    state_manager.clear_state(str(USER_ID))


@pytest.mark.asyncio
async def test_exclude_removes_item_and_edits_existing_message():
    from handlers.text import handle_text_message
    from services.state import state_manager

    _seed_state()
    msg = _make_text_message(USER_ID, "без кускуса")

    with (
        patch(LLM_ANALYZE) as mock_analyze,
        patch(ASK_AGENT),
        patch("logging.FileHandler", return_value=logging.NullHandler()),
    ):
        await handle_text_message(msg, USER_ID, MagicMock())

    mock_analyze.assert_not_called()

    state = state_manager.get_state(str(USER_ID))
    assert len(state.data["meal_items"]) == 2
    assert all(it["product"] != "Кускус" for it in state.data["meal_items"])
    assert state.data["meal_totals"]["calories"] == pytest.approx(280, abs=0.5)

    msg.bot.edit_message_text.assert_called_once()
    _, kwargs = msg.bot.edit_message_text.call_args
    assert kwargs["message_id"] == 777
    assert "− Кускус" in kwargs["text"]
    assert "Итого: 280" in kwargs["text"]
    assert len(kwargs["reply_markup"].inline_keyboard[0]) == 2 or (
        sum(len(row) for row in kwargs["reply_markup"].inline_keyboard) == 2
    )


@pytest.mark.asyncio
async def test_fraction_halves_all_weights_and_totals():
    from handlers.text import handle_text_message
    from services.state import state_manager

    _seed_state()
    msg = _make_text_message(USER_ID, "половину")

    with (
        patch(LLM_ANALYZE) as mock_analyze,
        patch(ASK_AGENT),
        patch("logging.FileHandler", return_value=logging.NullHandler()),
    ):
        await handle_text_message(msg, USER_ID, MagicMock())

    mock_analyze.assert_not_called()

    state = state_manager.get_state(str(USER_ID))
    couscous = next(it for it in state.data["meal_items"] if it["product"] == "Кускус")
    assert couscous["weight_g"] == pytest.approx(30, abs=0.5)
    assert state.data["meal_totals"]["calories"] == pytest.approx(247.5, abs=0.5)


@pytest.mark.asyncio
async def test_unmatched_exclusion_leaves_state_untouched():
    from handlers.text import handle_text_message
    from services.state import state_manager

    _seed_state()
    msg = _make_text_message(USER_ID, "без соуса")

    with (
        patch(LLM_ANALYZE) as mock_analyze,
        patch(ASK_AGENT),
        patch("logging.FileHandler", return_value=logging.NullHandler()),
    ):
        await handle_text_message(msg, USER_ID, MagicMock())

    mock_analyze.assert_not_called()

    state = state_manager.get_state(str(USER_ID))
    assert len(state.data["meal_items"]) == 3
    assert state.data["meal_totals"]["calories"] == 495

    msg.answer.assert_called_once()
    args, _ = msg.answer.call_args
    assert "Не нашёл «соуса»" in args[0]
    assert "Кускус" in args[0]
    msg.bot.edit_message_text.assert_not_called()


@pytest.mark.asyncio
async def test_edit_failure_falls_back_to_new_message_and_updates_id():
    from handlers.text import handle_text_message
    from services.state import state_manager

    _seed_state()
    msg = _make_text_message(USER_ID, "без кускуса", edit_side_effect=Exception("message to edit not found"))

    with (
        patch(LLM_ANALYZE) as mock_analyze,
        patch(ASK_AGENT),
        patch("logging.FileHandler", return_value=logging.NullHandler()),
    ):
        await handle_text_message(msg, USER_ID, MagicMock())

    mock_analyze.assert_not_called()
    msg.answer.assert_called_once()

    state = state_manager.get_state(str(USER_ID))
    assert state.data["preview_message_id"] == 778


@pytest.mark.asyncio
async def test_non_modifier_text_falls_through_to_normal_flow():
    from handlers.text import handle_text_message

    _seed_state()
    msg = _make_text_message(USER_ID, "завтрак: овсянка")

    with (
        patch(LLM_ANALYZE, return_value={"type": "other", "data": {}}) as mock_analyze,
        patch(ASK_AGENT, MagicMock(return_value="ок")),
        patch("logging.FileHandler", return_value=logging.NullHandler()),
    ):
        await handle_text_message(msg, USER_ID, MagicMock())

    mock_analyze.assert_called()


@pytest.mark.asyncio
async def test_multi_meals_pending_skips_refine_branch():
    from handlers.text import handle_text_message

    _seed_state(multi_meals=[{"meal_items": ITEMS, "meal_totals": TOTALS, "meal_name": "Завтрак"}])
    msg = _make_text_message(USER_ID, "без кускуса")

    with (
        patch(LLM_ANALYZE, return_value={"type": "other", "data": {}}) as mock_analyze,
        patch(ASK_AGENT, MagicMock(return_value="ок")),
        patch("logging.FileHandler", return_value=logging.NullHandler()),
    ):
        await handle_text_message(msg, USER_ID, MagicMock())

    mock_analyze.assert_called()
