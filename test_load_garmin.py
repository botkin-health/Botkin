import pandas as pd
import json
import os

GARMIN_DAILY = "data/garmin/daily-summary"
filename = "2026-01-01.json"
filepath = os.path.join(GARMIN_DAILY, filename)

try:
    with open(filepath, 'r') as f:
        data = json.load(f)
    print(f"Loaded {filename}")
    print(f"Keys: {list(data.keys())}")
    print(f"Date: {data.get('calendarDate')}")
    print(f"Steps: {data.get('totalSteps')}")
    
except Exception as e:
    print(f"Error: {e}")
