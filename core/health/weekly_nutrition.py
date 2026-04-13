#!/usr/bin/env python3
"""
Недельный учёт питания с категориями и коррекциями - PostgreSQL Version
"""

from datetime import datetime, timedelta, date as date_type
from typing import Dict, List
from collections import defaultdict

from database import SessionLocal, get_nutrition_logs_by_period, get_supplements_by_period, get_activity_logs_by_period


def get_last_7_days() -> List[date_type]:
    """Возвращает список дат за последние 7 дней"""
    today = datetime.now().date()
    return [today - timedelta(days=i) for i in range(7)]


def categorize_food_item(food_name: str, meal_time: str = None) -> Dict[str, bool]:
    """
    Категоризирует продукт по правилам патча:
    - Жирная рыба (лосось, скумбрия, сардина, сельдь)
    - Красное мясо (говядина, свинина, баранина)
    - Переработанное мясо (колбаса, сосиски, ветчина и т.д.)
    - Углеводы вечером (если meal_time указывает на ужин/вечер)
    - Алкоголь
    """
    food_lower = food_name.lower()

    categories = {
        "fatty_fish": False,
        "red_meat": False,
        "processed_meat": False,
        "high_carb_dinner": False,
        "alcohol": False,
    }

    # Жирная рыба
    fatty_fish_keywords = [
        "лосось",
        "скумбрия",
        "сардина",
        "сельдь",
        "сайра",
        "salmon",
        "mackerel",
        "sardine",
        "herring",
        "saira",
    ]
    if any(keyword in food_lower for keyword in fatty_fish_keywords):
        categories["fatty_fish"] = True

    # Красное мясо
    red_meat_keywords = ["говядина", "свинина", "баранина", "beef", "pork", "lamb", "стейк", "steak"]
    if any(keyword in food_lower for keyword in red_meat_keywords):
        categories["red_meat"] = True

    # Переработанное мясо
    processed_keywords = ["колбаса", "сосиски", "ветчина", "бекон", "sausage", "ham", "bacon", "салями"]
    if any(keyword in food_lower for keyword in processed_keywords):
        categories["processed_meat"] = True

    # Углеводы вечером (определяем по meal_time или по названию блюда)
    if meal_time:
        meal_lower = meal_time.lower()
        is_dinner = "ужин" in meal_lower or "dinner" in meal_lower or "вечер" in meal_lower
        if is_dinner:
            high_carb_keywords = [
                "каша",
                "рис",
                "макароны",
                "пюре",
                "хлеб",
                "картофель",
                "гречка",
                "porridge",
                "rice",
                "pasta",
                "bread",
                "potato",
            ]
            if any(keyword in food_lower for keyword in high_carb_keywords):
                categories["high_carb_dinner"] = True

    # Алкоголь
    alcohol_keywords = ["алкоголь", "вино", "пиво", "водка", "виски", "wine", "beer", "vodka", "whiskey", "guinness"]
    if any(keyword in food_lower for keyword in alcohol_keywords):
        categories["alcohol"] = True

    return categories


def estimate_fiber(food_name: str, amount_g: float) -> float:
    """Оценивает количество клетчатки в продукте (очень приблизительно)"""
    food_lower = food_name.lower()

    # Высокое содержание клетчатки (5-10 г на 100г)
    high_fiber = [
        "овощи",
        "фасоль",
        "бобовые",
        "овощ",
        "капуста",
        "брокколи",
        "шпинат",
        "овощной",
        "vegetable",
        "beans",
        "legumes",
        "cabbage",
        "broccoli",
        "spinach",
        "хлебец",
        "отруби",
        "чечевица",
        "нут",
        "горох",
        "винегрет",
        "авокадо",
        "семечки",
        "орех",
        "seeds",
        "nuts",
        "миндаль",
        "кешью",
        "фундук",
    ]
    if any(keyword in food_lower for keyword in high_fiber):
        return (amount_g / 100) * 5  # ~5г на 100г

    # Среднее содержание клетчатки (2-4 г на 100г)
    medium_fiber = [
        "каша",
        "греч",
        "рис",
        "овсянка",
        "porridge",
        "buckwheat",
        "rice",
        "oatmeal",
        "цельнозерновой",
        "whole grain",
        "крупа",
        "зерн",
        "огурец",
        "помидор",
        "томат",
        "перец",
        "морковь",
        "свекла",
        "зелень",
        "салат",
        "лук",
        "картофель",
        "картошка",
        "potato",
        "onion",
        "суп",
        "soup",
        "борщ",
        "щи",
        "фрукт",
        "яблоко",
        "груша",
        "мандарин",
        "апельсин",
        "цитрус",
        "ягода",
        "хлеб",
        "bread",
        "cucumber",
        "tomato",
        "pepper",
        "carrot",
        "beet",
        "fruit",
        "apple",
        "pear",
        "berry",
    ]
    if any(keyword in food_lower for keyword in medium_fiber):
        return (amount_g / 100) * 2  # ~2г на 100г

    return 0.0


