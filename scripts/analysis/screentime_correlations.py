import json
import os
import glob
from collections import defaultdict
from datetime import datetime

with open('data/activities/screentime_summary.json', 'r') as f:
    st_data = {item['date']: item for item in json.load(f)}

with open('data/environment/netatmo_history.json', 'r') as f:
    netatmo_data = json.load(f)

co2_by_date = {}
if 'Большевик' in netatmo_data:
    for ts_str, metrics in netatmo_data['Большевик'].items():
        dt = datetime.fromtimestamp(int(ts_str))
        date_str = dt.strftime('%Y-%m-%d')
        if len(metrics) > 1 and metrics[1] is not None:
            if date_str not in co2_by_date: co2_by_date[date_str] = []
            co2_by_date[date_str].append(metrics[1])

print("Date       | Sleep Score | Deep % | Stress | Pickups | Night CO2 | Mg Hr | PreBed ST | Total ST")
print("-" * 100)

results = []
for date_str, st in st_data.items():
    sleep_file = f"data/garmin/sleep/{date_str}.json"
    if not os.path.exists(sleep_file):
        continue
        
    with open(sleep_file, 'r') as f:
        try:
            sleep_entry = json.load(f).get('dailySleepDTO', {})
            duration_in_s = sleep_entry.get('sleepTimeSeconds', 0)
            deep_sleep_s = sleep_entry.get('deepSleepSeconds', 0)
            score = sleep_entry.get('sleepScores', {}).get('overall', {}).get('value', 0)
            stress = sleep_entry.get('avgSleepStress', 0)
            
            total_hours = duration_in_s / 3600
            deep_pct = (deep_sleep_s / duration_in_s * 100) if duration_in_s else 0
            
            co2_avg = " N/A "
            if date_str in co2_by_date and co2_by_date[date_str]:
                co2_avg = str(int(sum(co2_by_date[date_str]) / len(co2_by_date[date_str])))
            
            results.append({
                'Date': date_str,
                'SleepScore': score,
                'DeepSleep_pct': round(deep_pct, 1),
                'Stress': stress,
                'PreBedST_hr': st['pre_bed_hours'],
                'TotalST_hr': st['total_hours'],
                'Msg_hr': st['categories_hours'].get('Messengers', 0),
                'Pickups': st['pickups_count'],
                'CO2': co2_avg
            })
        except Exception as e:
            continue

results.sort(key=lambda x: x['Date'])

for r in results:
    co2 = r['CO2']
    print(f"{r['Date']} |     {r['SleepScore']:2}      |  {r['DeepSleep_pct']:4.1f}  |   {r['Stress']:2}   |   {r['Pickups']:2}    |   {co2:>5}   |  {r['Msg_hr']:4.1f} |   {r['PreBedST_hr']:4.2f}    |  {r['TotalST_hr']:4.1f}")

