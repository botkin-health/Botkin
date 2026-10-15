"""Время/дата записей — в таймзоне пользователя, а не по захардкоженной MSK.

Регрессия: пользователь в Дубае (UTC+4) отправил обед в 13:04 местного,
в nutrition_log.meal_time записалось 12:04 (UTC+3).
"""

from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from core.infra import tz as tz_mod
from database.models import NutritionLog
from helpers.db_save import save_meal_to_db

# 20:30 UTC = 00:30 15.10 в Дубае, но 23:30 14.10 по Москве
_INSTANT = datetime(2026, 10, 14, 20, 30, tzinfo=timezone.utc)


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return _INSTANT.astimezone(tz) if tz else _INSTANT.replace(tzinfo=None)


def _meal(**extra):
    return {
        "meal_items": [{"product": "Банан", "weight_g": 120, "calories": 110}],
        "meal_totals": {"calories": 110, "protein": 1, "fats": 0, "carbs": 28},
        **extra,
    }


def test_now_in_user_tz_uses_user_zone():
    with (
        patch.object(tz_mod, "datetime", _FrozenDatetime),
        patch.object(tz_mod, "get_user_tz", return_value=ZoneInfo("Asia/Dubai")),
    ):
        now = tz_mod.now_in_user_tz(42)
    assert (now.date().isoformat(), now.strftime("%H:%M")) == ("2026-10-15", "00:30")


def test_now_in_user_tz_unknown_user_falls_back_to_msk():
    with patch.object(tz_mod, "datetime", _FrozenDatetime):
        now = tz_mod.now_in_user_tz(None)
    assert (now.date().isoformat(), now.strftime("%H:%M")) == ("2026-10-14", "23:30")


def test_save_meal_without_explicit_time_uses_dubai_date_and_time(test_db):
    """Между 00:00 и 01:00 по Дубаю дата не должна уходить на предыдущие сутки."""
    with (
        patch.object(tz_mod, "datetime", _FrozenDatetime),
        patch.object(tz_mod, "get_user_tz", return_value=ZoneInfo("Asia/Dubai")),
        patch("helpers.db_save.SessionLocal", return_value=test_db),
    ):
        meal_id = save_meal_to_db(_meal(), "Обед", user_id=42)

    row = test_db.query(NutritionLog).filter(NutritionLog.id == meal_id).one()
    assert row.date.isoformat() == "2026-10-15"
    assert row.meal_time.strftime("%H:%M") == "00:30"


def test_save_meal_default_user_stays_on_moscow_time(test_db):
    with (
        patch.object(tz_mod, "datetime", _FrozenDatetime),
        patch.object(tz_mod, "get_user_tz", return_value=ZoneInfo("Europe/Moscow")),
        patch("helpers.db_save.SessionLocal", return_value=test_db),
    ):
        meal_id = save_meal_to_db(_meal(), "Ужин", user_id=42)

    row = test_db.query(NutritionLog).filter(NutritionLog.id == meal_id).one()
    assert row.date.isoformat() == "2026-10-14"
    assert row.meal_time.strftime("%H:%M") == "23:30"