def analyze_weekly_nutrition(user_id: int, last_7_days: bool = True) -> Dict:
    """
    Анализирует питание за неделю (последние 7 дней) из PostgreSQL

    Args:
        user_id: Telegram ID пользователя
        last_7_days: Всегда True (для совместимости)

    Returns:
        Словарь с агрегированными данными и рекомендациями
    """
    # Определяем даты для анализа
    dates_to_analyze = get_last_7_days()
    start_date = dates_to_analyze[-1]
    end_date = dates_to_analyze[0]

    db = SessionLocal()
    try:
        # Получаем все записи питания за период
        nutrition_logs = get_nutrition_logs_by_period(db, user_id, start_date, end_date)

        # Получаем добавки за период (для учета псиллиума)
        supplements = get_supplements_by_period(db, user_id, start_date, end_date)

        # Получаем активность Garmin за период
        activity_logs = get_activity_logs_by_period(db, user_id, start_date, end_date)

        # Группируем добавки по дате
        supplements_by_date = defaultdict(list)
        for supp in supplements:
            supplements_by_date[supp.date].append(supp.supplement_name.lower())

        # Считаем дни с псиллиумом для клетчатки
        psyllium_days = set()
        for date_key, supps in supplements_by_date.items():
            if any("псилл" in s or "psyll" in s for s in supps):
                psyllium_days.add(date_key)

        # Расчет TDEE
        total_active_cal = sum(log.active_calories or 0 for log in activity_logs)
        days_with_activity = len([log for log in activity_logs if log.active_calories])
        avg_active_cal = total_active_cal / max(days_with_activity, 1)

        # BMR (базовый обмен веществ) - можно рассчитать по формуле или взять из Garmin
        # Используем среднее BMR из Garmin или стандартное значение 1700
        bmr_values = [log.bmr_calories for log in activity_logs if log.bmr_calories]
        avg_bmr = sum(bmr_values) / len(bmr_values) if bmr_values else 1700.0

        # TDEE = BMR + активные калории
        avg_tdee = avg_bmr + avg_active_cal

        # Агрегируем данные
        totals = {
            "calories": 0.0,
            "protein": 0.0,
            "fats": 0.0,
            "carbs": 0.0,
            "fiber": 0.0,
            "avg_tdee": avg_tdee,
            "avg_bmr": avg_bmr,
            "avg_active_cal": avg_active_cal,
        }

        categories = {
            "fatty_fish_portions": 0,
            "red_meat_portions": 0,
            "processed_meat_portions": 0,
            "high_carb_dinners": 0,
            "alcohol_days": set(),
        }

        # Проходим по всем записям
        days_with_data = set()

        for log in nutrition_logs:
            days_with_data.add(log.date)

            # Суммируем totals
            log_totals = log.totals or {}
            totals["calories"] += log_totals.get("calories", 0.0)
            totals["protein"] += log_totals.get("protein", 0.0)
            totals["fats"] += log_totals.get("fats", 0.0)
            totals["carbs"] += log_totals.get("carbs", 0.0)

            # Анализируем items
            has_alcohol_today = False
            has_high_carb_dinner = False

            meal_name = log.meal_name.lower() if log.meal_name else ""
            is_dinner = "ужин" in meal_name or "dinner" in meal_name or "вечер" in meal_name

            for item in log.items or []:
                # Поддержка обоих форматов ключей в JSON (БД использует name/weight)
                food_name = item.get("name") or item.get("food") or ""
                amount_g = item.get("weight") or item.get("amount", 0.0) or 0.0

                # Категоризация
                item_categories = categorize_food_item(food_name, meal_name if is_dinner else None)

                if item_categories["fatty_fish"]:
                    portions = amount_g / 175
                    categories["fatty_fish_portions"] += portions

                if item_categories["red_meat"]:
                    portions = amount_g / 150
                    categories["red_meat_portions"] += portions

                if item_categories["processed_meat"]:
                    portions = amount_g / 100
                    categories["processed_meat_portions"] += portions

                if item_categories["high_carb_dinner"] and is_dinner:
                    has_high_carb_dinner = True

                if item_categories["alcohol"]:
                    has_alcohol_today = True

                # Оценка клетчатки из еды
                totals["fiber"] += estimate_fiber(food_name, amount_g)

            if has_high_carb_dinner:
                categories["high_carb_dinners"] += 1

            if has_alcohol_today:
                categories["alcohol_days"].add(log.date)

        # Добавляем клетчатку из псиллиума (2 ч.л. = ~10г клетчатки)
        totals["fiber"] += len(psyllium_days) * 10.0

        # Преобразуем alcohol_days
        categories["alcohol_days_count"] = len(categories["alcohol_days"])
        categories["alcohol_days"] = [d.isoformat() for d in categories["alcohol_days"]]

        # Генерируем рекомендации
        recommendations = generate_weekly_recommendations(totals, categories, [d.isoformat() for d in dates_to_analyze])

        return {
            "week_start": start_date.isoformat(),
            "dates_analyzed": [d.isoformat() for d in dates_to_analyze],
            "days_with_data": len(days_with_data),
            "totals": totals,
            "categories": categories,
            "recommendations": recommendations,
        }

    finally:
        db.close()


