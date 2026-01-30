
import json
import os
from pathlib import Path
from datetime import datetime, timedelta
import statistics

# Paths
DATA_DIR = Path('data')
WEIGHTS_APPLE = DATA_DIR / 'weights' / 'apple_health_weights.json'
WEIGHTS_DIR = DATA_DIR / 'weights'
GARMIN_DAILY = DATA_DIR / 'garmin' / 'daily-summary'
GARMIN_WORKOUTS = DATA_DIR / 'workouts_database.json'

def load_weights():
    weights = {}
    
    # 1. Apple Health
    if WEIGHTS_APPLE.exists():
        try:
            with open(WEIGHTS_APPLE, 'r') as f:
                data = json.load(f)
                for entry in data.get('entries', []):
                    d = entry.get('date')[:10] # YYYY-MM-DD
                    w = entry.get('weight_kg')
                    bf = entry.get('body_fat_percent')
                    muscle = entry.get('lean_body_mass_kg')
                    if d and w:
                        weights[d] = {
                            'weight': w, 
                            'fat': bf, 
                            'muscle': muscle,
                            'visceral_fat': None, # Not usually in Apple Health export
                            'source': 'AppleHealth'
                        }
        except Exception as e:
            print(f"Error loading Apple Health weights: {e}")

    # 2. Manual/OCR weights (Priority)
    for f in WEIGHTS_DIR.glob('2025-*.json'):
        try:
            with open(f, 'r') as file:
                data = json.load(file)
                # Handle list or single dict
                if isinstance(data, list):
                    item = data[0] if data else {}
                else:
                    item = data
                
                # Extract weight
                w = item.get('weight')
                bf = item.get('body_fat')
                
                # Extract date from filename
                d = f.stem # 2025-XX-XX
                
                if w:
                    weights[d] = {
                        'weight': w, 
                        'fat': bf, 
                        'muscle': item.get('muscle'),
                        'visceral_fat': item.get('visceral_fat'),
                        'source': 'OCR'
                    }
        except Exception as e:
            print(f"Error loading {f}: {e}")
            
    return weights

def load_garmin_daily():
    daily_stats = {}
    if not GARMIN_DAILY.exists():
        return daily_stats
        
    for f in GARMIN_DAILY.glob('2025-*.json'):
        try:
            with open(f, 'r') as file:
                data = json.load(file)
                stats = data.get('stats', {})
                
                date = stats.get('calendarDate')
                if not date: continue
                
                daily_stats[date] = {
                    'resting_hr': stats.get('restingHeartRate'),
                    'stress_avg': stats.get('averageStressLevel'),
                    'sleep_hours': (stats.get('sleepingSeconds', 0) or 0) / 3600.0,
                    'steps': stats.get('totalSteps'),
                    'body_battery_max': stats.get('bodyBatteryHighestValue'),
                    'active_cals': stats.get('activeKilocalories')
                }
        except Exception as e:
            pass
            
    return daily_stats

def load_workouts():
    workouts = {}
    if not GARMIN_WORKOUTS.exists():
        return workouts
        
    try:
        with open(GARMIN_WORKOUTS, 'r') as f:
            data = json.load(f)
            # "workouts" keys are timestamps "YYYY-MM-DD HH:MM:SS"
            for ts, w in data.get('workouts', {}).items():
                if ts.startswith('2025'):
                    date = ts[:10]
                    if date not in workouts:
                        workouts[date] = []
                    workouts[date].append(w)
    except Exception as e:
        print(f"Error loading workouts: {e}")
        
    return workouts

