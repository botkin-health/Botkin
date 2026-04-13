"""
Nutrition Service - PostgreSQL Version

Сервис для работы с данными о питании через PostgreSQL.
Заменяет JsonNutritionRepository на database CRUD operations.
"""

import logging
from datetime import date
from typing import Dict, Optional

from database import (
    SessionLocal,
    get_nutrition_logs_by_date,
    get_nutrition_totals_by_date,
    get_average_activity_stats,
    get_user_by_telegram_id,
)
from core.nutrition_targets import calculate_targets

logger = logging.getLogger(__name__)


class NutritionService:
    """Service for nutrition data operations using PostgreSQL"""

    def __init__(self, user_id: int):
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
            user = get_user_by_telegram_id(db, self.user_id)
            try:
                avg_stats = get_average_activity_stats(db, self.user_id, days=14)
                user_bmr = getattr(user, "bmr", None) if user else None
                user_active = getattr(user, "avg_active_calories", None) if user else None
                logger.info(
                    f"[day_stats] user_id={self.user_id} user.bmr={user_bmr} user.avg_active={user_active} avg_stats={avg_stats}"
                )
                targets_dict = calculate_targets(stats=avg_stats, user=user)
            except Exception as e:
                logger.error(f"Error calculating targets: {e}", exc_info=True)
                targets_dict = calculate_targets(stats=None, user=user)

            # Calculate remaining
            remaining = {
                "calories": targets_dict["calories"] - totals_dict["calories"],
                "protein": targets_dict["protein"] - totals_dict["protein"],
                "fats": targets_dict["fats"] - totals_dict["fats"],
                "carbs": targets_dict["carbs"] - totals_dict["carbs"],
            }

            # Create MacroStats-like object for compatibility
            class MacroStats:
                def __init__(self, data):
                    self.calories = data["calories"]
                    self.protein = data["protein"]
                    self.fats = data["fats"]
                    self.carbs = data["carbs"]
                    self.fiber = data.get("fiber", 0)

            return {
                "date": day,
                "totals": MacroStats(totals_dict),
                "targets": targets_dict,
                "remaining": remaining,
                "meals_count": meals_count,
            }

        finally:
            db.close()


# Singleton
_service_instance: Optional[NutritionService] = None


def get_nutrition_service(user_id: int) -> NutritionService:
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
