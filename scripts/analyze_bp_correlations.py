
import json
import csv
import re
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
import statistics

# Config
DATA_DIR = Path("/Users/alexlyskovsky/HealthVault/data")
BP_FILE = DATA_DIR / "apple-health/parsed/blood_pressure_manual.csv"
SLEEP_FILE = DATA_DIR / "apple-health/parsed/sleep.json"
WORKOUT_FILE = DATA_DIR / "apple-health/parsed/workouts.json"
NUTRITION_FILE = DATA_DIR / "nutrition/nutrition_log.json"

def parse_date(date_str):
    # Handles "2026-01-24" or timestamps
    if "T" in date_str:
        return date_str.split("T")[0]
    if " " in date_str:
        return date_str.split(" ")[0]
    return date_str

def load_bp():
    bp_data = defaultdict(list)
    if not BP_FILE.exists():
        print(f"❌ BP file not found: {BP_FILE}")
        return bp_data
        
    with open(BP_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = parse_date(row['Date'])
            try:
                sys = int(float(row['Systolic']))
                dia = int(float(row['Diastolic']))
                bp_data[d].append((sys, dia))
            except ValueError:
                continue
    
    # Average per day
    daily_bp = {}
    for d, readings in bp_data.items():
        avg_sys = statistics.mean([r[0] for r in readings])
        avg_dia = statistics.mean([r[1] for r in readings])
        daily_bp[d] = {"sys": avg_sys, "dia": avg_dia, "count": len(readings)}
    return daily_bp

def load_sleep():
    daily_sleep = defaultdict(float)
    if not SLEEP_FILE.exists(): return daily_sleep
    
    with open(SLEEP_FILE, 'r') as f:
        data = json.load(f)
        
    for entry in data:
        # Only count 'Asleep' types (Core, Deep, REM, Unspecified)
        val = entry.get('value') or entry.get('sleep_value')
        if val in ["HKCategoryValueSleepAnalysisInBed", "HKCategoryValueSleepAnalysisAwake"]:
            continue
            
        d_str = parse_date(entry['start_date']) # Assign sleep to the morning date usually
        
        # Calculate duration
        try:
            start = datetime.fromisoformat(entry['start_date'])
            end = datetime.fromisoformat(entry['end_date'])
            duration_hours = (end - start).total_seconds() / 3600.0
            daily_sleep[d_str] += duration_hours
        except:
            continue
            
    return daily_sleep

def load_workouts():
    daily_workouts = defaultdict(float)
    if not WORKOUT_FILE.exists(): return daily_workouts
    
    with open(WORKOUT_FILE, 'r') as f:
        data = json.load(f)
        
    for entry in data:
        d_str = parse_date(entry['start_date'])
        dur = entry.get('duration', 0)
        daily_workouts[d_str] += dur # minutes
    return daily_workouts

def load_nutrition():
    daily_nutrition = {}
    if not NUTRITION_FILE.exists(): return daily_nutrition
    
    with open(NUTRITION_FILE, 'r') as f:
        data = json.load(f)
        
    # Check structure: dict with 'entries' list or just list?
    entries = data.get('entries', []) if isinstance(data, dict) else data
    
    for entry in entries:
        d = entry.get('date')
        if not d: continue
        
        totals = entry.get('totals', {})
        meals = entry.get('meals', [])
        
        # Analyze items for keywords
        alcohol_items = []
        coffee_items = []
        salty_items = []
        
        for meal in meals:
            for item in meal.get('items', []):
                food = item.get('food', '').lower()
                
                # Check alcohol
                if any(x in food for x in ['вино', 'пиво', 'ром', 'водка', 'виски', 'коньяк', 'alcohol', 'beer', 'wine']):
                    alcohol_items.append(food)
                    
                # Check coffee
                if any(x in food for x in ['кофе', 'coffee', 'эспрессо']):
                    coffee_items.append(food)
                    
                # Check salt/sodium triggers
                if any(x in food for x in ['соль', 'соевый', 'соус', 'чипсы', 'колбаса', 'бекон', 'холодец', 'рыба соленая']):
                    salty_items.append(food)

        daily_nutrition[d] = {
            "calories": totals.get('calories', 0),
            "alcohol": len(alcohol_items) > 0,
            "alcohol_desc": ", ".join(alcohol_items),
            "coffee": len(coffee_items) > 0,
            "salty": len(salty_items) > 0,
            "salty_desc": ", ".join(salty_items)
        }
    return daily_nutrition

def analyze():
    bp = load_bp()
    sleep = load_sleep()
    workouts = load_workouts()
    nutrition = load_nutrition()
    
    # Merge dates (only dates with BP data for now)
    sorted_dates = sorted(bp.keys())
    
    print(f"📊 Analysis for {len(sorted_dates)} days with BP readings:\n")
    
    print(f"{'Date':<12} | {'BP (Sys/Dia)':<12} | {'Sleep':<5} | {'Workouts':<8} | {'Cals':<6} | {'Flags'}")
    print("-" * 80)
    
    data_points = []
    
    for d in sorted_dates:
        # Filter for 2026 only to be relevant
        if not d.startswith("2026"): continue
        
        b = bp[d]
        s = sleep.get(d, 0)
        w = workouts.get(d, 0)
        n = nutrition.get(d, {})
        
        # Previous day data (for sleep/nutrition impact on NEXT day BP?)
        # Convention: Sleep date X is the night BEFORE day X usually in Health app logic?
        # Actually sleep date X usually means wake up on date X. So it correlates with BP on date X.
        # Nutrition on date X might affect BP on date X (salt) or date X+1.
        
        flags = []
        if n.get('alcohol'): flags.append("🍷 Alc")
        if n.get('salty'): flags.append("🧂 Salt")
        if n.get('coffee'): flags.append("☕ Cof")
        if w > 0: flags.append("🏃 Sport")
        
        print(f"{d:<12} | {b['sys']:>3.0f}/{b['dia']:<3.0f}      | {s:>4.1f}h | {w:>3.0f} min  | {n.get('calories', 0):>4.0f}   | {', '.join(flags)}")
        
        data_points.append({
            "date": d,
            "sys": b['sys'],
            "dia": b['dia'],
            "sleep": s,
            "workout": w,
            "cals": n.get('calories', 0),
            "alcohol": n.get('alcohol'),
            "salty": n.get('salty')
        })

    # Simple Correlations
    print("\n🧐 Observations:")
    
    # 1. Alcohol impact
    alc_days = [p['sys'] for p in data_points if p['alcohol']]
    no_alc_days = [p['sys'] for p in data_points if not p['alcohol']]
    if alc_days and no_alc_days: # Check if both list contain data
        print(f"• Alcohol Days Avg BP: {statistics.mean(alc_days):.0f} (vs {statistics.mean(no_alc_days):.0f} normal)")
    
    # 2. Workout impact
    sport_days = [p['sys'] for p in data_points if p['workout'] > 10] # >10 mins
    no_sport_days = [p['sys'] for p in data_points if p['workout'] <= 10]
    if sport_days and no_sport_days: # Check if both list contain data
        print(f"• Sport Days Avg BP:   {statistics.mean(sport_days):.0f} (vs {statistics.mean(no_sport_days):.0f} no sport)")
        
    # 3. Sleep impact
    bad_sleep = [p['sys'] for p in data_points if 0 < p['sleep'] < 6.5]
    good_sleep = [p['sys'] for p in data_points if p['sleep'] >= 7.0]
    if bad_sleep and good_sleep: # Check if both list contain data
        print(f"• Bad Sleep (<6.5h) BP: {statistics.mean(bad_sleep):.0f} (vs {statistics.mean(good_sleep):.0f} good sleep)")

if __name__ == "__main__":
    analyze()
