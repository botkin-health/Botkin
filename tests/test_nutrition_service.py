import sys
from pathlib import Path
from datetime import date
import tempfile
import os

# Add project root
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services.nutrition_service import NutritionService
from infrastructure.storage.json_repository import JsonNutritionRepository
from domain.models import DayLog, Meal, MealItem

def test_service():
    print("🧪 Testing NutritionService...")
    
    # Create temp file
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp:
        tmp_path = Path(tmp.name)
    
    try:
        # Init repo & service
        repo = JsonNutritionRepository(tmp_path)
        service = NutritionService(repo)
        
        # 1. Setup Data for Today
        today = date.today()
        log = DayLog(date=today)
        meal = Meal(name="Breakfast", time="08:00")
        meal.items.append(MealItem(name="Eggs", calories=150, protein=12, fats=10, carbs=1, amount=100))
        meal.calculate_totals()
        log.meals.append(meal)
        log.recalculate_totals()
        repo.save_day(log)
        
        # 2. Test get_day_stats
        print(f"   Getting stats for {today}...")
        stats = service.get_day_stats(today)
        
        totals = stats['totals']
        targets = stats['targets']
        remaining = stats['remaining']
        
        print(f"✅ Service Stats:")
        print(f"   Totals: {totals.calories} kcal, {totals.protein}g protein")
        print(f"   Targets: {targets.get('calories')} kcal (Defaults used)")
        print(f"   Remaining: {remaining.get('calories')} kcal")
        
        if totals.calories != 150.0:
             print(f"❌ Calories mismatch: {totals.calories}")
             return
             
        if totals.protein != 12.0:
             print(f"❌ Protein mismatch: {totals.protein}")
             return

        print("✅ Service Logic Check Passed")
            
    finally:
        if tmp_path.exists():
            os.unlink(tmp_path)
            
if __name__ == "__main__":
    test_service()
