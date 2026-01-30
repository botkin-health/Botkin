#!/usr/bin/env python3
"""
Работа с данными Garmin для бота - PostgreSQL Version
"""

import logging
from datetime import datetime, timedelta, date as date_type
from typing import Dict, Optional

from database import SessionLocal, get_activity_by_date, get_average_activity_stats

logger = logging.getLogger(__name__)


def get_garmin_data_for_date(date: str, user_id: int = 895655) -> Optional[Dict]:
    """
    Получает данные Garmin/Activity за указанную дату из PostgreSQL
    
    Args:
        date: Дата в формате YYYY-MM-DD
        user_id: Telegram ID пользователя
        
    Returns:
        Словарь с данными или None
    """
    try:
        target_date = datetime.strptime(date, '%Y-%m-%d').date()
    except ValueError:
        return None
    
    db = SessionLocal()
    try:
        activity = get_activity_by_date(db, user_id, target_date)
        
        if not activity:
            return None
        
        # Return in old format for compatibility
        return {
            'totalKilocalories': activity.total_calories,
            'activeKilocalories': activity.active_calories,
            'bmrKilocalories': activity.bmr_calories,
            'totalSteps': activity.steps,
            'totalDistanceMeters': activity.distance_km * 1000 if activity.distance_km else None,
            'sleepingSeconds': activity.sleep_hours * 3600 if activity.sleep_hours else None,
            'averageHeartRate': activity.heart_rate_avg,
            'averageStressLevel': activity.stress_level,
        }
    finally:
        db.close()


def get_average_stats(days: int = 14, user_id: int = 895655) -> Dict[str, float]:
    """
    Получает средние показатели (BMR, Active, Total) за последние N дней из PostgreSQL
    Игнорирует дни с некорректными данными (total < 1200 ккал).
    
    Args:
        days: Количество дней для анализа
        user_id: Telegram ID пользователя
        
    Returns:
        Dict с ключами 'bmr', 'active', 'total', 'count'
    """
    db = SessionLocal()
    try:
        avg_stats = get_average_activity_stats(db, user_id, days=days)
        
        if not avg_stats:
            # Fallback to defaults
            return {
                'bmr': 1750.0,
                'active': 400.0,
                'total': 2150.0,
                'count': 0
            }
        
        return {
            'bmr': avg_stats.get('bmr_calories', 1750.0),
            'active': avg_stats.get('active_calories', 400.0),
            'total': avg_stats.get('total_calories', 2150.0),
            'count': avg_stats.get('count', 0)
        }
    finally:
        db.close()


def sync_garmin_data(user_id: int = 895655):
    """
    Синхронизирует данные Garmin
    
    TODO: В будущем здесь будет автоматическая синхронизация с Garmin API
    Пока данные уже синхронизированы через миграцию и периодический sync скрипт
    
    Args:
        user_id: Telegram ID пользователя
    """
    logger.info(f"Garmin sync called for user {user_id}")
    # Currently data is synced via scheduled jobs or manual migration
    # This is a placeholder for future Garmin Connect API integration
    pass

