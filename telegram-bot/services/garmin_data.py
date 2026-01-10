#!/usr/bin/env python3
"""
Работа с данными Garmin для бота
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional

# Определяем корневую директорию HealthVault
HEALTHVAULT_ROOT = Path(__file__).parent.parent.parent
GARMIN_DIR = HEALTHVAULT_ROOT / 'data' / 'garmin' / 'daily-summary'


def get_garmin_data_for_date(date: str) -> Optional[Dict]:
    """
    Получает данные Garmin за указанную дату.
    
    Args:
        date: Дата в формате YYYY-MM-DD
        
    Returns:
        Словарь с данными Garmin или None
    """
    file_path = GARMIN_DIR / f"{date}.json"
    
    if not file_path.exists():
        return None
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('stats', {})
    except Exception as e:
        print(f"Ошибка при загрузке данных Garmin: {e}")
        return None


def get_average_calories(days: int = 14) -> float:
    """
    Получает средний расход калорий за последние N дней.
    Игнорирует дни с нулевыми значениями.
    Отрубает выбросы (max и min), если данных достаточно (>10 дней).
    
    Args:
        days: Количество дней для расчета среднего (дефолт 14)
        
    Returns:
        Средний расход калорий
    """
    daily_calories = []
    
    # Собираем данные
    for i in range(days):
        date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
        garmin_data = get_garmin_data_for_date(date)
        
        if garmin_data:
            calories = garmin_data.get('totalKilocalories', 0)
            if calories and calories > 1000: # Фильтр совсем битых данных
                daily_calories.append(calories)
                
    count = len(daily_calories)
    if count == 0:
        return 0.0
        
    # Если данных достаточно (>= 10), убираем 1 максимум и 1 минимум (выбросы)
    if count >= 10:
        daily_calories.sort()
        # Убираем первый (мин) и последний (макс)
        daily_calories = daily_calories[1:-1]
        
    if not daily_calories:
        return 0.0
        
    avg = sum(daily_calories) / len(daily_calories)
    return round(avg, 1)




