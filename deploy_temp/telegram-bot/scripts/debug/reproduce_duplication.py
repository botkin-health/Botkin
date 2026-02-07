
import sys
import os
from pathlib import Path

# Add project root to python path
project_root = Path("/Users/alexlyskovsky/HealthVault/telegram-bot")
sys.path.append(str(project_root))

from services.description_parser import parse_meal_description, extract_products_from_description

def test_duplication():
    description = "150 грамм жаренной картошки"
    print(f"Testing description: '{description}'")
    
    # Test 1: Direct regex extraction
    print("\n--- Testing extract_products_from_description (regex only) ---")
    products_regex = extract_products_from_description(description)
    print(f"Found {len(products_regex)} products:")
    for p in products_regex:
        print(f"  - {p['name']}: {p['weight']}g")
        
    if len(products_regex) > 1 and products_regex[0]['name'] == products_regex[1]['name']:
        print("FAIL: Duplication found in regex parser!")
    else:
        print("PASS: No duplication in regex parser.")

    # Test 2: Full pipeline (might use ChatGPT if configured, but likely falls back to regex in this env)
    # We force ChatGPT to be skipped by mocking/failing if needed, or we just see what happens.
    # To properly test logic without ChatGPT we can inspect how parse_meal_description calls things.
    # But let's just run it.
    print("\n--- Testing parse_meal_description (full pipeline) ---")
    try:
        products_full = parse_meal_description(description)
        print(f"Found {len(products_full)} products:")
        for p in products_full:
            print(f"  - {p['name']}: {p['weight']}g (source: {p.get('source')})")
            
        if len(products_full) > 1 and products_full[0]['name'] == products_full[1]['name']:
             print("FAIL: Duplication found in full pipeline!")
        else:
             print("PASS: No duplication in full pipeline.")
             
    except Exception as e:
        print(f"Error running full pipeline: {e}")

if __name__ == "__main__":
    test_duplication()
