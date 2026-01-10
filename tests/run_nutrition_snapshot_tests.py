
import json
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to path
# Add telegram-bot directory to path (because it has a hyphen)
sys.path.insert(0, str(Path(__file__).parent.parent / "telegram-bot"))

from services.nutrition import process_meal_description

def mock_chatgpt_response(description, key):
    desc_lower = description.lower()
    
    # Case 1: Simple regex-able, but let's be consistent or let regex handle it?
    # Regex handles it but normalizes "курица" -> "куриное филе"
    
    # Case 2
    if "exponenta" in desc_lower:
        return [{"name": "EXPONENTA HIGH-PRO вишня", "weight": 160, "source": "chatgpt"}]
    
    # Case 3
    if "салат" in desc_lower and "тунец" in desc_lower:
        # Regex might extract this, but let's mock GPT for consistency
        return [
             {"name": "салат", "weight": 100, "source": "chatgpt"},
             {"name": "тунец", "weight": 85, "source": "chatgpt"},
             {"name": "огурец", "weight": 150, "source": "chatgpt"},
             {"name": "масло", "weight": 5, "source": "chatgpt"}
        ]

    # Case 4
    if "латте" in desc_lower:
        return [{"name": "латте на кокосовом", "weight": 300, "source": "chatgpt"}]
        
    # Case 5
    if "яблоко" in desc_lower and "шт" in desc_lower:
         return [
             {"name": "яблоко зеленое", "weight": 150, "source": "chatgpt"},
             {"name": "банан", "weight": 120, "source": "chatgpt"}
         ]
         
    # Case 6: Context correction - usually handled by logic OUTSIDE parser if it is "add to previous".
    # But if parser handles "хлеб 30г", it's fine.
    # Regex handles "хлеб 30г" well.
    
    # Case 7
    if "протеин" in desc_lower:
        return [{"name": "протеин Tree of Life", "weight": 30, "source": "chatgpt"}]
        
    # Case 8
    if "суп" in desc_lower and "порция" in desc_lower:
        return [{"name": "суп рассольник московский", "weight": 300, "source": "chatgpt"}]
        
    # Case 9
    if "guinness" in desc_lower:
        return [
            {"name": "пиво Guinness 0.0", "weight": 500, "source": "chatgpt"},
            {"name": "чипсы", "weight": 50, "source": "chatgpt"}
        ]
        
    # Case 10
    if "орехов" in desc_lower or "горсть" in desc_lower:
        return [{"name": "орехи", "weight": 30, "source": "chatgpt"}]

    # --- Text parsing for Image Cases (11-20) ---
    if "филе" in desc_lower:
        return [{"name": "куриное филе", "weight": 0, "source": "chatgpt"}] 
    if "поке" in desc_lower:
        return [{"name": "поке с тунцом", "weight": 0, "source": "chatgpt"}]
    if "скуп" in desc_lower:
        return [{"name": "протеин", "weight": 0, "source": "chatgpt"}]
    # Case 16 vs Case 4
    if "латте" in desc_lower and "рисунок" in desc_lower:
        return [{"name": "латте", "weight": 0, "source": "chatgpt"}]
    if "латте" in desc_lower: # Fallback for Case 4 (if needed, but Case 4 usually has 'кокосовом')
        # Check if it is really Case 4
        if "кокосов" in desc_lower:
             return [{"name": "латте на кокосовом", "weight": 300, "source": "chatgpt"}]
        return [{"name": "латте", "weight": 0, "source": "chatgpt"}]

    if "яблоко" in desc_lower and "зеленое" in desc_lower:
        return [{"name": "яблоко", "weight": 0, "source": "chatgpt"}]
    
    # Case 18 vs Case 9
    if "пиво" in desc_lower and "банку" in desc_lower:
        return [{"name": "пиво Guinness", "weight": 0, "source": "chatgpt"}]
    
    if "яиц" in desc_lower:
        return [{"name": "яйцо", "weight": 0, "source": "chatgpt"}]
        
    return None

def mock_menu_photo_response(photo_path, api_key=None):
    # Handle both str and Path
    path_str = str(photo_path).lower()
    print(f"DEBUG: mock_menu calling with {path_str}")
    
    if "nutrition_label" in path_str:
        return {
            "dish_name": "продукт с этикетки",
            "calories": 230, "protein": 3, "fats": 1, "carbs": 52, "weight": 100,
            "nutrition_per_100g": {"calories": 230, "protein": 3, "fats": 1, "carbs": 52} 
        }
    if "restaurant_menu" in path_str:
        return {
            "dish_name": "Биг Мак",
            "calories": 503, "protein": 26, "fats": 25, "carbs": 42, "weight": 215
        }
    return None

def mock_extract_weights(photo_paths, key=None):
    if not photo_paths: return []
    path_str = str(photo_paths[0]).lower()
    print(f"DEBUG: mock_extract_weights calling with {path_str}")
    
    if "kitchen_scale_chicken" in path_str:
        return [345.0]
    if "bowl_food" in path_str:
        return [400.0]
    if "protein_powder" in path_str:
        return [32.0]
    if "latte_art" in path_str:
        return [300.0] 
    if "apple_on_scale" in path_str:
        return [182.0]
    if "guinness_can" in path_str:
        return [500.0]
    if "eggs_carton" in path_str:
        return [600.0]
    if "walnuts_hand" in path_str:
        return [45.0]

    return []

