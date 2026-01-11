
import json

with open('data/nutrition/nutrition_log.json', 'r') as f:
    data = json.load(f)
    print(data.keys())
    if 'logs' not in data:
        # Maybe it's a list itself?
        if isinstance(data, list):
             print("Root is a list")
    
    # Print first few keys/elements to see structure
