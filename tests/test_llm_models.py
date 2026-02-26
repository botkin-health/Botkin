"""
Тесты для core/llm_models.py — Pydantic-валидация ответов LLM.

Покрывают:
1. Нормальные данные (happy path)
2. Типичные ошибки GPT: строки вместо чисел, null, отсутствующие поля
3. Граничные случаи: отрицательные, пустые списки, неизвестный тип
4. Интеграция с process_llm_food_data (pipeline без вызова API)
"""
import pytest
from core.llm_models import parse_llm_response

# core.nutrition нужно загрузить ДО core.llm_food_processor, иначе круговой
# импорт (nutrition → llm_food_processor → nutrition) падает при изолированном
# запуске теста. Это стандартный способ разрыва circular import в тестах.
import core.nutrition  # noqa: F401
from core.llm_food_processor import process_llm_food_data


# ===========================================================================
# FOOD — ответы о еде
# ===========================================================================

class TestFoodResponseParsing:

    def test_valid_food_response(self):
        """Нормальный ответ GPT — все числа числами, всё на месте."""
        raw = {
            "type": "food",
            "data": {
                "dish_name": "Завтрак",
                "meal_type": "breakfast",
                "items": [
                    {"name": "Овсянка", "weight": 100, "calories": 350,
                     "protein": 10, "fats": 7, "carbs": 60}
                ],
                "total_nutrition": {"calories": 350, "protein": 10, "fats": 7, "carbs": 60}
            }
        }
        result = parse_llm_response(raw)
        assert result["type"] == "food"
        item = result["data"]["items"][0]
        assert item["weight"] == 100.0
        assert item["calories"] == 350.0
        assert item["protein"] == 10.0

    def test_weight_as_string_coerced_to_float(self):
        """GPT вернул вес как строку '150' → должно стать 150.0."""
        raw = {
            "type": "food",
            "data": {
                "dish_name": "Обед",
                "meal_type": "lunch",
                "items": [{"name": "Курица", "weight": "150", "calories": "250",
                           "protein": "40", "fats": "5", "carbs": "0"}],
                "total_nutrition": None
            }
        }
        result = parse_llm_response(raw)
        item = result["data"]["items"][0]
        assert isinstance(item["weight"], float), "weight должен быть float, не строкой"
        assert item["weight"] == 150.0
        assert item["calories"] == 250.0
        assert item["protein"] == 40.0

    def test_weight_null_stays_none(self):
        """GPT вернул null для веса → остаётся None, не 0."""
        raw = {
            "type": "food",
            "data": {
                "dish_name": "Ужин",
                "meal_type": "dinner",
                "items": [{"name": "Борщ", "weight": None, "calories": 150}],
                "total_nutrition": None
            }
        }
        result = parse_llm_response(raw)
        assert result["data"]["items"][0]["weight"] is None

    def test_weight_null_string_stays_none(self):
        """GPT вернул строку 'null' для веса → тоже None."""
        raw = {
            "type": "food",
            "data": {
                "dish_name": "Суп",
                "meal_type": "lunch",
                "items": [{"name": "Суп", "weight": "null", "calories": 120}],
                "total_nutrition": None
            }
        }
        result = parse_llm_response(raw)
        assert result["data"]["items"][0]["weight"] is None

    def test_negative_calories_become_none(self):
        """Отрицательные калории (ошибка GPT) → None."""
        raw = {
            "type": "food",
            "data": {
                "dish_name": "Тест",
                "meal_type": "snack",
                "items": [{"name": "Продукт", "weight": 100, "calories": -50}],
                "total_nutrition": None
            }
        }
        result = parse_llm_response(raw)
        assert result["data"]["items"][0]["calories"] is None

    def test_missing_macros_default_to_none(self):
        """GPT не вернул КБЖУ — поля должны стать None, не падать."""
        raw = {
            "type": "food",
            "data": {
                "dish_name": "Яблоко",
                "meal_type": "snack",
                "items": [{"name": "Яблоко"}],  # нет weight, calories и т.д.
                "total_nutrition": None
            }
        }
        result = parse_llm_response(raw)
        item = result["data"]["items"][0]
        assert item["name"] == "Яблоко"
        assert item["weight"] is None
        assert item["calories"] is None
        assert item["protein"] is None

    def test_missing_items_field_becomes_empty_list(self):
        """Отсутствует поле items → пустой список, не ошибка."""
        raw = {
            "type": "food",
            "data": {"dish_name": "Без ингредиентов", "meal_type": "snack"}
            # нет "items"
        }
        result = parse_llm_response(raw)
        assert result["data"]["items"] == []

    def test_empty_items_list(self):
        """Пустой список продуктов — не должно падать."""
        raw = {
            "type": "food",
            "data": {
                "dish_name": "Пустой",
                "meal_type": "snack",
                "items": [],
                "total_nutrition": None
            }
        }
        result = parse_llm_response(raw)
        assert result["data"]["items"] == []

    def test_total_nutrition_null_fields_become_zero(self):
        """null в total_nutrition → 0.0 (не None), потому что это итоги."""
        raw = {
            "type": "food",
            "data": {
                "dish_name": "Тест",
                "meal_type": "snack",
                "items": [],
                "total_nutrition": {
                    "calories": None, "protein": None, "fats": None, "carbs": None
                }
            }
        }
        result = parse_llm_response(raw)
        totals = result["data"]["total_nutrition"]
        assert totals["calories"] == 0.0
        assert totals["protein"] == 0.0

    def test_total_nutrition_string_values_coerced(self):
        """total_nutrition с числами-строками → float."""
        raw = {
            "type": "food",
            "data": {
                "dish_name": "Этикетка",
                "meal_type": "snack",
                "items": [],
                "total_nutrition": {
                    "calories": "668", "protein": "47", "fats": "22", "carbs": "70"
                }
            }
        }
        result = parse_llm_response(raw)
        assert result["data"]["total_nutrition"]["calories"] == 668.0
        assert result["data"]["total_nutrition"]["protein"] == 47.0

    def test_missing_meal_type_defaults_to_snack(self):
        """Нет meal_type → 'snack' по умолчанию."""
        raw = {
            "type": "food",
            "data": {
                "dish_name": "Что-то",
                "items": [{"name": "Творог", "weight": 200, "calories": 200}]
            }
        }
        result = parse_llm_response(raw)
        assert result["data"]["meal_type"] == "snack"

    def test_structure_preserved_for_food_processor(self):
        """Структура после валидации совместима с process_llm_food_data."""
        raw = {
            "type": "food",
            "data": {
                "dish_name": "Обед",
                "meal_type": "lunch",
                "items": [
                    {"name": "Гречка", "weight": 150, "calories": 510,
                     "protein": 18, "fats": 5, "carbs": 99},
                ],
                "total_nutrition": None
            }
        }
        result = parse_llm_response(raw)
        # Проверяем что у dict есть все ключи которые ждёт food processor
        assert "type" in result
        assert "data" in result
        data = result["data"]
        assert "items" in data
        item = data["items"][0]
        assert "name" in item
        assert "weight" in item
        assert "calories" in item


