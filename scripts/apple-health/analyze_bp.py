
import json
import os
from pathlib import Path
from datetime import datetime
from collections import defaultdict

BASE_DIR = Path("/Users/alexlyskovsky/HealthVault")
PARSED_DIR = BASE_DIR / "data" / "apple-health" / "parsed"

def get_latest_parsed_file():
    files = list(PARSED_DIR.glob("*_parsed.json"))
    if not files:
        return None
    return max(files, key=os.path.getctime)

def analyze_bp():
    latest_file = get_latest_parsed_file()
    if not latest_file:
        print("No parsed files found.")
        return

    print(f"Analyzing {latest_file.name}...")
    
    with open(latest_file, 'r') as f:
        data = json.load(f)

    systolic = []
    diastolic = []
    
    # Filter records
    for record in data.get('records', []):
        r_type = record.get('type')
        if r_type == 'HKQuantityTypeIdentifierBloodPressureSystolic':
            systolic.append(record)
        elif r_type == 'HKQuantityTypeIdentifierBloodPressureDiastolic':
            diastolic.append(record)

    print(f"Found {len(systolic)} systolic and {len(diastolic)} diastolic readings.")

    # Group by time (simple matching by exact string start date or close timestamp)
    # Apple Health usually writes separate records. We can group by startDate.
    
    measurements = defaultdict(dict)
    
    for r in systolic:
        dt = r.get('startDate')
        measurements[dt]['systolic'] = float(r.get('value'))
        measurements[dt]['date'] = dt
        measurements[dt]['source'] = r.get('sourceName')

    for r in diastolic:
        dt = r.get('startDate')
        if dt in measurements:
             measurements[dt]['diastolic'] = float(r.get('value'))
        else:
            # Try fuzzy match if needed, but usually startDate is identical for correlated samples
            measurements[dt]['diastolic'] = float(r.get('value'))
            measurements[dt]['date'] = dt
            measurements[dt]['source'] = r.get('sourceName')

    # Convert to list and sort
    results = []
    for dt, m in measurements.items():
        if 'systolic' in m and 'diastolic' in m:
            results.append(m)
    
    results.sort(key=lambda x: x['date'], reverse=True)
    
    print("\nLatest Blood Pressure Readings:")
    print("-" * 60)
    print(f"{'Date':<20} | {'BP (mmHg)':<10} | {'Source'}")
    print("-" * 60)
    
    for m in results[:10]: # Show last 10
        date_str = m['date'].replace(' +0300', '').replace('T', ' ')
        print(f"{date_str:<20} | {int(m['systolic'])}/{int(m['diastolic']):<3}    | {m['source']}")
    
    # Update stats in HEALTH.md could be done here or just print
    
if __name__ == "__main__":
    analyze_bp()
