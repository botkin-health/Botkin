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


# Импорт библиотеки (пытаемся, чтобы не падать если нет)
try:
    from garminconnect import Garmin
except ImportError:
    Garmin = None

import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

def update_today_data() -> bool:
    """
    Обновляет данные Garmin за сегодня.
    Возвращает True если успешно, False если ошибка.
    """
    if Garmin is None:
        logger.error("Library 'garminconnect' not found")
        return False
        
    email = os.getenv('GARMIN_EMAIL')
    password = os.getenv('GARMIN_PASSWORD')
    
    if not email or not password:
        logger.error("No Garmin credentials in .env")
        return False
        
    try:
        # 1. Auth
        client = Garmin(email, password)
        client.login()
        
        # 2. Get Date
        today_str = datetime.now().strftime('%Y-%m-%d')
        
        # 3. Fetch Data
        # Daily Stats
        stats = client.get_stats(today_str)
        
        # Combine (simple version for now: mainly stats)
        summary = {
            'stats': stats
        }
        
        # Try steps if available
        try:
             daily_steps = client.get_daily_steps(today_str)
             summary['daily_steps'] = daily_steps
        except:
             pass

        # 4. Save
        file_path = GARMIN_DIR / f"{today_str}.json"
        
        # Ensure dir
        GARMIN_DIR.mkdir(parents=True, exist_ok=True)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
            
        return True
        
    except Exception as e:
        logger.error(f"Error updating Garmin data: {e}")
        return False




