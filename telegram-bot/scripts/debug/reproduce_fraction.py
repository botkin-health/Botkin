
import re

def parse_portion(description):
    description = description.lower()
    portion_multiplier = 1.0
    
    # Updated logic similar to handlers/photo.py
    fraction_match = re.search(r'\b(\d+)/(\d+)\b', description)
    decimal_match = re.search(r'\b(0[.,]\d+)\b', description)
    
    if fraction_match:
        try:
            numerator = int(fraction_match.group(1))
            denominator = int(fraction_match.group(2))
            if denominator != 0:
                portion_multiplier = float(numerator) / float(denominator)
        except (ValueError, ZeroDivisionError):
            pass
    elif decimal_match:
        try:
            portion_multiplier = float(decimal_match.group(1).replace(',', '.'))
        except ValueError:
            pass
    elif 'половину' in description.lower() or 'половина' in description.lower():
        portion_multiplier = 0.5
    elif 'треть' in description.lower():
        portion_multiplier = 1.0 / 3.0
    elif 'четверть' in description.lower():
        portion_multiplier = 0.25
        
    return portion_multiplier

def test_fraction():
    # Test cases
    cases = [
        ("1/2 шоколадки Twix", 0.5),
        ("0.5 шоколадки", 0.5),
        ("0,5 шоколадки", 0.5),
        ("1/4 шоколадки", 0.25),
        ("половину шоколадки", 0.5),
        ("целую шоколадку", 1.0)
    ]
    
    all_passed = True
    for text, expected in cases:
        multiplier = parse_portion(text)
        if multiplier == expected:
             print(f"PASS: '{text}' -> {multiplier}")
        else:
             print(f"FAIL: '{text}' -> {multiplier} (expected {expected})")
             all_passed = False
             
    if all_passed:
        print("\nALL TESTS PASSED")
    else:
        print("\nSOME TESTS FAILED")

if __name__ == "__main__":
    test_fraction()
