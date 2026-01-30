import json
import sys
from pathlib import Path
from datetime import date
import tempfile
import os

# Add project root
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from infrastructure.storage.json_repository import JsonNutritionRepository
from domain.models import DayLog, Meal, MealItem

def test_repo():
    print("🧪 Testing JsonNutritionRepository...")
    
    # Create temp file
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp:
        tmp_path = Path(tmp.name)
    
    try:
        # Init repo
        repo = JsonNutritionRepository(tmp_path)
        
        # Test 1: Save
        today = date.today()
        log = DayLog(date=today)
        meal = Meal(name="Test Meal", time="12:00")
        meal.items.append(MealItem(name="Apple", calories=50, protein=0.5, fats=0.2, carbs=14, amount=100))
        meal.calculate_totals()
        log.meals.append(meal)
        log.recalculate_totals()
        
        print(f"   Saving log for {today}...")
        repo.save_day(log)
        
        # Test 2: Read
        print(f"   Reading log back...")
        loaded_log = repo.get_day(today)
        
        if not loaded_log:
            print("❌ Failed to load log")
            return
            
        print(f"✅ Loaded log: {loaded_log.date}")
        print(f"   Calories: {loaded_log.totals.calories} (Expected: 50.0)")
        
        if loaded_log.totals.calories == 50.0:
            print("✅ Data integrity check passed")
        else:
            print(f"❌ Data mismatch: {loaded_log.totals.calories}")
            
    finally:
        if tmp_path.exists():
            os.unlink(tmp_path)
            
if __name__ == "__main__":
    test_repo()
