import json
import sys
from pathlib import Path
from datetime import date

# Add project root
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from domain.models import DayLog

def test_models():
    """Тестирует загрузку реальных данных в новые модели"""
    json_path = project_root / 'data' / 'nutrition' / 'nutrition_log.json'
    
    if not json_path.exists():
        print("❌ nutrition_log.json not found")
        return

    with open(json_path) as f:
        data = json.load(f)
        
    entries = data.get('entries', [])
    if not entries:
        print("⚠️ No entries in log")
        return

    # Берем последние 3 записи
    print(f"Testing {min(3, len(entries))} entries...")
    
    for entry in entries[-3:]:
        try:
            day_log = DayLog(**entry)
            print(f"✅ Parsed {day_log.date}: {len(day_log.meals)} meals, Total: {day_log.totals.calories} kcal")
            
            # Проверяем пересчет
            old_cals = day_log.totals.calories
            day_log.recalculate_totals()
            new_cals = day_log.totals.calories
            
            if abs(old_cals - new_cals) > 1.0:
                print(f"   ⚠️ Recalculation mismatch: {old_cals} vs {new_cals}")
            
        except Exception as e:
            print(f"❌ Failed to parse entry {entry.get('date')}: {e}")
            # Debug fields
            # print(json.dumps(entry, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    test_models()
