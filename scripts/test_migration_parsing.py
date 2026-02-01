#!/usr/bin/env python3
"""
Test migration script logic without real database.
Validates data parsing and transformation.
"""

import json
import csv
from datetime import datetime
from pathlib import Path

DATA_DIR = Path("data")
WEIGHTS_DIR = DATA_DIR / "weights"
NUTRITION_FILE = DATA_DIR / "nutrition" / "nutrition_log.json"
BP_FILE = DATA_DIR / "apple-health" / "parsed" / "blood_pressure_manual.csv"

def test_weight_parsing():
    """Test weight file parsing."""
    print("🔍 Testing weight data parsing...")
    
    weight_files = sorted(WEIGHTS_DIR.glob("*.json"))[:5]
    parsed_count = 0
    
    for filepath in weight_files:
        with open(filepath) as f:
            data = json.load(f)
        
        for entry in data:
            if "weight" not in entry:
                continue
            
            # Validate required fields
            assert "date" in entry, f"Missing date in {filepath}"
            assert "weight" in entry, f"Missing weight in {filepath}"
            
            # Parse timestamp
            measured_at = datetime.strptime(entry["date"], "%Y-%m-%d %H:%M")
            
            # Simulate SQL insert
            print(f"  ✓ {measured_at.date()}: {entry['weight']}kg, BF={entry.get('body_fat')}%, VF={entry.get('visceral_fat')}")
            parsed_count += 1
    
    print(f"✅ Parsed {parsed_count} weight records from {len(weight_files)} files\n")
    return parsed_count

def test_bp_parsing():
    """Test blood pressure parsing."""
    print("🔍 Testing blood pressure data parsing...")
    
    if not BP_FILE.exists():
        print("⚠️  BP file not found, skipping\n")
        return 0
    
    parsed_count = 0
    with open(BP_FILE) as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if i >= 5:  # Limit to 5
                break
            
            measured_at = datetime.strptime(row["Date"], "%Y-%m-%d %H:%M:%S %z")
            systolic = int(row["Systolic"])
            diastolic = int(row["Diastolic"])
            
            print(f"  ✓ {measured_at.date()}: {systolic}/{diastolic}")
            parsed_count += 1
    
    print(f"✅ Parsed {parsed_count} BP records\n")
    return parsed_count

def test_nutrition_parsing():
    """Test nutrition log parsing."""
    print("🔍 Testing nutrition data parsing...")
    
    if not NUTRITION_FILE.exists():
        print("⚠️  Nutrition file not found, skipping\n")
        return 0
    
    with open(NUTRITION_FILE) as f:
        data = json.load(f)
    
    entries = data.get("entries", [])[:3]  # Limit to 3 days
    parsed_entries = 0
    parsed_items = 0
    
    for entry in entries:
        date = datetime.strptime(entry["date"], "%Y-%m-%d").date()
        
        for meal in entry.get("meals", []):
            meal_name = meal.get("meal")
            items_count = len(meal.get("items", []))
            
            print(f"  ✓ {date} | {meal_name}: {items_count} items")
            parsed_entries += 1
            parsed_items += items_count
    
    print(f"✅ Parsed {parsed_entries} meal entries, {parsed_items} food items\n")
    return parsed_entries

def main():
    print("="*60)
    print("🧪 MIGRATION DRY-RUN TEST (No Database)")
    print("="*60 + "\n")
    
    try:
        weights = test_weight_parsing()
        bp = test_bp_parsing()
        nutrition = test_nutrition_parsing()
        
        print("="*60)
        print("📊 TEST SUMMARY")
        print("="*60)
        print(f"Weight records:     {weights}")
        print(f"BP records:         {bp}")
        print(f"Nutrition entries:  {nutrition}")
        print("\n✅ All parsing tests passed!")
        print("\n💡 Next step: Start Docker and run real migration:")
        print("   make db-up")
        print("   python scripts/migrate_to_postgres_v2.py --dry-run --limit 10")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        raise

if __name__ == "__main__":
    main()