# ===========================================================================
# WEIGHT — данные весов
# ===========================================================================

class TestWeightResponseParsing:

    def test_valid_weight_response(self):
        """Нормальные данные весов с body composition."""
        raw = {
            "type": "weight",
            "data": {
                "weight": 75.5,
                "body_fat": 28.0,
                "muscle_mass": 52.0,
                "visceral_fat": 12,
                "water_percent": None,
                "date": None
            }
        }
        result = parse_llm_response(raw)
        assert result["data"]["weight"] == 75.5
        assert result["data"]["body_fat"] == 28.0
        assert result["data"]["visceral_fat"] == 12.0

    def test_weight_as_string(self):
        """Вес как строка '75.3' → float 75.3."""
        raw = {
            "type": "weight",
            "data": {"weight": "75.3", "body_fat": "27.5", "date": None}
        }
        result = parse_llm_response(raw)
        assert isinstance(result["data"]["weight"], float)
        assert result["data"]["weight"] == 75.3
        assert result["data"]["body_fat"] == 27.5

    def test_optional_fields_absent(self):
        """Только вес — опциональные поля должны быть None."""
        raw = {
            "type": "weight",
            "data": {"weight": 80.0}
        }
        result = parse_llm_response(raw)
        assert result["data"]["weight"] == 80.0
        assert result["data"]["body_fat"] is None
        assert result["data"]["muscle_mass"] is None
        assert result["data"]["visceral_fat"] is None

    def test_weight_null_falls_back_to_raw(self):
        """Вес = null → валидация падает, возвращаем raw (backward compat)."""
        raw = {
            "type": "weight",
            "data": {"weight": None, "body_fat": 25.0}
        }
        # Не должно бросить исключение — либо вернёт raw, либо поднимет
        # ValidationError которую мы ловим внутри parse_llm_response
        result = parse_llm_response(raw)
        assert result is not None  # не упало


# ===========================================================================
# VITAMINS — витамины и БАДы
# ===========================================================================

