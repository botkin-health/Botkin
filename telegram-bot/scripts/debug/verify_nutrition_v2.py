
from services.nutrition_targets import calculate_targets, check_feasibility
import math

def test_targets():
    print("--- Testing Target Calculation (12% Deficit) ---")
    
    # Case 1: TDEE 2000
    tdee = 2000
    targets = calculate_targets(tdee)
    expected_cal = round(2000 * 0.88) # ~1760
    print(f"TDEE {tdee}: Target={targets['calories']} (Exp: ~{expected_cal}), P={targets['protein']}, F={targets['fats']}, C={targets['carbs']}")
    # Assertions
    assert abs(targets['calories'] - expected_cal) < 5
    assert targets['protein'] == round(82 * 1.8) # 148
    
    # Case 2: TDEE 1600 (Low)
    tdee = 1600
    targets = calculate_targets(tdee)
    expected_cal = round(1600 * 0.88) # ~1408
    print(f"TDEE {tdee}: Target={targets['calories']} (Exp: ~{expected_cal}), P={targets['protein']}, F={targets['fats']}, C={targets['carbs']}")
    assert abs(targets['calories'] - expected_cal) < 5
    
    # Case 3: TDEE 3000 (High)
    tdee = 3000
    targets = calculate_targets(tdee)
    expected_cal = round(3000 * 0.88) # ~2640
    print(f"TDEE {tdee}: Target={targets['calories']} (Exp: ~{expected_cal}), P={targets['protein']}, F={targets['fats']}, C={targets['carbs']}")
    assert abs(targets['calories'] - expected_cal) < 5
    
    # Consistency Check
    cal_from_macros = targets['protein']*4 + targets['fats']*9 + targets['carbs']*4
    diff = abs(targets['calories'] - cal_from_macros)
    print(f"  Consistency: Target={targets['calories']}, Sum={cal_from_macros}, Diff={diff}")
    assert diff < 10

def test_feasibility():
    print("\n--- Testing Feasibility Check ---")
    
    # Case 1: Impossible (Need 80g protein in 200 kcal)
    # Max possible = 200/4 = 50g
    msg = check_feasibility(remaining_calories=200, remaining_protein=80)
    print(f"Case 1 (80g in 200kcal): {msg}")
    assert msg is not None
    assert "недостижима" in msg
    
    # Case 2: Possible (Need 20g protein in 200 kcal)
    msg = check_feasibility(remaining_calories=200, remaining_protein=20)
    print(f"Case 2 (20g in 200kcal): {msg}")
    assert msg is None # Should be fine (only 40% of calories)
    
    # Case 3: Hard but possible (Need 40g in 200 kcal -> 80% protein)
    msg = check_feasibility(remaining_calories=200, remaining_protein=40)
    print(f"Case 3 (40g in 200kcal): {msg}")
    assert msg is not None
    assert "Нужно наедать белок" in msg or "недостижима" in msg

if __name__ == "__main__":
    try:
        test_targets()
        test_feasibility()
        print("\n✅ Verification PASSED")
    except AssertionError as e:
        print(f"\n❌ Verification FAILED: {e}")