def generate_weekly_recommendations(totals: Dict, categories: Dict, dates_analyzed: List[str]) -> List[str]:
    """Генерирует рекомендации на основе недельного анализа"""
    recommendations = []

    # A) Жирная рыба
    fatty_fish_portions = categories.get("fatty_fish_portions", 0)

    if fatty_fish_portions < 2:
        missing_portions = 2 - fatty_fish_portions
        recommendations.append(
            f"🐟 Жирная рыба: за неделю {fatty_fish_portions:.1f} порций из 2 рекомендуемых. "
            f"Добавьте {missing_portions:.1f} порции (лосось/скумбрия/сардина 150-200г)"
        )

    # B) Красное мясо и переработанное
    red_meat_portions = categories.get("red_meat_portions", 0)
    processed_portions = categories.get("processed_meat_portions", 0)

    if red_meat_portions >= 3:
        recommendations.append("⚠️ Красное мясо: более 3 порций за неделю. Замените часть на рыбу/птицу/бобовые")

    if processed_portions >= 1:
        recommendations.append("⚠️ Переработанное мясо: есть в рационе. Лучше заменить на свежее мясо/рыбу")

    # C) Углеводы вечером
    high_carb_dinners = categories.get("high_carb_dinners", 0)
    if high_carb_dinners >= 3:
        recommendations.append(
            f"🍞 Высокоуглеводные ужины: {high_carb_dinners} раз за неделю. "
            "Переносите углеводы на обед или после тренировки"
        )

    # D) Клетчатка
    fiber_avg = totals.get("fiber", 0) / len(dates_analyzed) if dates_analyzed else 0
    if fiber_avg < 25:
        recommendations.append(
            f"🥬 Клетчатка: {fiber_avg:.0f}г/день (норма 30+). Увеличьте овощи, бобовые, крупы, псиллиум"
        )

    # E) Алкоголь
    alcohol_days = categories.get("alcohol_days_count", 0)
    if alcohol_days > 2:
        recommendations.append(
            f"🍷 Алкоголь: {alcohol_days} дней за неделю (рекомендуется макс 2). "
            "Избегайте поздно вечером для лучшего сна"
        )

    return recommendations
