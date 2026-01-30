"""
Nutrition Service - PostgreSQL Version

Сервис для работы с данными о питании через PostgreSQL.
Заменяет JsonNutritionRepository на database CRUD operations.
"""

import logging
from datetime import date, datetime
from typing import Dict, Optional

from database import (
    SessionLocal,
    get_nutrition_logs_by_date,
    get_nutrition_totals_by_date,
    get_activity_by_date,
    get_average_activity_stats
)
from core.nutrition_targets import calculate_targets

logger = logging.getLogger(__name__)


class NutritionService:
    """Service for nutrition data operations using PostgreSQL"""
    
    def __init__(self, user_id: int = 895655):
        """
        Initialize service for specific user
        
        Args:
            user_id: Telegram ID of the user (default: 895655)
        """
        self.user_id = user_id
    
    def get_day_stats(self, day: date) -> Dict:
        """
        Возвращает полную статистику за день для UI:
        - Totals (кбжу)
        - Targets (цели)
        - Remaining (остаток)
        
        Args:
            day: Дата для статистики
            
        Returns:
            Dict with totals, targets, remaining, meals_count
        """
        db = SessionLocal()
        try:
            # Get nutrition totals for the day
            totals_dict = get_nutrition_totals_by_date(db, self.user_id, day)
            
            # Get meal count
            meals = get_nutrition_logs_by_date(db, self.user_id, day)
            meals_count = len(meals)
            
            # Get average activity stats for targets calculation
            try:
                avg_stats = get_average_activity_stats(db, self.user_id, days=14)
                targets_dict = calculate_targets(stats=avg_stats)
            except Exception as e:
                logger.error(f"Error calculating targets: {e}")
                # Fallback to default
                targets_dict = calculate_targets(stats=None)
            
            # Calculate remaining
            remaining = {
                'calories': targets_dict['calories'] - totals_dict['calories'],
                'protein': targets_dict['protein'] - totals_dict['protein'],
                'fats': targets_dict['fats'] - totals_dict['fats'],
                'carbs': targets_dict['carbs'] - totals_dict['carbs'],
            }
            
            # Create MacroStats-like object for compatibility
            class MacroStats:
                def __init__(self, data):
                    self.calories = data['calories']
                    self.protein = data['protein']
                    self.fats = data['fats']
                    self.carbs = data['carbs']
                    self.fiber = data.get('fiber', 0)
            
            return {
                'date': day,
                'totals': MacroStats(totals_dict),
                'targets': targets_dict,
                'remaining': remaining,
                'meals_count': meals_count
            }
            
        finally:
            db.close()


# Singleton
_service_instance: Optional[NutritionService] = None


def get_nutrition_service(user_id: int = 895655) -> NutritionService:
    """
    Get or create nutrition service instance
    
    Args:
        user_id: Telegram ID of the user
        
    Returns:
        NutritionService instance
    """
    global _service_instance
    if _service_instance is None or _service_instance.user_id != user_id:
        _service_instance = NutritionService(user_id=user_id)
    return _service_instance
