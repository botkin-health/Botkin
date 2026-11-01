"""Тихая порча данных в быстрых путях (аудит обвязки, ноябрь 2026, задача 1).

- «вчера 150/95 пульс 70» записывался на сегодня: regex-путь АД игнорировал дату.
- «вчера вес 82.5» — то же в ветке weight.
- голосовое «вес 82,5» (handle_description) отвечало «✅ Записано», ничего не сохраняя.
- «забыл выпить омегу» записывался как приём подстрочной проверкой без LLM.
- при падении роутера добавки угадывались по подстроке.

LLM не зовём: analyze_message и ask_agent замоканы.
"""

import logging
import sys
from datetime import datetime, timedelta
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
SAVE_BP = "helpers.db_save.save_bp_to_db"
SAVE_WEIGHT = "helpers.db_save.save_weight_to_db"
SAVE_SUPPS = "core.health.supplements.save_supplements"


def _msg(user_id: int, text: str):
    msg = MagicMock()
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.text = text
    msg.photo = None
    msg.answer = AsyncMock(return_value=MagicMock())
    msg.bot = AsyncMock()
    return msg


def _yesterday(user_id: int) -> str:
    from core.infra.tz import now_in_user_tz

    return (now_in_user_tz(user_id) - timedelta(days=1)).strftime("%Y-%m-%d")


async def _run_text(user_id: int, text: str, router_result, **mocks):
    from handlers.text import handle_text_message
    from services.state import state_manager

    state_manager.clear_state(str(user_id))
    patches = [
        patch(LLM_ANALYZE, return_value=router_result),
        patch(ASK_AGENT, mocks.pop("ask_agent", MagicMock(return_value="ок"))),
        patch("logging.FileHandler", return_value=logging.NullHandler()),
    ] + [patch(target, mock) for target, mock in mocks.items()]
    for p_ in patches:
        p_.start()
    try:
        await handle_text_message(_msg(user_id, text), user_id, MagicMock())
    finally:
        for p_ in patches:
            p_.stop()


@pytest.mark.asyncio
async def test_bp_regex_yesterday_saved_on_yesterday():
    uid = 100201
    save_bp = MagicMock(return_value=True)
    await _run_text(uid, "вчера 150/95 пульс 70", None, **{SAVE_BP: save_bp})
    assert save_bp.call_count == 1
    kw = save_bp.call_args.kwargs
    assert (kw["systolic"], kw["diastolic"], kw["pulse"]) == (150, 95, 70)
    assert kw["measured_at"].strftime("%Y-%m-%d") == _yesterday(uid)


@pytest.mark.asyncio
async def test_bp_regex_today_keeps_now():
    uid = 100202
    save_bp = MagicMock(return_value=True)
    await _run_text(uid, "130/85 пульс 62", None, **{SAVE_BP: save_bp})
    assert save_bp.call_args.kwargs["measured_at"] is None  # save_bp_to_db сам возьмёт «сейчас»


@pytest.mark.asyncio
async def test_weight_text_yesterday_saved_on_yesterday():
    uid = 100203
    save_w = MagicMock(return_value="ok")
    await _run_text(uid, "вчера вес 82.5", {"type": "weight", "data": {"weight": 82.5}}, **{SAVE_WEIGHT: save_w})
    data = save_w.call_args.args[0]
    assert data["weight"] == 82.5
    assert data["date"].startswith(_yesterday(uid))


@pytest.mark.asyncio
async def test_forgot_supplement_not_logged_as_intake():
    uid = 100204
    save_s = MagicMock(return_value=True)
    agent = MagicMock(return_value="Ничего страшного, выпей сегодня.")
    router = {"type": "vitamins", "data": {"items": ["Омега 3"], "action": "metadata"}}
    await _run_text(uid, "забыл выпить омегу", router, ask_agent=agent, **{SAVE_SUPPS: save_s})
    save_s.assert_not_called()
    assert agent.called


@pytest.mark.asyncio
async def test_router_failure_goes_to_agent_not_substring_guess():
    uid = 100205
    save_s = MagicMock(return_value=True)
    agent = MagicMock(return_value="Понял.")
    await _run_text(uid, "кончился магний", None, ask_agent=agent, **{SAVE_SUPPS: save_s})
    save_s.assert_not_called()
    assert agent.called


@pytest.mark.asyncio
async def test_voice_weight_in_description_is_saved():
    """Голос идёт в handle_description: ветка weight раньше только отвечала."""
    from handlers.photo import handle_description
    from services.state import state_manager
    from services.state_helpers import create_photo_state

    uid = 100206
    state_manager.clear_state(str(uid))
    state_manager.set_state(
        str(uid), create_photo_state(user_id=str(uid), photo_paths=[], photo_file_ids=[], caption="вчера вес 82,5")
    )
    processing = MagicMock()
    processing.edit_text = AsyncMock()
    save_w = MagicMock(return_value="ok")
    with (
        patch(LLM_ANALYZE, return_value={"type": "weight", "data": {"weight": 82.5}}),
        patch(SAVE_WEIGHT, save_w),
    ):
        await handle_description(_msg(uid, "вчера вес 82,5"), description=None, processing_message=processing)
    assert save_w.call_count == 1
    assert save_w.call_args.args[0]["date"].startswith(_yesterday(uid))
    assert "Записано" in processing.edit_text.call_args.args[0]


@pytest.mark.parametrize(
    "text,expected_date,expected_text",
    [
        ("Сегодня чувствую себя плохо после вчерашнего", None, "Сегодня чувствую себя плохо после вчерашнего"),
    ],
)
def test_today_with_yesterday_adjective_stays_today(text, expected_date, expected_text):
    from handlers.text import extract_date_from_text

    assert extract_date_from_text(text) == (expected_date, expected_text)


def test_near_future_date_stays_this_year():
    from zoneinfo import ZoneInfo

    from handlers.text import extract_date_from_text

    tz = ZoneInfo("Europe/Moscow")
    target = datetime.now(tz) + timedelta(days=5)
    months = [
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    ]
    date_str, _ = extract_date_from_text(f"У меня {target.day} {months[target.month - 1]} приём у врача", user_tz=tz)
    assert date_str == target.strftime("%Y-%m-%d")
