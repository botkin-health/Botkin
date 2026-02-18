import pandas as pd
import json
import os
from datetime import datetime, timedelta

DATA_DIR = "data"
GARMIN_DAILY = os.path.join(DATA_DIR, "garmin/daily-summary")
GARMIN_SLEEP = os.path.join(DATA_DIR, "garmin/sleep")
NUTRITION_LOG = os.path.join(DATA_DIR, "nutrition/nutrition_log.json")
APPLE_HEALTH_WEIGHT = os.path.join(DATA_DIR, "apple_health_weight.json")

def get_garmin_dates():
    dates = set()
    if os.path.exists(GARMIN_DAILY):
        for f in os.listdir(GARMIN_DAILY):
            if f.endswith(".json"):
                 dates.add(f.replace(".json", ""))
    return dates

def get_sleep_dates():
    dates = set()
    if os.path.exists(GARMIN_SLEEP):
        for f in os.listdir(GARMIN_SLEEP):
            if f.endswith(".json"):
                 dates.add(f.replace(".json", ""))
    return dates

def get_nutrition_dates():
    dates = set()
    try:
        with open(NUTRITION_LOG, 'r') as f:
            data = json.load(f)
        for entry in data.get('entries', []):
            if entry.get('date'):
                dates.add(entry['date'])
    except: pass
    return dates

def get_weight_dates():
    dates = set()
    try:
        with open(APPLE_HEALTH_WEIGHT, 'r') as f:
            data = json.load(f)
        for entry in data.get('measurements', []):
            if entry.get('date'):
                dates.add(entry['date'][:10])
    except: pass
    return dates

def main():
    start_date = datetime(2026, 1, 1)
    end_date = datetime.now()
    
    garmin = get_garmin_dates()
    sleep = get_sleep_dates()
    nutrition = get_nutrition_dates()
    weight = get_weight_dates()
    
    print(f"{'Datum':<12} | {'Garmin':<8} | {'Sleep':<8} | {'Nutrit':<8} | {'Weight':<8}")
    print("-" * 55)
    
    current = start_date
    while current <= end_date:
        d_str = current.strftime("%Y-%m-%d")
        
        has_garmin = "YES" if d_str in garmin else ".."
        has_sleep = "YES" if d_str in sleep else ".."
        has_nut = "YES" if d_str in nutrition else ".."
        has_weight = "YES" if d_str in weight else ".."
        
        print(f"{d_str:<12} | {has_garmin:<8} | {has_sleep:<8} | {has_nut:<8} | {has_weight:<8}")
        
        current += timedelta(days=1)

if __name__ == "__main__":
    main()
