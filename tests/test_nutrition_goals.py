import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

from datetime import date
from unittest.mock import patch

from webhook.nutrition_goals import compute_goals


def test_compute_goals_full_budget():
    fake_budget = {"target": 2000, "consumed": 0, "remaining": 2000, "pct": 0, "warn": False, "has_garmin": True}
    with patch("webhook.nutrition_goals.get_daily_budget", return_value=fake_budget):
        g = compute_goals(user_id=895655, for_date=date(2026, 4, 17))
    assert g == {
        "kcal": 2000,
        "protein": 150,
        "fats": 67,
        "carbs": 200,
        "fiber": 30,
    }


def test_compute_goals_missing_target_returns_none_kcal():
    fake_budget = {"target": None, "consumed": 0, "remaining": 0, "pct": 0, "warn": False, "has_garmin": False}
    with patch("webhook.nutrition_goals.get_daily_budget", return_value=fake_budget):
        g = compute_goals(user_id=895655, for_date=date(2026, 4, 17))
    assert g == {"kcal": None, "protein": None, "fats": None, "carbs": None, "fiber": 30}
