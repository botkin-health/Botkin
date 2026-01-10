#!/usr/bin/env python3
"""
Недельный учёт питания с категориями и коррекциями
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

# Определяем корневую директорию HealthVault
HEALTHVAULT_ROOT = Path(__file__).parent.parent.parent
NUTRITION_LOG = HEALTHVAULT_ROOT / 'data' / 'nutrition' / 'nutrition_log.json'


def get_week_start(date_str: str = None) -> str:
    """Возвращает дату начала недели (понедельник) для указанной даты"""
    if date_str is None:
        date_str = datetime.now().strftime('%Y-%m-%d')
    
    date_obj = datetime.strptime(date_str, '%Y-%m-%d')
    # Понедельник = 0, воскресенье = 6
    days_since_monday = date_obj.weekday()
    week_start = date_obj - timedelta(days=days_since_monday)
    return week_start.strftime('%Y-%m-%d')


def get_last_7_days() -> List[str]:
    """Возвращает список дат за последние 7 дней"""
    today = datetime.now()
    dates = []
    for i in range(7):
        date = today - timedelta(days=i)
        dates.append(date.strftime('%Y-%m-%d'))
    return dates


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
        'fatty_fish': False,
        'red_meat': False,
        'processed_meat': False,
        'high_carb_dinner': False,
        'alcohol': False,
    }
    
    # Жирная рыба
    fatty_fish_keywords = ['лосось', 'скумбрия', 'сардина', 'сельдь', 'salmon', 'mackerel', 'sardine', 'herring']
    if any(keyword in food_lower for keyword in fatty_fish_keywords):
        categories['fatty_fish'] = True
    
    # Красное мясо
    red_meat_keywords = ['говядина', 'свинина', 'баранина', 'beef', 'pork', 'lamb', 'стейк', 'steak']
    if any(keyword in food_lower for keyword in red_meat_keywords):
        categories['red_meat'] = True
    
    # Переработанное мясо
    processed_keywords = ['колбаса', 'сосиски', 'ветчина', 'бекон', 'sausage', 'ham', 'bacon', 'салями']
    if any(keyword in food_lower for keyword in processed_keywords):
        categories['processed_meat'] = True
    
    # Углеводы вечером (определяем по meal_time или по названию блюда)
    if meal_time:
        meal_lower = meal_time.lower()
        is_dinner = 'ужин' in meal_lower or 'dinner' in meal_lower or 'вечер' in meal_lower
        if is_dinner:
            high_carb_keywords = ['каша', 'рис', 'макароны', 'пюре', 'хлеб', 'картофель', 'гречка', 'porridge', 'rice', 'pasta', 'bread', 'potato']
            if any(keyword in food_lower for keyword in high_carb_keywords):
                categories['high_carb_dinner'] = True
    
    # Алкоголь
    alcohol_keywords = ['алкоголь', 'вино', 'пиво', 'водка', 'виски', 'wine', 'beer', 'vodka', 'whiskey', 'guinness']
    if any(keyword in food_lower for keyword in alcohol_keywords):
        categories['alcohol'] = True
    
    return categories


def estimate_fiber(food_name: str, amount_g: float) -> float:
    """
    Оценивает количество клетчатки в продукте (очень приблизительно)
    """
    food_lower = food_name.lower()
    
    # Высокое содержание клетчатки (5-10 г на 100г)
    high_fiber = ['овощи', 'фасоль', 'бобовые', 'овощ', 'капуста', 'брокколи', 'шпинат', 'овощной', 'vegetable', 'beans', 'legumes', 'cabbage', 'broccoli', 'spinach']
    if any(keyword in food_lower for keyword in high_fiber):
        return (amount_g / 100) * 5  # ~5г на 100г
    
    # Среднее содержание клетчатки (2-4 г на 100г)
    medium_fiber = ['каша', 'гречка', 'рис', 'овсянка', 'porridge', 'buckwheat', 'rice', 'oatmeal', 'цельнозерновой', 'whole grain']
    if any(keyword in food_lower for keyword in medium_fiber):
        return (amount_g / 100) * 2  # ~2г на 100г
    
    # Низкое содержание клетчатки
    return 0.0


def analyze_weekly_nutrition(week_start: str = None, last_7_days: bool = False) -> Dict:
    """
    Анализирует питание за неделю (с понедельника) или за последние 7 дней
    
    Returns:
        Словарь с агрегированными данными и рекомендациями
    """
    if not NUTRITION_LOG.exists():
        return {
            'error': 'nutrition_log.json не найден',
            'week_start': week_start,
            'totals': {},
            'categories': {},
            'recommendations': []
        }
    
    try:
        with open(NUTRITION_LOG, 'r', encoding='utf-8') as f:
            nutrition_data = json.load(f)
    except Exception as e:
        return {
            'error': f'Ошибка при загрузке nutrition_log.json: {e}',
            'week_start': week_start,
            'totals': {},
            'categories': {},
            'recommendations': []
        }
    
    # Определяем даты для анализа
    if last_7_days:
        dates_to_analyze = get_last_7_days()
        week_start = dates_to_analyze[-1]  # Самая ранняя дата
    else:
        if week_start is None:
            week_start = get_week_start()
        
        # Генерируем даты недели (понедельник-воскресенье)
        start_date = datetime.strptime(week_start, '%Y-%m-%d')
        dates_to_analyze = []
        for i in range(7):
            date = start_date + timedelta(days=i)
            dates_to_analyze.append(date.strftime('%Y-%m-%d'))
    
    # Агрегируем данные
    totals = {
        'calories': 0.0,
        'protein': 0.0,
        'fats': 0.0,
        'carbs': 0.0,
        'fiber': 0.0,
    }
    
    categories = {
        'fatty_fish_portions': 0,  # Порции жирной рыбы (150-200г = 1 порция)
        'red_meat_portions': 0,    # Порции красного мяса
        'processed_meat_portions': 0,  # Порции переработанного мяса
        'high_carb_dinners': 0,    # Количество высокоуглеводных ужинов
        'alcohol_days': set(),      # Дни с алкоголем
    }
    
    # Проходим по всем записям
    valid_days_count = 0
    for entry in nutrition_data.get('entries', []):
        entry_date = entry.get('date')
        if entry_date not in dates_to_analyze:
            continue
            
        valid_days_count += 1
        
        # Суммируем totals
        entry_totals = entry.get('totals', {})
        totals['calories'] += entry_totals.get('calories', 0.0)
        totals['protein'] += entry_totals.get('protein', 0.0)
        totals['fats'] += entry_totals.get('fats', 0.0)
        totals['carbs'] += entry_totals.get('carbs', 0.0)
        
        # Анализируем meals
        has_alcohol_today = False
        has_high_carb_dinner = False
        
        for meal in entry.get('meals', []):
            meal_name = meal.get('meal', '').lower()
            is_dinner = 'ужин' in meal_name or 'dinner' in meal_name or 'вечер' in meal_name
            
            for item in meal.get('items', []):
                food_name = item.get('food', '')
                amount_g = item.get('amount', 0.0) or 0.0
                
                # Категоризация
                item_categories = categorize_food_item(food_name, meal_name if is_dinner else None)
                
                if item_categories['fatty_fish']:
                    # Считаем порции (150-200г = 1 порция)
                    portions = amount_g / 175  # Среднее 175г
                    categories['fatty_fish_portions'] += portions
                
                if item_categories['red_meat']:
                    portions = amount_g / 150  # Примерно 150г = 1 порция
                    categories['red_meat_portions'] += portions
                
                if item_categories['processed_meat']:
                    portions = amount_g / 100  # Примерно 100г = 1 порция
                    categories['processed_meat_portions'] += portions
                
                if item_categories['high_carb_dinner'] and is_dinner:
                    has_high_carb_dinner = True
                
                if item_categories['alcohol']:
                    has_alcohol_today = True
                
                # Оценка клетчатки
                totals['fiber'] += estimate_fiber(food_name, amount_g)
        
        if has_high_carb_dinner:
            categories['high_carb_dinners'] += 1
        
        if has_alcohol_today:
            categories['alcohol_days'].add(entry_date)
    
    # Преобразуем alcohol_days в количество
    categories['alcohol_days_count'] = len(categories['alcohol_days'])
    categories['alcohol_days'] = list(categories['alcohol_days'])
    
    # Генерируем рекомендации
    recommendations = generate_weekly_recommendations(totals, categories, dates_to_analyze)
    
    return {
        'week_start': week_start,
        'dates_analyzed': dates_to_analyze,
        'days_with_data': valid_days_count,
        'totals': totals,
        'categories': categories,
        'recommendations': recommendations
    }


def generate_weekly_recommendations(totals: Dict, categories: Dict, dates_analyzed: List[str]) -> List[str]:
    """
    Генерирует рекомендации на основе недельного анализа
    """
    recommendations = []
    
    # A) Жирная рыба
    fatty_fish_portions = categories.get('fatty_fish_portions', 0)
    today = datetime.now()
    weekday = today.weekday()  # 0 = понедельник, 6 = воскресенье
    
    if weekday <= 3:  # Понедельник-четверг
        if fatty_fish_portions < 1:
            recommendations.append("🐟 Жирная рыба: к четвергу 0-1 порция. План: добавить в пт + вс (лосось/скумбрия/сардина 150-200г)")
    elif fatty_fish_portions < 2:
        recommendations.append("🐟 Жирная рыба: за неделю &lt; 2 порций. Добавить до конца недели (лосось/скумбрия/сардина 150-200г)")
    
    # B) Красное мясо и переработанное
    red_meat_portions = categories.get('red_meat_portions', 0)
    processed_portions = categories.get('processed_meat_portions', 0)
    
    if red_meat_portions >= 3:
        recommendations.append("⚠️ Красное мясо ≥3 порции/нед. Рекомендация: заменить на рыбу/птицу/бобовые")
    
    if processed_portions >= 1:
        recommendations.append("⚠️ Переработанное мясо ≥1 порция/нед. Рекомендация: заменить на рыбу/птицу/бобовые")
    
    # C) Углеводы вечером
    high_carb_dinners = categories.get('high_carb_dinners', 0)
    if high_carb_dinners >= 3:
        recommendations.append("🍞 Высокоуглеводные ужины ≥3 раза за последние 5 дней. Сегодня: белок + овощи, углеводы перенести на обед/после тренировки")
    
    # D) Клетчатка
    fiber_avg = totals.get('fiber', 0) / len(dates_analyzed) if dates_analyzed else 0
    if fiber_avg < 25:  # Меньше 25г в день в среднем
        recommendations.append("🥬 Клетчатка: мало овощей/бобовых/цельных круп. Добавить 1-2 простых добора сегодня (овощи, бобовые, цельные крупы)")
    
    # E) Алкоголь
    alcohol_days = categories.get('alcohol_days_count', 0)
    if alcohol_days > 2:
        recommendations.append("🍷 Алкоголь: &gt;2 дней/нед. Рекомендация: ≤2 дней/нед, избегать поздно вечером (храп/АД/сон)")
    
    return recommendations