def calculate_monthly_stats(merged_data):
    months = {}
    for d, data in merged_data.items():
        month = d[:7] # YYYY-MM
        if month not in months:
            months[month] = {k: [] for k in ['weight', 'resting_hr', 'sleep_hours', 'visceral_fat', 'muscle']}
            months[month]['workout_count'] = 0
            
        if data.get('weight'): months[month]['weight'].append(data['weight'])
        if data.get('resting_hr'): months[month]['resting_hr'].append(data['resting_hr'])
        if data.get('sleep_hours') and data['sleep_hours'] > 0: months[month]['sleep_hours'].append(data['sleep_hours'])
        if data.get('visceral_fat'): months[month]['visceral_fat'].append(data['visceral_fat'])
        if data.get('muscle'): months[month]['muscle'].append(data['muscle'])
        if data.get('workouts'): months[month]['workout_count'] += len(data['workouts'])

    # Average them
    report = []
    for m in sorted(months.keys()):
        stats = months[m]
        row = {'month': m}
        for k in ['weight', 'resting_hr', 'sleep_hours', 'visceral_fat', 'muscle']:
            vals = stats[k]
            row[k] = round(sum(vals)/len(vals), 1) if vals else None
        row['workout_count'] = stats['workout_count']
        report.append(row)
        
    return report

def analyze_correlations(merged_data):
    # Simple correlation lists
    sleep_vs_hr = []
    activity_vs_sleep = []
    
    for d, data in merged_data.items():
        if data.get('sleep_hours') and data.get('resting_hr'):
            sleep_vs_hr.append((data['sleep_hours'], data['resting_hr']))
            
    return sleep_vs_hr

def generate_report(monthly, merged):
    lines = ["# Динамика состава тела и тренировок 2025\n"]
    
    # 1. Monthly Table
    lines.append("## 📅 Помесячная динамика")
    lines.append("| Месяц | Вес (кг) | Мышцы (кг) | Висц.Жир | Тренировок | Пульс |")
    lines.append("|---|---|---|---|---|---|")
    
    for r in monthly:
        w = f"**{r['weight']}**" if r['weight'] else "-"
        mus = r['muscle'] or "-"
        vis = r['visceral_fat'] or "-"
        wc = r['workout_count']
        hr = r['resting_hr'] or "-"
        lines.append(f"| {r['month']} | {w} | {mus} | {vis} | {wc} | {hr} |")
        
    lines.append("\n## 🔍 Анализ периода голодания (Июль-Август)")
    # Extract specific dates
    fasting_period = []
    for d in sorted(merged.keys()):
        if "2025-07-15" <= d <= "2025-08-30":
            fasting_period.append((d, merged[d]))
            
    lines.append("Динамика в период диеты/голодания:")
    lines.append("| Дата | Вес | Пульс | Сон | Стресс |")
    lines.append("|---|---|---|---|---|")
    for d, data in fasting_period:
        if data.get('weight') or data.get('resting_hr'):
             w = data.get('weight', '-')
             hr = data.get('resting_hr', '-')
             sl = round(data.get('sleep_hours', 0), 1) if data.get('sleep_hours') else '-'
             st = data.get('stress_avg', '-')
             lines.append(f"| {d[5:]} | {w} | {hr} | {sl} | {st} |")

    return "\n".join(lines)

def main():
    print("Loading data...")
    weights = load_weights()
    garmin = load_garmin_daily()
    workouts = load_workouts()
    
    # Merge
    all_dates = set(weights.keys()) | set(garmin.keys()) | set(workouts.keys())
    merged = {}
    
    for d in sorted(list(all_dates)):
        if not d.startswith('2025'): continue
        w_data = weights.get(d, {})
        merged[d] = {
            'weight': w_data.get('weight'),
            'fat': w_data.get('fat'),
            'muscle': w_data.get('muscle'),
            'visceral_fat': w_data.get('visceral_fat'),
            **garmin.get(d, {}),
            'workouts': workouts.get(d, [])
        }
        
    print(f"Merged {len(merged)} days of data.")
    
    monthly = calculate_monthly_stats(merged)
    report = generate_report(monthly, merged)
    
    with open('comprehensive_analysis_2025.md', 'w') as f:
        f.write(report)
        
    print("Report saved to comprehensive_analysis_2025.md")

if __name__ == "__main__":
    main()
