#!/usr/bin/env python3
"""
Garmin data synchronization and retrieval functions
"""

import logging
from datetime import datetime, date as date_type, timedelta
from typing import Optional, Dict
from database import SessionLocal, get_activity_by_date, get_last_activity_date

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


def get_average_stats(days: int = 7, user_id: int = 895655) -> Dict:
    """
    Получает средние показатели за последние N дней
    
    Args:
        days: Количество дней для анализа
        user_id: Telegram ID пользователя
        
    Returns:
        Словарь со средними значениями
    """
    from database import get_activity_logs_by_period
    
    db = SessionLocal()
    try:
        end_date = date_type.today()
        start_date = end_date - timedelta(days=days-1)
        
        logs = get_activity_logs_by_period(db, user_id, start_date, end_date)
        
        if not logs:
            return {
                'avg_steps': 0,
                'avg_active_calories': 0,
                'avg_total_calories': 0
            }
        
        total_steps = sum(log.steps or 0 for log in logs)
        total_active = sum(log.active_calories or 0 for log in logs)
        total_cal = sum(log.total_calories or 0 for log in logs)
        
        return {
            'avg_steps': total_steps / len(logs),
            'avg_active_calories': total_active / len(logs),
            'avg_total_calories': total_cal / len(logs)
        }
    finally:
        db.close()


def sync_garmin_data(user_id: int = 895655, sync_date: Optional[date_type] = None):
    """
    Синхронизирует данные Garmin за сегодня или за указанную дату
    
    Args:
        user_id: Telegram ID пользователя
        sync_date: Дата для синхронизации (по умолчанию сегодня)
    """
    logger.info(f"Garmin sync called for user {user_id}, date: {sync_date}")
    
    # 1. Get credentials
    import os
    from database import get_user_by_telegram_id, create_or_update_activity
    
    db = SessionLocal()
    try:
        user = get_user_by_telegram_id(db, user_id)
        email = None
        password = None
        
        # Priority: DB > ENV
        if user and user.garmin_email and user.garmin_password:
            email = user.garmin_email
            password = user.garmin_password
        else:
            email = os.getenv('GARMIN_EMAIL')
            password = os.getenv('GARMIN_PASSWORD')
            
        if not email or not password:
            logger.warning(f"No Garmin credentials for user {user_id}")
            return

        # 2. Connect to Garmin
        try:
            from garminconnect import Garmin
            client = Garmin(email, password)
            client.login()
        except ImportError:
             logger.error("garminconnect library not installed")
             return
        except Exception as e:
            logger.error(f"Garmin login failed: {e}")
            return
            
        # 3. Get Data (Default to today)
        target_date = sync_date if sync_date else date_type.today()
        target_date_str = target_date.strftime('%Y-%m-%d')
        
        try:
            stats = client.get_stats(target_date_str)
            # steps = client.get_steps_data(today_str) # Optional for more details
        except Exception as e:
            logger.error(f"Failed to fetch Garmin stats for {target_date_str}: {e}")
            return
            
        if not stats:
            logger.info(f"No stats available for {target_date_str}")
            return
            
        # 4. Save to DB
        create_or_update_activity(
            db=db,
            user_id=user_id,
            date=target_date,
            steps=stats.get('dailyStepCount'),
            active_calories=stats.get('activeKilocalories'),
            total_calories=stats.get('totalKilocalories'),
            bmr_calories=stats.get('bmrKilocalories'),
            distance_km=(stats.get('totalDistanceMeters') or 0) / 1000.0,
            # Basic stats often don't have sleep/stress/hrv instantly, 
            # they require separate calls or sync delay.
            # We map what's available in 'get_stats' response.
            source='garmin_connect',
            raw_data=stats
        )
        return True
        
    except Exception as e:
        logger.error(f"Error in sync_garmin_data: {e}", exc_info=True)
        return False
    finally:
        db.close()


def sync_missing_garmin_days(user_id: int = 895655):
    """
    Умная синхронизация: синхронизирует только недостающие дни
    
    Синхронизируется с последней даты в БД (полностью) до сегодня (включительно)
    Это позволяет обновить частичные данные за последний день и добавить новые
    
    Args:
        user_id: Telegram ID пользователя
    """
    logger.info(f"Smart Garmin sync started for user {user_id}")
    
    db = SessionLocal()
    try:
        # Получаем последнюю дату с данными
        last_date = get_last_activity_date(db, user_id)
        
        if last_date is None:
            # Если данных нет - синхронизируем только сегодня
            logger.info("No previous Garmin data found, syncing today only")
            sync_garmin_data(user_id, date_type.today())
            return
        
        # Синхронизируем с последней даты (полностью) до сегодня
        today = date_type.today()
        current_date = last_date
        
        synced_count = 0
        while current_date <= today:
            logger.info(f"Syncing Garmin data for {current_date}")
            success = sync_garmin_data(user_id, current_date)
            if success:
                synced_count += 1
            current_date += timedelta(days=1)
        
        logger.info(f"Smart sync completed: {synced_count} days synced")
        
    finally:
        db.close()
