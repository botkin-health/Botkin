#!/usr/bin/env python3
"""
Работа с хранилищем данных (YAML файлы и JSON)
"""

import yaml
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import os
from os import getenv


# Определяем корневую директорию HealthVault
HEALTHVAULT_ROOT = Path(__file__).parent.parent

# Директории для логов
NUTRITION_LOG_DIR = HEALTHVAULT_ROOT / 'data' / 'logs' / 'nutrition'
SUPPLEMENTS_LOG_DIR = HEALTHVAULT_ROOT / 'data' / 'logs' / 'supplements'
MEDIA_DIR = HEALTHVAULT_ROOT / 'data' / 'media' / 'nutrition'

# Создаем директории, если их нет
for dir_path in [NUTRITION_LOG_DIR, SUPPLEMENTS_LOG_DIR, MEDIA_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)


def load_nutrition_log(date: Optional[str] = None) -> Dict:
    """
    Загружает лог питания за указанную дату.
    
    Args:
        date: Дата в формате YYYY-MM-DD (если None, используется сегодня)
        
    Returns:
        Словарь с данными питания
    """
    if date is None:
        date = datetime.now().strftime('%Y-%m-%d')
    
    log_file = NUTRITION_LOG_DIR / f"{date}.yaml"
    
    if not log_file.exists():
        return {
            'date': date,
            'meals': []
        }
    
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {'date': date, 'meals': []}
    except Exception as e:
        print(f"Ошибка при загрузке лога питания: {e}")
        return {'date': date, 'meals': []}


def save_nutrition_log(data: Dict, date: Optional[str] = None):
    """
    Сохраняет лог питания за указанную дату.
    
    Args:
        data: Данные для сохранения
        date: Дата в формате YYYY-MM-DD (если None, используется сегодня)
    """
    if date is None:
        date = datetime.now().strftime('%Y-%m-%d')
    
    log_file = NUTRITION_LOG_DIR / f"{date}.yaml"
    
    try:
        # Убеждаемся, что дата указана
        if 'date' not in data:
            data['date'] = date
        
        with open(log_file, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
    except Exception as e:
        print(f"Ошибка при сохранении лога питания: {e}")


def add_meal(meal_data: Dict, date: Optional[str] = None):
    """
    Добавляет прием пищи в лог.
    
    Args:
        meal_data: Данные о приеме пищи
        date: Дата в формате YYYY-MM-DD (если None, используется сегодня)
    """
    log_data = load_nutrition_log(date)
    
    if 'meals' not in log_data:
        log_data['meals'] = []
    
    log_data['meals'].append(meal_data)
    save_nutrition_log(log_data, date)


def get_today_totals() -> Dict:
    """
    Получает общие КБЖУ за сегодня.
    Читает из data/nutrition/nutrition_log.json (основная база).
    
    Returns:
        Словарь с общими КБЖУ: {'calories': 0, 'protein': 0, 'fats': 0, 'carbs': 0}
    """
    today = datetime.now().strftime('%Y-%m-%d')
    
    totals = {
        'calories': 0.0,
        'protein': 0.0,
        'fats': 0.0,
        'carbs': 0.0,
    }
    
    # Пробуем загрузить из основного JSON файла
    nutrition_json = HEALTHVAULT_ROOT / 'data' / 'nutrition' / 'nutrition_log.json'
    if nutrition_json.exists():
        try:
            with open(nutrition_json, 'r', encoding='utf-8') as f:
                nutrition_data = json.load(f)
            
            # Ищем запись за сегодня
            for entry in nutrition_data.get('entries', []):
                if entry.get('date') == today:
                    entry_totals = entry.get('totals', {})
                    totals['calories'] = entry_totals.get('calories', 0.0)
                    totals['protein'] = entry_totals.get('protein', 0.0)
                    totals['fats'] = entry_totals.get('fats', 0.0)
                    totals['carbs'] = entry_totals.get('carbs', 0.0)
                    return totals
        except Exception as e:
            print(f"Ошибка при загрузке из nutrition_log.json: {e}")
    
    # Если не нашли в JSON, пробуем YAML (старый формат)
    log_data = load_nutrition_log(today)
    for meal in log_data.get('meals', []):
        meal_totals = meal.get('meal_totals', {})
        totals['calories'] += meal_totals.get('calories', 0)
        totals['protein'] += meal_totals.get('protein', 0)
        totals['fats'] += meal_totals.get('fats', 0)
        totals['carbs'] += meal_totals.get('carbs', 0)
    
    # Округляем
    for key in totals:
        totals[key] = round(totals[key], 1)
    
    return totals