def run_tests():
    fixtures_dir = Path(__file__).parent / "fixtures"
    with open(fixtures_dir / "nutrition_inputs.json", "r") as f:
        inputs = json.load(f)
    with open(fixtures_dir / "nutrition_expected_snapshots.json", "r") as f:
        expected = json.load(f)

    passed = 0
    total = len(inputs)
    results = []

    print(f"Running {total} snapshot tests...\n")

    # Mocking ChatGPT and Network calls
    # Import modules to ensure they are loaded before patching
    import services.chatgpt_vision
    import services.description_parser
    import services.menu_parser
    
    # We use mock_menu_photo_response for BOTH chatgpt wrapper and menu_parser direct call
    with patch('services.chatgpt_vision.parse_text_description_with_chatgpt', side_effect=mock_chatgpt_response), \
         patch('services.chatgpt_vision.parse_menu_with_chatgpt', side_effect=mock_menu_photo_response), \
         patch('services.menu_parser.parse_menu_photo', side_effect=mock_menu_photo_response), \
         patch('services.description_parser.extract_weights_from_photos', side_effect=mock_extract_weights), \
         patch('services.chatgpt_vision.get_openai_api_key', return_value="fake_key"), \
         patch('services.nutrition.search_product_online', return_value=None), \
         patch('services.nutrition.find_product', return_value=None):

        for case in inputs:
            case_id = case["id"]
            desc = case["input_text"]
            photo_paths = [Path(case["photo_path"])] if "photo_path" in case else None
            
            # Run the parser
            # We must pass photo_paths if they exist
            if photo_paths:
                 items, totals = process_meal_description(desc, photo_paths=photo_paths)
            else:
                 items, totals = process_meal_description(desc)
            
            # Transform to snapshot format (simplify for comparison)
            snapshot = []
            for item in items:
                entry = {
                    "product": item["product"],
                    "weight_g": item["weight_g"]
                }
                # Include nutrition info if expected in the snapshot for this case
                # Or just include it if it's non-zero/present to be robust
                # But let's look at expected
                
                # Dynamic check: if expected has calories, include them.
                # Find matching expected item (simplified logic assuming order or unique names)
                # But safer to just include them if they exist in item and are not None
                if item.get("calories") is not None:
                     # Round to avoid float issues
                     entry["calories"] = item["calories"]
                if item.get("protein") is not None:
                     entry["protein"] = item["protein"]
                if item.get("fats") is not None:
                     entry["fats"] = item["fats"]
                if item.get("carbs") is not None:
                     entry["carbs"] = item["carbs"]

                snapshot.append(entry)
            
            # Compare
            exp = expected.get(case_id, [])
            
            # Sort for robust comparison
            snapshot.sort(key=lambda x: x["product"])
            exp.sort(key=lambda x: x["product"])
            
            # Compare
            exp = expected.get(case_id, [])
            
            # Filter actual snapshot to only include keys present in expected
            # This allows us to ignore extra fields like calories if we don't care about them in the test
            filtered_snapshot = []
            for item in snapshot:
                 # Find corresponding expected item (by product name) to know which keys to keep
                 # This is tricky if multiple items.
                 # Simpler approach: construct a new dict keeping ONLY keys that appear in ANY expected item for simpler structure?
                 # No, per item.
                 
                 # Let's just strip keys not in the expected item structure?
                 # Assume expected is list of dicts.
                 # If list lengths differ, we fail anyway.
                 # Let's just leave snapshot as is, but change comparison logic:
                 # "Check if Expected is a Subset of Actual"
                 
                 pass # Logic moved to approx_equal_subset
            
            # Sort for robust comparison
            snapshot.sort(key=lambda x: x["product"])
            exp.sort(key=lambda x: x["product"])
            
            # Start: Custom comparison
            def is_subset_match(actual_list, expected_list):
                if len(actual_list) != len(expected_list):
                    return False
                for act, exp_item in zip(actual_list, expected_list):
                    # For each key in expected, actual must match
                    for k, v in exp_item.items():
                        if k not in act:
                            return False
                        # Float comparison
                        if isinstance(v, (int, float)) and isinstance(act[k], (int, float)):
                            if abs(v - act[k]) > 0.1:
                                return False
                        elif v != act[k]:
                            return False
                return True

            if is_subset_match(snapshot, exp):
                print(f"✅ {case_id}: PASS")
                passed += 1
            else:
                print(f"❌ {case_id}: FAIL")
                print(f"   Input: {desc}")
                print(f"   Expected: {json.dumps(exp, ensure_ascii=False)}")
                print(f"   Actual:   {json.dumps(snapshot, ensure_ascii=False)}")
                results.append((case_id, False))

    print(f"\nSummary: {passed}/{total} passed.")
    if passed != total:
        sys.exit(1)

if __name__ == "__main__":
    run_tests()
