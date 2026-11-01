"""Роутер получает [NOW] и возвращает data.date / data.time (аудит обвязки, задача 4)."""

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
for p in [str(PROJECT_ROOT), str(PROJECT_ROOT / "telegram-bot")]:
    if p not in sys.path:
        sys.path.insert(0, p)

USER_ID = 100401
TZ = ZoneInfo("Europe/Moscow")


def test_now_line_format():
    from core.llm.router import with_now_line

    out = with_now_line("ел творог", datetime(2026, 11, 1, 0, 40, tzinfo=TZ))
    assert out.startswith("[NOW: 2026-11-01 вс 00:40 local]\n")
    assert out.endswith("ел творог")
    assert with_now_line("x", None) == "x"


def test_food_model_keeps_clean_when_and_drops_garbage():
    from core.llm.models import parse_llm_response

    ok = parse_llm_response({"type": "food", "data": {"items": [], "date": "2026-10-31", "time": "23:00"}})
    assert (ok["data"]["date"], ok["data"]["time"]) == ("2026-10-31", "23:00")
    bad = parse_llm_response({"type": "food", "data": {"items": [], "date": "вчера", "time": "25:99"}})
    assert (bad["data"]["date"], bad["data"]["time"]) == (None, None)


def test_router_when_rejects_today_and_future():
    from handlers.text import _router_when

    today = datetime.now(TZ).date()
    y = (today - timedelta(days=1)).isoformat()
    assert _router_when({"date": y, "time": "23:00"}, TZ) == (y, "23:00")
    assert _router_when({"date": today.isoformat()}, TZ) == (None, None)
    assert _router_when({"date": (today + timedelta(days=2)).isoformat()}, TZ) == (None, None)


@pytest.mark.asyncio
async def test_router_date_and_time_land_in_preview():
    """«ел в 23:00 творог 200 г» после полуночи: дата и время — от роутера."""
    from handlers.text import handle_text_message
    from services.state import state_manager

    state_manager.clear_state(str(USER_ID))
    yesterday = (datetime.now(TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
    food = {
        "type": "food",
        "data": {
            "dish_name": "Творог",
            "items": [{"name": "Творог 5%", "weight": 200, "calories": 242, "protein": 34, "fats": 10, "carbs": 6}],
            "total_nutrition": {"calories": 242, "protein": 34, "fats": 10, "carbs": 6, "fiber": 0},
            "date": yesterday,
            "time": "23:00",
        },
    }
    msg = MagicMock()
    msg.from_user = MagicMock(id=USER_ID)
    msg.text = "творог 200 г, ел поздно"
    msg.photo = None
    msg.answer = AsyncMock(return_value=MagicMock(message_id=1))
    router = MagicMock(return_value=food)
    with (
        patch("core.llm.router.analyze_message", router),
        patch("core.agent_chat.dialog_active", return_value=False),
        patch("logging.FileHandler", return_value=logging.NullHandler()),
    ):
        await handle_text_message(msg, USER_ID, MagicMock())
    assert router.call_args.kwargs["now_local"] is not None
    st = state_manager.get_state(str(USER_ID))
    assert st.state == "waiting_confirmation"
    assert st.data["date"] == yesterday
    assert st.data["meal_time"] == "23:00"
    state_manager.clear_state(str(USER_ID))
