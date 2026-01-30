import pytest
from core.description_parser import parse_meal_description

def test_fruit_quantity_estimation():
    """
    Test that inputs like "1 kiwi", "1 mandarin", "6 cherry tomatoes"
    result in concrete weights, not None.
    """
    import sys
    from unittest.mock import patch
    
    description = "1 киви, 1 мандарин, 6 томатов черри"
    
    # Mock get_openai_api_key to return None, forcing Regex parser
    with patch('core.chatgpt_vision.get_openai_api_key', return_value=None):
        products = parse_meal_description(description)
    
    product_map = {p['name']: p for p in products}
    
    # Check Kiwi
    # Normalizer might change "киви" to "киви"
    kiwi = product_map.get('киви')
    assert kiwi is not None, "Kiwi not found"
    assert kiwi['weight'] is not None, "Kiwi weight is None"
    assert kiwi['weight'] > 0, "Kiwi weight is 0"
    
    # Check Mandarin
    mandarin = product_map.get('мандарин')
    assert mandarin is not None, "Mandarin not found"
    assert mandarin['weight'] is not None, "Mandarin weight is None"
    # Approx 80-100g
    assert 50 < mandarin['weight'] < 150
    
    # Check Cherry Tomatoes
    # Normalizer should map to "томат черри"
    cherry = product_map.get('томат черри')
    assert cherry is not None, "Cherry tomatoes not found"
    assert cherry['weight'] is not None, "Cherry tomatoes weight is None"
    # 6 * 15g = 90g
    assert cherry['weight'] == 90