class TestVitaminsResponseParsing:

    def test_valid_vitamins(self):
        """Нормальный список витаминов."""
        raw = {
            "type": "vitamins",
            "data": {"items": ["Витамин D", "Омега-3", "Магний"], "action": "logged"}
        }
        result = parse_llm_response(raw)
        assert result["type"] == "vitamins"
        assert "Витамин D" in result["data"]["items"]
        assert len(result["data"]["items"]) == 3

    def test_empty_vitamins_list(self):
        """Пустой список витаминов — не должно падать."""
        raw = {
            "type": "vitamins",
            "data": {"items": [], "action": "logged"}
        }
        result = parse_llm_response(raw)
        assert result["data"]["items"] == []

    def test_missing_action_gets_default(self):
        """Нет поля action → 'logged' по умолчанию."""
        raw = {
            "type": "vitamins",
            "data": {"items": ["Псиллиум"]}
        }
        result = parse_llm_response(raw)
        assert result["data"]["action"] == "logged"


# ===========================================================================
# OTHER / MEDICAL — прочие типы
# ===========================================================================

class TestOtherTypes:

    def test_other_type_passed_through_as_is(self):
        """Тип 'other' — данные пропускаются без изменений."""
        raw = {"type": "other", "data": {"reply": "Привет! Чем помочь?"}}
        result = parse_llm_response(raw)
        assert result["type"] == "other"
        assert result["data"]["reply"] == "Привет! Чем помочь?"

    def test_medical_type_passed_through(self):
        """Тип 'medical' — произвольная структура, пропускается как есть."""
        raw = {
            "type": "medical",
            "data": {"notes": "ЛДЛ 3.79, Общий холестерин 5.4"}
        }
        result = parse_llm_response(raw)
        assert result["type"] == "medical"
        assert result["data"]["notes"] == "ЛДЛ 3.79, Общий холестерин 5.4"

    def test_unknown_future_type_doesnt_crash(self):
        """Неизвестный тип из будущей версии GPT — не падаем, возвращаем raw."""
        raw = {"type": "workout", "data": {"exercises": ["бег", "отжимания"]}}
        result = parse_llm_response(raw)
        assert result is not None
        assert result["type"] == "workout"


# ===========================================================================
# EDGE CASES — граничные случаи
# ===========================================================================

class TestEdgeCases:

    def test_none_input_returns_none(self):
        """None на входе → None, не ошибка."""
        assert parse_llm_response(None) is None

    def test_empty_dict_returns_empty(self):
        """Пустой dict → возвращаем как есть."""
        result = parse_llm_response({})
        assert result == {}

    def test_missing_data_field(self):
        """Нет поля data совсем → fallback к raw, не падаем."""
        raw = {"type": "food"}  # нет "data"
        result = parse_llm_response(raw)
        assert result is not None  # не упало

    def test_data_is_not_dict(self):
        """data — строка вместо dict (совсем плохой ответ GPT) → fallback."""
        raw = {"type": "food", "data": "что-то пошло не так"}
        result = parse_llm_response(raw)
        assert result is not None  # не упало


# ===========================================================================
# INTEGRATION — интеграция с process_llm_food_data
# ===========================================================================

