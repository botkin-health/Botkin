"""Кросс-валидация согласованности вес↔калории в записях питания."""

import logging

logger = logging.getLogger(__name__)

_HIGH_KCAL_PER_100G = 600


def validate_weight_calorie_sync(data: dict) -> dict:
    """Проверяет и исправляет рассинхрон между weight_grams и calories.

    Когда LLM оценивает калории за полную порцию (~350 г), а парсер веса
    выдаёт 150 г (основной ингредиент) — возникает завышение ккал/100г вдвое.

    Стратегия:
    - Если есть nutrition_per_100g и weight_grams > 0 → пересчитать все
      макронутриенты от nutrition_per_100g × weight_grams (nutrition_per_100g
      точнее, т.к. LLM оценивает её независимо от порции).
    - Если nutrition_per_100g отсутствует, но ккал/100г > _HIGH_KCAL_PER_100G
      → логировать предупреждение (данных для автофикса нет).

    Args:
        data: Словарь с полями calories, weight_grams, nutrition_per_100g и
              макронутриентами. Не мутируется.

    Returns:
        Новый словарь с исправленными значениями (или исходный при отсутствии
        данных для валидации).
    """
    weight_grams = data.get("weight_grams")
    nutrition_per_100g = data.get("nutrition_per_100g")

    if not weight_grams or weight_grams <= 0:
        return data

    if nutrition_per_100g:
        multiplier = weight_grams / 100.0
        return {
            **data,
            "calories": nutrition_per_100g.get("calories", 0) * multiplier,
            "protein": nutrition_per_100g.get("protein", 0) * multiplier,
            "fats": nutrition_per_100g.get("fats", 0) * multiplier,
            "carbs": nutrition_per_100g.get("carbs", 0) * multiplier,
        }

    calories = data.get("calories", 0)
    if calories and weight_grams:
        kcal_per_100g = calories / weight_grams * 100
        if kcal_per_100g > _HIGH_KCAL_PER_100G:
            logger.warning(
                "Вероятный рассинхрон вес↔калории: %.0f ккал/100г "
                "(%.0f ккал на %.0f г) — нет nutrition_per_100g для автофикса",
                kcal_per_100g,
                calories,
                weight_grams,
            )

    return data
