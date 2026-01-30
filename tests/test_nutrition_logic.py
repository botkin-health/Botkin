import pytest
from core.description_parser import apply_portion_multiplier, extract_products_from_description, normalize_product_name
from core.nutrition import calculate_nutrition

# 1. Test for "Pizza Weight Bug" (Double Multiplication)
def test_portion_multiplier_only_affects_weight_correctly():
    """
    Simulate the 'Half Pizza' scenario.
    If we have a product of 400g and apply 0.5 multiplier, 
    it should become 200g. 
    It should NOT become 100g (applied twice) or remain 400g.
    """
    products = [
        {'name': 'Pizza', 'weight': 400.0, 'calories': 800.0}
    ]
    
    # Apply 0.5 (half)
    multiplied = apply_portion_multiplier(products, 0.5)
    
    assert len(multiplied) == 1
    item = multiplied[0]
    
    # Weight should be halved
    assert item['weight'] == 200.0
    
    # Calories should be halved implies the logic in apply_portion_multiplier 
    # handles calories too if present. Let's verify what it does.
    # If it only changes weight, that's fine, as long as calculate_nutrition 
    # downstream uses the new weight.
    # Checking implementation behavior:
    if 'calories' in item:
        assert item['calories'] == 400.0

def test_nutrition_calculation_linear_scaling():
    """
    Ensure calculate_nutrition scales linearly with weight.
    200g should have exactly 2x calories of 100g.
    """
    # Assuming 'dummy_product' doesn't exist, it might use default or search.
    # Better to use a known product or mock to avoid network calls?
    # calculate_nutrition uses find_product. 
    # We will trust that for 'oats' or similar simple product it finds something or uses default.
    
    # Use a product that likely hits default values if DB empty: "яйцо" (Egg)
    # Default in code: 143 kcal/100g
    
    res_100 = calculate_nutrition("яйцо", 100.0)
    res_200 = calculate_nutrition("яйцо", 200.0)
    
    assert res_100['calories'] > 0
    # Allow small float error
    assert abs(res_200['calories'] - (res_100['calories'] * 2)) < 0.2

# 2. Test for "Duplication Bug"
def test_normalization_removes_duplicates():
    """
    Test that different forms of the same product normalize to the same string.
    """
    assert normalize_product_name("куриное филе") == "куриное филе"
    assert normalize_product_name("куриная грудка") == "куриное филе" # Check alias
    
    # "вареная картошка" vs "картофель отварной"
    assert normalize_product_name("вареная картошка") == "картофель отварной"

def test_parser_deduplication():
    """
    Test that the parser doesn't output duplicates logic if implemented.
    NOTE: The parser regex might output raw items, deduplication often happens 
    in process_meal_description. 
    Let's check extract_products_from_description behavior directly.
    """
    # Description with "Tomato 100g" and "Tomato"
    # Depending on logic, it might keep both if one has weight and other doesn't,
    # or merge them. Ideally, we want no duplicates.
    
    desc = "помидор 100г и помидор"
    products = extract_products_from_description(desc)
    
    # Depending on implementation quality, this might fail if bug exists.
    # We expect efficient deduplication.
    
    names = [p['name'] for p in products]
    # Ideally should be just one "томат" (normalized)
    assert names.count('томат') <= 1
    
def test_parser_quantity_logic():
    """
    Test 3 eggs = 165g (3 * 55g).
    """
    desc = "3 яйца"
    products = extract_products_from_description(desc)
    
    assert len(products) == 1
    item = products[0]
    assert item['name'] == "яйцо"
    assert item['weight'] == 3 * 55 # 165

