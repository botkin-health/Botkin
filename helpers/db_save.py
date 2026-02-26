"""
Database save functions - PostgreSQL Version

Заменяет save_meal_to_json и save_weight_measurement
для работы с PostgreSQL вместо JSON.
Время и дата при сохранении — по Москве (UTC+3).
"""

import logging
from datetime import datetime, time as time_type, timezone, timedelta
from typing import Dict, Any, Optional

MSK = timezone(timedelta(hours=3))

from database import (
    SessionLocal,
    create_nutrition_log,
    create_weight,
    create_supplement_log
)

logger = logging.getLogger(__name__)


def save_meal_to_db(meal_data: dict, meal_name: str = None, user_id: int = 895655) -> bool:
    """
    Сохраняет приём пищи в PostgreSQL
    
    Args:
        meal_data: Данные о приёме пищи из состояния
        meal_name: Название приёма пищи
        user_id: Telegram ID пользователя
        
    Returns:
        True if successful
    """
    try:
        # Определяем дату
        custom_date = meal_data.get('date')
        if custom_date:
            if isinstance(custom_date, str):
                meal_date = datetime.strptime(custom_date, '%Y-%m-%d').date()
            else:
                meal_date = custom_date
        else:
            meal_date = datetime.now(MSK).date()
        
        # Определяем время (по Москве)
        meal_time_str = meal_data.get('meal_time', datetime.now(MSK).strftime('%H:%M'))
        try:
            meal_time = datetime.strptime(meal_time_str, '%H:%M').time()
        except:
            meal_time = datetime.now(MSK).time()
        
        # Название приёма пищи
        if not meal_name:
            meal_name = meal_data.get('dish_name') or meal_data.get('meal_name') or 'Приём пищи'
        
        # Формируем items
        meal_items = meal_data.get('meal_items', [])
        items = []
        for item in meal_items:
            items.append({
                'food': item.get('product', 'Неизвестный продукт'),
                'amount': item.get('weight_g', 0.0),
                'unit': 'г',
                'calories': int(round(item.get('calories', 0.0))),
                'protein': int(round(item.get('protein', 0.0))),
                'fats': int(round(item.get('fats', 0.0))),
                'carbs': int(round(item.get('carbs', 0.0))),
            })
        
        # Totals
        meal_totals = meal_data.get('meal_totals', {})
        totals = {
            'calories': int(round(meal_totals.get('calories', 0.0))),
            'protein': int(round(meal_totals.get('protein', 0.0))),
            'fats': int(round(meal_totals.get('fats', 0.0))),
            'carbs': int(round(meal_totals.get('carbs', 0.0))),
        }
        
        # Фото
        photo_paths = meal_data.get('photo_paths', [])
        if isinstance(photo_paths, list):
            photo_paths = [str(p) for p in photo_paths]
        else:
            photo_paths = []
        
        # Сохраняем в БД
        db = SessionLocal()
        try:
            create_nutrition_log(
                db,
                user_id=user_id,
                date=meal_date,
                meal_time=meal_time,
                meal_name=meal_name,
                items=items,
                totals=totals,
                photo_paths=photo_paths
            )
            logger.info(f"Meal saved to DB: {meal_name} on {meal_date} at {meal_time}")
            return True
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error saving meal to DB: {e}", exc_info=True)
        return False


def save_weight_to_db(data: Dict[str, Any], user_id: int = 895655) -> str:
    """
    Saves a weight measurement to PostgreSQL
    
    Args:
        data: Dict containing weight, date, source, etc.
        user_id: Telegram ID пользователя
        
    Returns:
        String confirmation or empty string on error
    """
    try:
        # Определяем дату и время
        date_input = data.get('date')
        if not date_input:
            measured_at = datetime.now()
        else:
            date_str = str(date_input)
            
            # Парсинг даты
            try:
                if "T" in date_str:
                    measured_at = datetime.fromisoformat(date_str)
                elif ' ' in date_str and ':' in date_str:
                    # "2025-08-03 09:27"
                    measured_at = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
                elif len(date_str) == 10 and "-" in date_str:
                    # "2025-08-03"
                    measured_at = datetime.strptime(date_str, "%Y-%m-%d")
                else:
                    measured_at = datetime.now()
            except:
                measured_at = datetime.now()
        
        # Извлекаем данные
        weight = data.get('weight')
        body_fat = data.get('body_fat')
        muscle_mass = data.get('muscle_mass')
        water = data.get('water')
        bmi = data.get('bmi')
        visceral_fat = data.get('visceral_fat')
        bone_mass = data.get('bone_mass')
        source = data.get('source', 'manual')
        
        # Сохраняем в БД
        db = SessionLocal()
        try:
            create_weight(
                db,
                user_id=user_id,
                measured_at=measured_at,
                weight=weight,
                body_fat=body_fat,
                muscle_mass=muscle_mass,
                water=water,
                bmi=bmi,
                visceral_fat=visceral_fat,
                bone_mass=bone_mass,
                source=source
            )
            logger.info(f"Weight saved to DB: {weight}kg on {measured_at}")
            return f"Saved to DB: {measured_at.strftime('%Y-%m-%d %H:%M')}"
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error saving weight to DB: {e}", exc_info=True)
        return ""


def save_supplements_to_db(items: list, user_id: int = 895655, date_str: Optional[str] = None) -> bool:
    """
    Сохраняет добавки в PostgreSQL
    
    Args:
        items: Список названий добавок
        user_id: Telegram ID пользователя
        date_str: Дата в формате YYYY-MM-DD (если None - сегодня)
        
    Returns:
        True if successful
    """
    if not items:
        return False
        
    try:
        # Дата
        if date_str:
            supplement_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            supplement_date = datetime.now().date()
        
        # Время
        supplement_time = datetime.now().time()
        
        # Сохраняем
        db = SessionLocal()
        try:
            for item in items:
                create_supplement_log(
                    db,
                    user_id=user_id,
                    date=supplement_date,
                    time=supplement_time,
                    supplement_name=item,
                    dosage=None
                )
            logger.info(f"Supplements saved to DB: {items}")
            return True
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error saving supplements to DB: {e}", exc_info=True)
        return False