class TestFoodProcessorIntegration:
    """
    Тестируем полный pipeline: parse_llm_response → process_llm_food_data.
    Нет вызовов API — только обработка данных.
    """

    def test_pipeline_normal_meal(self):
        """Обычный обед: гречка + курица — должны посчитаться калории."""
        raw = {
            "type": "food",
            "data": {
                "dish_name": "Обед",
                "meal_type": "lunch",
                "items": [
                    {"name": "Гречка", "weight": 150, "calories": 510,
                     "protein": 18, "fats": 5, "carbs": 99},
                    {"name": "Куриная грудка", "weight": 200, "calories": 330,
                     "protein": 62, "fats": 7, "carbs": 0}
                ],
                "total_nutrition": None
            }
        }
        validated = parse_llm_response(raw)
        meal_items, totals = process_llm_food_data(validated)

        assert len(meal_items) == 2
        assert totals["calories"] > 0
        assert totals["protein"] > 50  # курица даёт много белка

    def test_pipeline_with_null_weight_doesnt_crash(self):
        """Продукт без веса (null) — pipeline не должен падать."""
        raw = {
            "type": "food",
            "data": {
                "dish_name": "Снек",
                "meal_type": "snack",
                "items": [{"name": "Яблоко", "weight": None, "calories": 80}],
                "total_nutrition": None
            }
        }
        validated = parse_llm_response(raw)
        meal_items, totals = process_llm_food_data(validated)

        assert isinstance(meal_items, list)
        assert isinstance(totals, dict)
        assert "calories" in totals

    def test_pipeline_string_weights_coerced_before_processing(self):
        """Строковые числа от GPT → float → корректные расчёты."""
        raw = {
            "type": "food",
            "data": {
                "dish_name": "Перекус",
                "meal_type": "snack",
                "items": [{"name": "Творог", "weight": "200",
                           "calories": "200", "protein": "30",
                           "fats": "4", "carbs": "8"}],
                "total_nutrition": None
            }
        }
        validated = parse_llm_response(raw)
        meal_items, totals = process_llm_food_data(validated)

        assert len(meal_items) == 1
        # weight_g должен быть числом, не строкой
        assert isinstance(meal_items[0]["weight_g"], (int, float))
        assert meal_items[0]["weight_g"] > 0

    def test_pipeline_empty_items(self):
        """Пустой список продуктов → 0 ккал, не падает."""
        raw = {
            "type": "food",
            "data": {
                "dish_name": "Пустой",
                "meal_type": "snack",
                "items": [],
                "total_nutrition": None
            }
        }
        validated = parse_llm_response(raw)
        meal_items, totals = process_llm_food_data(validated)

        assert meal_items == []
        assert totals["calories"] == 0

    def test_pipeline_negative_calories_handled(self):
        """Отрицательные калории от GPT → None → food processor справляется."""
        raw = {
            "type": "food",
            "data": {
                "dish_name": "Баг GPT",
                "meal_type": "snack",
                "items": [{"name": "Салат", "weight": 100, "calories": -30,
                           "protein": -5, "fats": -1, "carbs": -3}],
                "total_nutrition": None
            }
        }
        validated = parse_llm_response(raw)
        # После валидации calories/protein/fats/carbs = None
        assert validated["data"]["items"][0]["calories"] is None

        meal_items, totals = process_llm_food_data(validated)
        assert isinstance(meal_items, list)
        # Нет ошибки — бот не падает

    def test_pipeline_recipe_label_uses_explicit_totals(self):
        """Этикетка с явными КБЖУ → total_nutrition берётся из LLM, не вычисляется."""
        raw = {
            "type": "food",
            "data": {
                "dish_name": "Протеин Tree of Life",
                "meal_type": "snack",
                "items": [
                    {"name": "Протеиновый коктейль", "weight": 35,
                     "calories": 130, "protein": 25, "fats": 2, "carbs": 4}
                ],
                "total_nutrition": {
                    "calories": 130, "protein": 25, "fats": 2, "carbs": 4
                }
            }
        }
        validated = parse_llm_response(raw)
        meal_items, totals = process_llm_food_data(validated)

        # Для 1 продукта с explicit total — берём из total_nutrition
        assert totals["calories"] == 130.0
        assert totals["protein"] == 25.0

    def test_pipeline_label_per_100g_with_user_weight(self):
        """
        РЕГРЕССИЯ: Этикетка индейки «на 100г», пользователь написал «150 грамм».
        LLM должен умножить: 169 ккал/100г × 1.5 = 253.5 ккал.
        Баг: раньше LLM возвращал 169 ккал как итог, игнорируя вес.
        """
        # Симулируем корректный ответ LLM после фикса промпта:
        # LLM видит «на 100г: 169 ккал», пользователь написал «150 грамм»
        # → LLM должен умножить и вернуть 253.5 ккал для 150г
        raw = {
            "type": "food",
            "data": {
                "dish_name": "Консервы из мяса птицы «Индейка томлёная в собственном соку»",
                "meal_type": "lunch",
                "items": [
                    {
                        "name": "Индейка томлёная в собственном соку",
                        "weight": 150,       # пользователь указал 150г
                        "calories": 253.5,   # 169 * 1.5 — LLM умножил
                        "protein": 27.75,    # 18.5 * 1.5
                        "fats": 15.75,       # 10.5 * 1.5
                        "carbs": 0.0
                    }
                ],
                "total_nutrition": {
                    "calories": 253.5,
                    "protein": 27.75,
                    "fats": 15.75,
                    "carbs": 0.0
                }
            }
        }
        validated = parse_llm_response(raw)
        meal_items, totals = process_llm_food_data(validated)

        assert len(meal_items) == 1
        assert meal_items[0]["weight_g"] == 150.0

        # Главная проверка: НЕ 169 (per-100g), а 253.5 (для 150г)
        assert totals["calories"] > 200, (
            f"Ожидалось ~253 ккал для 150г, получено {totals['calories']}. "
            "Возможно LLM вернул per-100g значение вместо итога для 150г."
        )
        assert abs(totals["calories"] - 253.5) < 5, (
            f"Ожидалось 253.5 ккал, получено {totals['calories']}"
        )
        assert totals["protein"] > 20  # 27.75г белка для 150г индейки
