import sys
import os
import logging

# Add project root to path
sys.path.append(os.getcwd())

# Mock logger
logging.basicConfig(level=logging.INFO)

from core.description_parser import parse_meal_description

def test_short_description():
    print("Testing short description parsing...")
    
    # Test case: "две сливы" (9 chars)
    description = "две сливы"
    print(f"Description: '{description}' (len: {len(description)})")
    
    # Simulate API key presence
    # We won't actually call OpenAI here, we probably just want to see if it ATTEMPTS to call it
    # But since we can't easily mock the internal import without patching, 
    # we will rely on the fact that if it tries to import and finds no key, it prints "OpenAI API ключ не найден"
    # or if we have a key it proceeds.
    
    # Actually, we can check if it returns empty list. 
    # If the length check > 10 is the blocker, it won't even try ChatGPT.
    
    # For this test, we unfortunately need the real key to fully verify ChatGPT works, 
    # but to verify the code PATH, we can inspect the source code.
    # However, running this script will show if regex catches it (it shouldn't).
    
    products = parse_meal_description(description)
    
    print("\nResults:")
    print(f"Products found: {len(products)}")
    for p in products:
        print(f" - {p}")
        
    if not products:
        print("❌ FAILURE: No products found (likely skipped ChatGPT due to length check)")
    else:
        print("✅ SUCCESS: Products found")

if __name__ == "__main__":
    test_short_description()
