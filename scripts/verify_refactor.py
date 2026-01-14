#!/usr/bin/env python3
import sys
from pathlib import Path
import os

# Add root to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

print(f"Python path: {sys.path}")
print(f"CWD: {os.getcwd()}")

try:
    print("Testing imports...")
    from core.nutrition import parse_meal_description, calculate_nutrition
    from core.supplements import supplement_service
    from core.storage import load_nutrition_log
    from core.api_key_loader import get_google_vision_api_key
    print("✅ Imports successful")
except ImportError as e:
    print(f"❌ Import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test Supplements
print("\nTesting Supplement Service...")
try:
    # Check if schema loaded (indirectly checking data path)
    count = len(supplement_service.schema)
    print(f"Loaded {count} supplements in schema.")
    if count == 0:
        print("⚠️ Warning: Schema is empty. Check supplements.json path.")
    else:
        print(f"✅ Schema loaded with {count} items.")
    
    # Test log intake logic
    print("Testing intake logic for 'омега'...")
    # Mocking storage to avoid writing to real log? 
    # Actually logic uses _save_log. It will write to file.
    # Since this is "verify", maybe we shouldn't actally write or we should revert?
    # It sends to "supplements/log.json".
    # Let's just check schema Logic first without saving? 
    # log_intake calls _save_log.
    # We can mock _save_log temporarily.
    
    original_save = supplement_service._save_log
    supplement_service._save_log = lambda x: print("(Mock) Log saved")
    
    logged, remaining = supplement_service.log_intake("омега")
    print(f"Logged: {logged}")
    
    supplement_service._save_log = original_save
    
    if logged:
         print("✅ Supplement logic working")
    else:
         print("⚠️ Supplement logic returned empty. Maybe 'омега' is not in schema or time conflict?")

except Exception as e:
    print(f"❌ Supplement service error: {e}")
    import traceback
    traceback.print_exc()

# Test Nutrition
print("\nTesting Nutrition Service...")
try:
    print("Testing parse_meal_description with 'яблоко 100г'...")
    # This might use Description Parser -> which uses regex
    items = parse_meal_description("яблоко 100г")
    print(f"Result: {items}")
    if items and 'яблоко' in items[0]['name'].lower():
        print("✅ Nutrition parsing working")
    else:
        print("⚠️ Nutrition parsing returned unexpected result")
except Exception as e:
    print(f"❌ Nutrition service error: {e}")
    import traceback
    traceback.print_exc()

# Test Storage
print("\nTesting Storage...")
try:
    log = load_nutrition_log()
    print(f"Loaded log for today, contains {len(log.get('meals', []))} meals.")
    print("✅ Storage working")
except Exception as e:
    print(f"❌ Storage error: {e}")
    import traceback
    traceback.print_exc()

print("\n-------------------------------------------")
print("Refactoring Verification Complete.")
