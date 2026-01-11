
import json
import os
from decimal import Decimal

LOG_FILE = 'data/nutrition/nutrition_log.json'

def load_log():
    with open(LOG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_log(data):
    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def recalculate_day_totals(day_entry):
    totals = {'calories': 0.0, 'protein': 0.0, 'fats': 0.0, 'carbs': 0.0}
    
    for meal in day_entry.get('meals', []):
        for item in meal.get('items', []):
            totals['calories'] += item.get('calories', 0)
            totals['protein'] += item.get('protein', 0)
            totals['fats'] += item.get('fats', 0)
            totals['carbs'] += item.get('carbs', 0)
            
    # Rounding
    for k in totals:
        totals[k] = round(totals[k], 1)
        
    day_entry['totals'] = totals

def fix_log():
    data = load_log()
    
    # Get last day
    if not data or 'entries' not in data or not data['entries']:
        print("No entries found.")
        return

    last_day = data['entries'][-1]
    print(f"Checking date: {last_day.get('date')}")
    
    if last_day.get('date') != '2026-01-10':
        print("Last day is not 2026-01-10, aborting safety check.")
        return

    meals = last_day.get('meals', [])
    if not meals:
        print("No meals for this day.")
        return

    last_meal = meals[-1]
    print(f"Last meal found: {last_meal.get('meal')} at {last_meal.get('time')}")
    
    # Verify it's the peppers
    items = last_meal.get('items', [])
    if items and 'перец' in items[0].get('food', '').lower():
        print(f"Removing meal with: {items[0].get('food')}")
        meals.pop()
        
        # Recalculate totals
        recalculate_day_totals(last_day)
        
        save_log(data)
        print("Log updated successfully.")
    else:
        print("Last meal does not appear to be the peppers. Aborting.")
        print(f"Found items: {[i.get('food') for i in items]}")

if __name__ == '__main__':
    fix_log()
