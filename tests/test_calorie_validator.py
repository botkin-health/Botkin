"""Тесты кросс-валидации вес↔калории в записях питания."""

from core.food.calorie_validator import validate_weight_calorie_sync

CALORIE_MISMATCH_THRESHOLD = 0.25
HIGH_KCAL_PER_100G = 600


class TestValidateWeightCalorieSync:
    def test_recalculates_when_nutrition_per_100g_present(self):
        """Поке 150г + 476 ккал (за ~350г) + nutrition_per_100g(150) → 225 ккал."""
        data = {
            "calories": 476,
            "protein": 20,
            "fats": 15,
            "carbs": 30,
            "weight_grams": 150,
            "nutrition_per_100g": {"calories": 150, "protein": 13, "fats": 10, "carbs": 20},
        }
        result = validate_weight_calorie_sync(data)
        assert abs(result["calories"] - 225) < 1
        assert abs(result["protein"] - 19.5) < 0.5
        assert abs(result["fats"] - 15.0) < 0.5
        assert abs(result["carbs"] - 30.0) < 0.5

    def test_no_change_when_already_consistent(self):
        """Согласованная запись: рис 200г, 260 ккал (130 ккал/100г) — без изменений."""
        data = {
            "calories": 260,
            "protein": 5,
            "fats": 2,
            "carbs": 54,
            "weight_grams": 200,
            "nutrition_per_100g": {"calories": 130, "protein": 2.5, "fats": 1, "carbs": 27},
        }
        result = validate_weight_calorie_sync(data)
        assert abs(result["calories"] - 260) < 1

    def test_no_change_when_no_nutrition_per_100g(self):
        """Нет nutrition_per_100g — калории не трогаем."""
        data = {"calories": 300, "protein": 20, "fats": 10, "carbs": 30, "weight_grams": 200}
        result = validate_weight_calorie_sync(data)
        assert result["calories"] == 300

    def test_no_change_when_weight_zero(self):
        """weight_grams == 0 — не делим на ноль."""
        data = {
            "calories": 300,
            "weight_grams": 0,
            "nutrition_per_100g": {"calories": 150, "protein": 10, "fats": 5, "carbs": 20},
        }
        result = validate_weight_calorie_sync(data)
        assert result["calories"] == 300

    def test_no_change_when_weight_missing(self):
        """weight_grams отсутствует — не трогаем."""
        data = {
            "calories": 300,
            "nutrition_per_100g": {"calories": 150, "protein": 10, "fats": 5, "carbs": 20},
        }
        result = validate_weight_calorie_sync(data)
        assert result["calories"] == 300

    def test_warns_on_high_kcal_per_100g(self, caplog):
        """Нет nutrition_per_100g, но ккал/100г > 600 → предупреждение в логе."""
        import logging

        data = {"calories": 1000, "weight_grams": 100}
        with caplog.at_level(logging.WARNING, logger="core.food.calorie_validator"):
            validate_weight_calorie_sync(data)
        assert any("рассинхрон" in r.message.lower() or "ккал/100" in r.message for r in caplog.records)

    def test_immutable_does_not_modify_input(self):
        """Функция возвращает новый dict, не меняет оригинал."""
        data = {
            "calories": 476,
            "weight_grams": 150,
            "nutrition_per_100g": {"calories": 150, "protein": 10, "fats": 5, "carbs": 20},
        }
        original_calories = data["calories"]
        validate_weight_calorie_sync(data)
        assert data["calories"] == original_calories

    def test_recalculates_all_macros(self):
        """При пересчёте обновляются все макронутриенты, не только калории."""
        data = {
            "calories": 476,
            "protein": 50,
            "fats": 40,
            "carbs": 60,
            "weight_grams": 100,
            "nutrition_per_100g": {"calories": 200, "protein": 20, "fats": 8, "carbs": 25},
        }
        result = validate_weight_calorie_sync(data)
        assert abs(result["calories"] - 200) < 1
        assert abs(result["protein"] - 20) < 0.5
        assert abs(result["fats"] - 8) < 0.5
        assert abs(result["carbs"] - 25) < 0.5
