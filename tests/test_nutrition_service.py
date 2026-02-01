import pytest
from datetime import date, datetime, time
from services.nutrition_service import NutritionService
from database.models import NutritionLog
from database.crud import create_nutrition_log

def test_service_get_day_stats(mock_session_local, test_db):
    """Test get_day_stats with mock DB"""
    user_id = 895655
    today = date.today()
    service = NutritionService(user_id=user_id)
    
    # 1. Create a meal log in DB directly or via CRUD
    # We'll use CRUD to be safe or direct DB add
    
    items = {"eggs": {"calories": 150, "protein": 12, "fats": 10, "carbs": 1}}
    totals = {"calories": 150, "protein": 12, "fats": 10, "carbs": 1}
    
    create_nutrition_log(
        db=test_db,
        user_id=user_id,
        date=today,
        meal_time=time(8, 0),
        meal_name="Breakfast",
        items=items,
        totals=totals,
        photo_paths=None
    )
    
    # 2. Get stats
    stats = service.get_day_stats(today)
    
    assert stats['date'] == today
    assert stats['meals_count'] == 1
    
    totals_res = stats['totals']
    assert totals_res.calories == 150
    assert totals_res.protein == 12
    assert totals_res.fats == 10
    
    # Check targets (these come from mocked or default calculation)
    # Since we didn't add activity logs, it should use defaults/fallback
    assert stats['targets'] is not None
