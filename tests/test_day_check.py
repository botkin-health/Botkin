"""Утренний вопрос «вчера внёс всё?» (ADR-0015): логика, кнопки, диспетчер, хендлер."""

import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOT_ROOT = PROJECT_ROOT / "telegram-bot"
for p in [str(PROJECT_ROOT), str(BOT_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from core.reminders import day_check  # noqa: E402

TODAY = date(2026, 11, 15)
YESTERDAY = TODAY - timedelta(days=1)


def test_window_and_dedup():
    morning = datetime(2026, 11, 15, 9, 30)
    assert day_check.in_window(morning, {}, "2026-11-15")
    assert not day_check.in_window(morning, {day_check.DAY_CHECK_KEY: "2026-11-15"}, "2026-11-15")
    assert day_check.in_window(morning, {day_check.DAY_CHECK_KEY: "2026-11-14"}, "2026-11-15")
    assert not day_check.in_window(datetime(2026, 11, 15, 8, 59), {}, "2026-11-15")
    assert not day_check.in_window(datetime(2026, 11, 15, 12, 0), {}, "2026-11-15")


def test_typical_needs_history_and_skips_incomplete():
    intake = {YESTERDAY - timedelta(days=i): 2000.0 for i in range(1, 12)}
    intake[YESTERDAY - timedelta(days=1)] = 500.0
    statuses = {YESTERDAY - timedelta(days=1): False}
    assert day_check.typical_day_kcal(intake, statuses, before=YESTERDAY) == 2000.0
    short = {YESTERDAY - timedelta(days=i): 2000.0 for i in range(1, 5)}
    assert day_check.typical_day_kcal(short, {}, before=YESTERDAY) is None


@pytest.mark.parametrize(
    "kcal,typical,marked,expected",
    [
        (1250, 2100, False, True),
        (1900, 2100, False, False),  # 90% обычного — норм
        (0, 2100, False, False),  # пустой день в расчёт и так не идёт
        (1250, None, False, False),  # истории мало
        (1250, 2100, True, False),  # уже ответил
    ],
)
def test_should_ask_about(kcal, typical, marked, expected):
    assert day_check.should_ask_about(kcal, typical, marked) is expected


def test_keyboard_matches_aiogram_pack():
    from handlers.callbacks import DayCheckCallback

    kb = day_check.build_keyboard("2026-11-14")
    datas = {b["callback_data"] for row in kb["inline_keyboard"] for b in row}
    assert datas == {
        DayCheckCallback(answer="yes", date="2026-11-14").pack(),
        DayCheckCallback(answer="no", date="2026-11-14").pack(),
    }


def test_question_text():
    q = day_check.build_question(YESTERDAY, 1257, 2100)
    assert "14.11" in q and "1257" in q and "2100" in q


def _seed(db, uid: int, yesterday_kcal: float):
    from database.models import NutritionLog, User, UserSettings

    db.add(User(telegram_id=uid, username=f"u{uid}", is_active=True, role="user"))
    db.add(UserSettings(user_id=uid))
    for i in range(1, 20):
        d = YESTERDAY - timedelta(days=i)
        db.add(
            NutritionLog(
                user_id=uid, date=d, meal_time=time(13, 0), meal_name="Обед", items=[], totals={"calories": 2100}
            )
        )
    db.add(
        NutritionLog(
            user_id=uid,
            date=YESTERDAY,
            meal_time=time(13, 0),
            meal_name="Обед",
            items=[],
            totals={"calories": yesterday_kcal},
        )
    )
    db.commit()


def test_dispatch_asks_only_underlogged_and_once(test_db):
    import scripts.server.send_reminders as send_reminders
    from database.models import UserSettings

    _seed(test_db, 900001, 1200)  # недолог
    _seed(test_db, 900002, 2050)  # обычный день
    sent = []

    def fake_send(token, chat_id, text, dry, reply_markup=None):
        sent.append((chat_id, reply_markup))
        return True

    now = datetime(2026, 11, 15, 9, 15)
    with (
        patch.object(send_reminders, "_send", side_effect=fake_send),
        patch("core.infra.tz.get_user_tz", return_value=None),
    ):
        n = send_reminders.dispatch_day_check(test_db, token="x", dry=False, now_fn=lambda tz: now)
        n2 = send_reminders.dispatch_day_check(test_db, token="x", dry=False, now_fn=lambda tz: now)

    assert n == 1 and n2 == 0
    assert [c for c, _ in sent] == [900001]
    assert sent[0][1] == day_check.build_keyboard("2026-11-14")
    for uid in (900001, 900002):
        s = test_db.query(UserSettings).filter(UserSettings.user_id == uid).first()
        assert s.meal_reminder_last_sent[day_check.DAY_CHECK_KEY] == "2026-11-15"


def test_dispatch_skips_already_marked_day(test_db):
    import scripts.server.send_reminders as send_reminders
    from database.crud import set_day_status

    _seed(test_db, 900003, 1200)
    set_day_status(test_db, 900003, YESTERDAY, True)
    with (
        patch.object(send_reminders, "_send", return_value=True) as s,
        patch("core.infra.tz.get_user_tz", return_value=None),
    ):
        n = send_reminders.dispatch_day_check(
            test_db, token="x", dry=False, now_fn=lambda tz: datetime(2026, 11, 15, 10)
        )
    assert n == 0
    s.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("answer,complete", [("yes", True), ("no", False)])
async def test_handler_writes_status(test_db, mock_session_local, answer, complete):
    from database.crud import get_day_statuses_by_period
    from database.models import User
    from handlers.callbacks import DayCheckCallback
    from handlers.day_check import handle_day_check

    uid = 900010
    test_db.add(User(telegram_id=uid, username="dc", is_active=True, role="user"))
    test_db.commit()

    cb = AsyncMock()
    cb.from_user = MagicMock()
    cb.from_user.id = uid
    cb.message = AsyncMock()
    with (
        patch("handlers.day_check.safe_edit_text", new=AsyncMock()) as edit,
        patch("handlers.day_check.SessionLocal", return_value=test_db),
    ):
        test_db.close = MagicMock()
        await handle_day_check(cb, DayCheckCallback(answer=answer, date="2026-11-14"))

    assert get_day_statuses_by_period(test_db, uid, YESTERDAY, YESTERDAY) == {YESTERDAY: complete}
    edit.assert_awaited_once()
