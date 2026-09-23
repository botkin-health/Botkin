"""Тесты для подсчёта выпитой воды из nutrition_log (issue #526).

Вода уже пишется как еда (0 ккал, PR #455/#457/#458). Эта задача — не новая
таблица, а агрегация ИЗ существующих записей: строка «вода: N мл» в итоге дня
и тот же итог агенту.

Покрываем:
  - core/food/water_table.py: is_water_item / water_ml_for_item / sum_water_ml
  - database/crud.py::get_nutrition_totals_by_date: ключ water_ml
  - services/nutrition_service.py::get_day_stats: totals.water_ml
"""

import sys
from datetime import date, time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOT_ROOT = PROJECT_ROOT / "telegram-bot"
for p in [str(PROJECT_ROOT), str(BOT_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from core.food.water_table import is_water_item, water_ml_for_item, sum_water_ml


# ── is_water_item: положительные и отрицательные случаи ────────────────────


class TestIsWaterItem:
    @pytest.mark.parametrize(
        "name",
        [
            "вода",
            "Вода",
            "вода питьевая",
            "минеральная вода",
            "газированная вода",
            "стакан воды",
            "Стакан воды",
            "water",
            "Water",
            "негазированная вода",
        ],
    )
    def test_water_positive(self, name):
        assert is_water_item(name) is True, f"{name!r} должно считаться водой"

    @pytest.mark.parametrize(
        "name",
        [
            "водка",
            "водка 50мл",
            "водоросли",
            "нори водоросли",
            "водяной орех",
            "кокосовая вода",
            "чай",
            "кофе",
            "суп",
            "куриный суп",
            "сок",
            "молоко",
            "",
        ],
    )
    def test_water_negative(self, name):
        assert is_water_item(name) is False, f"{name!r} НЕ должно считаться водой"


# ── water_ml_for_item: три схемы items + дефолт «стакана» ──────────────────


class TestWaterMlForItem:
    def test_product_weight_g_schema(self):
        assert water_ml_for_item({"product": "Минеральная вода", "weight_g": 500}) == 500.0

    def test_food_amount_schema(self):
        assert water_ml_for_item({"food": "Вода", "amount": 250}) == 250.0

    def test_name_weight_schema(self):
        assert water_ml_for_item({"name": "Вода", "weight": 300}) == 300.0

    def test_stakan_default_250_no_explicit_weight_estimated_flag(self):
        """«Стакан воды» без указанного объёма — 250 г, как в calculate_nutrition
        (core/food/nutrition.py default_weights['вода'] = 250)."""
        assert water_ml_for_item({"product": "Стакан воды", "weight_g": None}) == 250.0
        assert water_ml_for_item({"product": "стакан воды"}) == 250.0

    def test_non_water_item_returns_zero(self):
        assert water_ml_for_item({"product": "Водка", "weight_g": 50}) == 0.0
        assert water_ml_for_item({"product": "Чай", "weight_g": 250}) == 0.0

    def test_water_without_any_weight_and_not_stakan_is_not_counted(self):
        """Если объёма нет вообще и это не «стакан» — не считаем, не гадаем."""
        assert water_ml_for_item({"product": "Вода"}) == 0.0
        assert water_ml_for_item({"product": "Вода", "weight_g": 0}) == 0.0


# ── sum_water_ml: агрегация по списку items дня ─────────────────────────────


class TestSumWaterMl:
    def test_stakan_plus_mineral_water_500(self):
        items = [
            {"product": "Стакан воды", "weight_g": None},
            {"product": "Минеральная вода", "weight_g": 500},
        ]
        assert sum_water_ml(items) == 750.0

    def test_vodka_tea_coffee_soup_not_counted(self):
        items = [
            {"product": "Водка", "weight_g": 50},
            {"product": "Чай", "weight_g": 250},
            {"product": "Кофе", "weight_g": 200},
            {"product": "Суп куриный", "weight_g": 300},
        ]
        assert sum_water_ml(items) == 0.0

    def test_mixed_day(self):
        items = [
            {"product": "Овсянка", "weight_g": 200},
            {"product": "Стакан воды", "weight_g": 250},
            {"product": "Чай", "weight_g": 250},
            {"food": "Газированная вода", "amount": 330},
        ]
        assert sum_water_ml(items) == 580.0

    def test_empty_list(self):
        assert sum_water_ml([]) == 0.0

    def test_no_water_returns_zero_not_none(self):
        items = [{"product": "Гречка", "weight_g": 150}]
        assert sum_water_ml(items) == 0.0


# ── интеграция: get_nutrition_totals_by_date считает water_ml из items ─────


class TestNutritionTotalsIncludeWater:
    def test_totals_include_water_ml_from_multiple_meals(self, test_db):
        from database.models import NutritionLog
        from database.crud import get_nutrition_totals_by_date

        user_id = 999001
        today = date(2026, 9, 23)

        breakfast = NutritionLog(
            user_id=user_id,
            date=today,
            meal_time=time(9, 0),
            meal_name="Завтрак",
            items=[{"product": "Стакан воды", "weight_g": None}],
            totals={"calories": 0},
            status="eaten",
        )
        lunch = NutritionLog(
            user_id=user_id,
            date=today,
            meal_time=time(13, 0),
            meal_name="Обед",
            items=[
                {"product": "Минеральная вода", "weight_g": 500},
                {"product": "Куриный суп", "weight_g": 300},
            ],
            totals={"calories": 220},
            status="eaten",
        )
        test_db.add_all([breakfast, lunch])
        test_db.commit()

        totals = get_nutrition_totals_by_date(test_db, user_id, today)
        assert totals["water_ml"] == 750.0

    def test_totals_water_ml_zero_when_no_water(self, test_db):
        from database.models import NutritionLog
        from database.crud import get_nutrition_totals_by_date

        user_id = 999002
        today = date(2026, 9, 23)
        test_db.add(
            NutritionLog(
                user_id=user_id,
                date=today,
                meal_time=time(9, 0),
                meal_name="Завтрак",
                items=[{"product": "Овсянка", "weight_g": 200}],
                totals={"calories": 300},
                status="eaten",
            )
        )
        test_db.commit()

        totals = get_nutrition_totals_by_date(test_db, user_id, today)
        assert totals["water_ml"] == 0.0

    def test_vodka_not_counted_as_water(self, test_db):
        from database.models import NutritionLog
        from database.crud import get_nutrition_totals_by_date

        user_id = 999003
        today = date(2026, 9, 23)
        test_db.add(
            NutritionLog(
                user_id=user_id,
                date=today,
                meal_time=time(20, 0),
                meal_name="Ужин",
                items=[{"product": "Водка", "weight_g": 50}],
                totals={"calories": 110},
                status="eaten",
            )
        )
        test_db.commit()

        totals = get_nutrition_totals_by_date(test_db, user_id, today)
        assert totals["water_ml"] == 0.0

    def test_plan_status_counted_same_as_eaten(self, test_db):
        """status='plan' считается в итог дня как съеденное (см. модель
        NutritionLog.status) — вода из плана тоже должна попасть в итог."""
        from database.models import NutritionLog
        from database.crud import get_nutrition_totals_by_date

        user_id = 999004
        today = date(2026, 9, 23)
        test_db.add(
            NutritionLog(
                user_id=user_id,
                date=today,
                meal_time=time(13, 0),
                meal_name="Обед",
                items=[{"product": "Стакан воды", "weight_g": 250}],
                totals={"calories": 0},
                status="plan",
            )
        )
        test_db.commit()

        totals = get_nutrition_totals_by_date(test_db, user_id, today)
        assert totals["water_ml"] == 250.0

    def test_record_for_other_user_or_other_date_not_counted(self, test_db):
        """Неподтверждённая/чужая запись — в данном случае строки в
        nutrition_log попадают туда только после подтверждения (превью не
        сохраняется, см. CLAUDE.md); граница пользователь/дата — обычный
        WHERE, проверяем что он не даёт утечки воды другого юзера/дня."""
        from database.models import NutritionLog
        from database.crud import get_nutrition_totals_by_date

        user_id = 999005
        other_user_id = 999006
        today = date(2026, 9, 23)
        yesterday = date(2026, 9, 22)

        test_db.add_all(
            [
                NutritionLog(
                    user_id=other_user_id,
                    date=today,
                    meal_time=time(9, 0),
                    meal_name="Завтрак",
                    items=[{"product": "Вода", "weight_g": 1000}],
                    totals={"calories": 0},
                    status="eaten",
                ),
                NutritionLog(
                    user_id=user_id,
                    date=yesterday,
                    meal_time=time(9, 0),
                    meal_name="Завтрак",
                    items=[{"product": "Вода", "weight_g": 1000}],
                    totals={"calories": 0},
                    status="eaten",
                ),
            ]
        )
        test_db.commit()

        totals = get_nutrition_totals_by_date(test_db, user_id, today)
        assert totals["water_ml"] == 0.0


# ── NutritionService.get_day_stats выставляет totals.water_ml ──────────────


class TestNutritionServiceWaterMl:
    def test_get_day_stats_exposes_water_ml(self, mock_session_local):
        from database.models import NutritionLog, User, UserSettings
        from services.nutrition_service import get_nutrition_service

        user_id = 999010
        today = date(2026, 9, 23)
        mock_session_local.add(User(telegram_id=user_id, username="water_test", is_active=True, role="user"))
        mock_session_local.add(UserSettings(user_id=user_id))
        mock_session_local.add(
            NutritionLog(
                user_id=user_id,
                date=today,
                meal_time=time(9, 0),
                meal_name="Завтрак",
                items=[{"product": "Стакан воды", "weight_g": 250}],
                totals={"calories": 0},
                status="eaten",
            )
        )
        mock_session_local.commit()

        service = get_nutrition_service(user_id=user_id)
        stats = service.get_day_stats(today)
        assert stats["totals"].water_ml == 250.0


@pytest.mark.parametrize("name", ["кофе, разбавленный водой", "американо с водой", "виски с водой"])
def test_something_with_water_is_not_water(name):
    """«X с водой» — это X, а не вода (ревью #526 на реальных названиях с прода)."""
    assert is_water_item(name) is False
