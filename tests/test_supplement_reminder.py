"""Напоминание о добавках/лекарствах (scripts/server/send_reminders.py::run).

Регрессия: напоминание приходило, даже если пользователь уже отметил приём
таблеток сегодня (отметка в 10:59, напоминание в 11:00).
"""

import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scripts.server.send_reminders as send_reminders  # noqa: E402

TZ = timezone(timedelta(hours=3))
UID = 900001
TODAY = date(2026, 11, 8)


def _seed(db, supplement_dates=()):
    from database.models import SupplementLog, User, UserSettings

    db.add(User(telegram_id=UID, first_name="Test"))
    db.add(
        UserSettings(
            user_id=UID,
            supplement_reminders_enabled=True,
            supplement_reminder_time=time(11, 0),
            meal_reminders_enabled=False,
        )
    )
    for d in supplement_dates:
        db.add(SupplementLog(user_id=UID, date=d, supplement_name="Утренние таблетки"))
    db.commit()


def _run(db, now_local):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now_local.astimezone(tz) if tz else now_local

    sent = []
    with (
        patch("database.SessionLocal", return_value=db),
        patch.object(send_reminders, "get_user_tz", return_value=TZ),
        patch.object(send_reminders, "datetime", FrozenDatetime),
        patch.object(send_reminders, "dispatch_plan_close", return_value=0),
        patch.object(
            send_reminders, "_send", side_effect=lambda token, uid, text, dry, **kw: sent.append(text) or True
        ),
        patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "dummy"}),
    ):
        send_reminders.run(dry=False)
    return sent


def _last_sent(db):
    from database.models import UserSettings

    db.expire_all()
    return (db.query(UserSettings).filter(UserSettings.user_id == UID).one().meal_reminder_last_sent) or {}


def test_no_reminder_when_taken_today(test_db):
    _seed(test_db, supplement_dates=[TODAY])
    sent = _run(test_db, datetime(2026, 11, 8, 11, 5, tzinfo=TZ))
    assert sent == []
    # день закрыт — дальнейшие прогоны в окне не дёргают БД и не шлют
    assert _last_sent(test_db).get(send_reminders.SUPPLEMENT_KEY) == TODAY.isoformat()


def test_reminder_sent_when_not_taken_today(test_db):
    # вчерашняя отметка не считается
    _seed(test_db, supplement_dates=[TODAY - timedelta(days=1)])
    sent = _run(test_db, datetime(2026, 11, 8, 11, 5, tzinfo=TZ))
    assert len(sent) == 1
    assert "добавки/лекарства" in sent[0]


def test_taken_after_window_start_suppresses_next_runs(test_db):
    # отметил в 11:10 — прогон в 11:15 уже не напоминает (прогон в 11:00 не успел)
    _seed(test_db, supplement_dates=[TODAY])
    assert _run(test_db, datetime(2026, 11, 8, 11, 15, tzinfo=TZ)) == []
