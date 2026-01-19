import sys
import os
import logging

# Add project root to path
sys.path.append(os.getcwd())

# Mock logger
logging.basicConfig(level=logging.INFO)

from core.nutrition import process_meal_description_with_menu

def test_fix():
    print("Testing fix for nutrition analysis...")
    
    # Mock data simulating the issue
    description = "ужин\nужин"
    
    # Mock menu data with components from AI
    menu_data = {
        "dish_name": "ужин",
        "calories": 74, # per 100g
        "protein": 18.5,
        "fats": 0,
        "carbs": 0.4,
        "weight": 90,
        "components": [
            {
                "name": "белок яичный варёный с солью",
                "weight": 90,
                "calories": 66.6, # Declared by AI
                "protein": 16.65,
                "fats": 0,
                "carbs": 0.36,
            }
        ]
    }
    
    # Run processing
    meal_items, meal_totals = process_meal_description_with_menu(
        description=description,
        menu_data=menu_data,
        photo_paths=None
    )
    
    # Inspect results
    print("\nResults:")
    for item in meal_items:
        print(f"Product: {item['product']}")
        print(f"  Weight: {item['weight_g']}")
        print(f"  Calories: {item['calories']}")
        print(f"  Source: {item['source']}")
        print(f"  Fats: {item['fats']}")
        
        # Verification logic
        if item['source'] == 'menu_ocr_component' and item['fats'] == 0:
            print("✅ SUCCESS: Product accepted as menu component with correct nutrition (0 fats)")
        elif item['fats'] > 0:
            print("❌ FAILURE: Product has fats (likely recalculated from generic DB)")
        else:
            print("⚠️ INDETERMINATE result")

if __name__ == "__main__":
    test_fix()
