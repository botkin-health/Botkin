import pandas as pd
import json
import os
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, timedelta
import numpy as np

# --- Configuration ---
DATA_DIR = "data"
APPLE_HEALTH_WEIGHT = os.path.join(DATA_DIR, "apple_health_weight.json")
APPLE_HEALTH_BP = os.path.join(DATA_DIR, "apple_health_blood_pressure.json")
GARMIN_DAILY = os.path.join(DATA_DIR, "garmin/daily-summary")
GARMIN_SLEEP = os.path.join(DATA_DIR, "garmin/sleep")
GARMIN_STRESS = os.path.join(DATA_DIR, "garmin/stress")
GARMIN_HRV = os.path.join(DATA_DIR, "garmin/hrv")
GARMIN_BB = os.path.join(DATA_DIR, "garmin/body-battery")
NETATMO_LOG = os.path.join(DATA_DIR, "environment/netatmo_history.json")
SCREENTIME_LOG = os.path.join(DATA_DIR, "activities/screentime_summary.json")
NUTRITION_LOG = os.path.join(DATA_DIR, "nutrition/nutrition_log.json")
WEIGHTS_DIR = os.path.join(DATA_DIR, "weights")
OUTPUT_DIR = os.path.join(DATA_DIR, "analysis")

os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- Data Loading Functions ---

def load_apple_health_weight():
    try:
        with open(APPLE_HEALTH_WEIGHT, 'r') as f:
            data = json.load(f)
        records = []
        for entry in data.get('measurements', []):
            if not entry.get('date'): continue
            records.append({
                'date': entry['date'][:10], # YYYY-MM-DD
                'weight': entry['weight_kg']
            })
        df = pd.DataFrame(records)
        if not df.empty:
            df = df.groupby('date')['weight'].mean().reset_index()
        return df
    except Exception as e:
        print(f"Ошибка загрузки веса Apple Health: {e}")
        return pd.DataFrame(columns=['date', 'weight'])

def load_body_composition():
    records = []
    if not os.path.exists(WEIGHTS_DIR): return pd.DataFrame()
    
    for filename in os.listdir(WEIGHTS_DIR):
        if not filename.endswith('.json') or filename == 'apple_health_weights.json' or filename == 'body_measurements.json': continue
        try:
            with open(os.path.join(WEIGHTS_DIR, filename), 'r') as f:
                data = json.load(f)
            
            # Data can be a list or a dict
            if isinstance(data, list):
                entries = data
            else:
                entries = [data]
                
            for entry in entries:
                date_str = entry.get('date') or entry.get('measured_at')
                if not date_str: continue
                # Handle "2026-01-14 21:10" format
                if len(date_str) > 10:
                    date_str = date_str[:10]
                
                records.append({
                    'date': date_str,
                    'visceral_fat': entry.get('visceral_fat'),
                    'muscle_mass': entry.get('muscle') or entry.get('muscle_mass'),
                    'water_percent': entry.get('water'),
                    'bone_mass': entry.get('bone_mass'),
                    # Try to find fat
                    'fat_percent': entry.get('fat') or entry.get('body_fat') or entry.get('fat_percentage')
                })
        except: pass
        
    df = pd.DataFrame(records)
    if not df.empty:
        # Average if multiple same day
        df = df.groupby('date').mean().reset_index()
    return df

def load_apple_health_bp():
    try:
        with open(APPLE_HEALTH_BP, 'r') as f:
            data = json.load(f)
        records = []
        for entry in data.get('measurements', []):
            if not entry.get('date'): continue
            records.append({
                'date': entry['date'][:10],
                'systolic': entry['systolic'],
                'diastolic': entry['diastolic']
            })
        df = pd.DataFrame(records)
        if not df.empty:
            df = df.groupby('date')[['systolic', 'diastolic']].mean().reset_index()
        return df
    except Exception as e:
        print(f"Ошибка загрузки давления Apple Health: {e}")
        return pd.DataFrame(columns=['date', 'systolic', 'diastolic'])

def load_garmin_daily():
    records = []
    if not os.path.exists(GARMIN_DAILY): return pd.DataFrame()
    for filename in os.listdir(GARMIN_DAILY):
        if not filename.endswith('.json'): continue
        try:
            with open(os.path.join(GARMIN_DAILY, filename), 'r') as f:
                data = json.load(f)
            
            # Structure check: 'stats' key usually holds the daily summary
            stats = data.get('stats', {}) if 'stats' in data else data
            
            date = stats.get('calendarDate')
            if not date: continue
            
            records.append({
                'date': date,
                'steps': stats.get('totalSteps'),
                'total_cals': stats.get('totalKilocalories'),
                'active_cals': stats.get('activeKilocalories'),
                'resting_cals': stats.get('bmrKilocalories'),
                'max_hr': stats.get('maxHeartRate'),
                'resting_hr': stats.get('restingHeartRate'),
                'min_hr': stats.get('minHeartRate'),
            })
        except: pass
    return pd.DataFrame(records)

def load_garmin_sleep():
    records = []
    if not os.path.exists(GARMIN_SLEEP): return pd.DataFrame()
    for filename in os.listdir(GARMIN_SLEEP):
        if not filename.endswith('.json'): continue
        try:
            with open(os.path.join(GARMIN_SLEEP, filename), 'r') as f:
                data = json.load(f)
            
            # Structure check: 'dailySleepDTO'
            sleep_dto = data.get('dailySleepDTO', {})
            date = sleep_dto.get('calendarDate')
            if not date: continue
            
            records.append({
                'date': date,
                'sleep_hours': sleep_dto.get('sleepTimeSeconds', 0) / 3600,
                'sleep_score': sleep_dto.get('sleepScores', {}).get('overall', {}).get('value'),
                'deep_sleep_hours': sleep_dto.get('deepSleepSeconds', 0) / 3600,
                'rem_sleep_hours': sleep_dto.get('remSleepSeconds', 0) / 3600,
                'awake_sleep_hours': sleep_dto.get('awakeSleepSeconds', 0) / 3600
            })
        except: pass
    return pd.DataFrame(records)

def load_garmin_stress():
    records = []
    if not os.path.exists(GARMIN_STRESS): return pd.DataFrame()
    for filename in os.listdir(GARMIN_STRESS):
        if not filename.endswith('.json'): continue
        try:
            with open(os.path.join(GARMIN_STRESS, filename), 'r') as f:
                data = json.load(f)
            
            # Structure check: top level
            date = data.get('calendarDate')
            if not date: continue

            records.append({
                'date': date,
                'avg_stress': data.get('avgStressLevel'),
                'max_stress': data.get('maxStressLevel'),
                'rest_stress_duration': data.get('restStressDuration'),
                'low_stress_duration': data.get('lowStressDuration'),
                'medium_stress_duration': data.get('mediumStressDuration'),
                'high_stress_duration': data.get('highStressDuration')
            })
        except: pass
    return pd.DataFrame(records)

def load_garmin_hrv():
    records = []
    if not os.path.exists(GARMIN_HRV): return pd.DataFrame()
    for filename in os.listdir(GARMIN_HRV):
        if not filename.endswith('.json'): continue
        try:
            with open(os.path.join(GARMIN_HRV, filename), 'r') as f:
                data = json.load(f)
            summary = data.get('hrvSummary', {})
            date = summary.get('calendarDate')
            if not date: continue
            records.append({
                'date': date,
                'hrv_last_night': summary.get('lastNightAvg')
            })
        except: pass
    return pd.DataFrame(records)

def load_garmin_bb():
    records = []
    if not os.path.exists(GARMIN_BB): return pd.DataFrame()
    for filename in os.listdir(GARMIN_BB):
        if not filename.endswith('.json'): continue
        try:
            with open(os.path.join(GARMIN_BB, filename), 'r') as f:
                data = json.load(f)
            if isinstance(data, list) and len(data) > 0:
                data = data[0]
            date = data.get('date')
            if not date: continue
            records.append({
                'date': date,
                'bb_charged': data.get('charged'),
                'bb_drained': data.get('drained')
            })
        except: pass
    return pd.DataFrame(records)

def load_netatmo():
    records = []
    if not os.path.exists(NETATMO_LOG): return pd.DataFrame()
    try:
        with open(NETATMO_LOG, 'r') as f:
            data = json.load(f)
        daily_data = {}
        target_station = "Большевик"
        if target_station in data:
            for ts_str, values in data[target_station].items():
                if len(values) >= 4:
                    dt = datetime.fromtimestamp(int(ts_str)).strftime('%Y-%m-%d')
                    if dt not in daily_data:
                        daily_data[dt] = {'temp': [], 'co2': [], 'noise': []}
                    daily_data[dt]['temp'].append(values[0])
                    daily_data[dt]['co2'].append(values[1])
                    daily_data[dt]['noise'].append(values[3])   
            for dt, vals in daily_data.items():
                records.append({
                    'date': dt,
                    'netatmo_temp': sum(vals['temp'])/len(vals['temp']),
                    'netatmo_co2': sum(vals['co2'])/len(vals['co2']),
                    'netatmo_noise': sum(vals['noise'])/len(vals['noise'])
                })
    except: pass
    return pd.DataFrame(records)

def load_screentime():
    records = []
    if not os.path.exists(SCREENTIME_LOG): return pd.DataFrame()
    try:
        with open(SCREENTIME_LOG, 'r') as f:
            data = json.load(f)
        for dt, item in data.items():
            records.append({
                'date': dt,
                'st_total_hours': item.get('total_hours'),
                'st_pickups': item.get('pickups'),
                'st_prebed': item.get('prebed_hours')
            })
    except: pass
    return pd.DataFrame(records)

def load_nutrition():
    data_map = {} # date -> {calories, protein, fats, carbs}
    
    # 1. Load Local (Legacy/Current)
    try:
        if os.path.exists(NUTRITION_LOG):
            with open(NUTRITION_LOG, 'r') as f:
                data = json.load(f)
            for entry in data.get('entries', []):
                d = entry.get('date')
                if not d: continue
                totals = entry.get('totals', {})
                data_map[d] = {
                    'nutrition_cals': totals.get('calories', 0),
                    'protein_g': totals.get('protein', 0),
                    'fats_g': totals.get('fats', 0),
                    'carbs_g': totals.get('carbs', 0)
                }
    except Exception as e:
        print(f"Ошибка загрузки локального питания: {e}")

    # 2. Load Remote (Netherlands Server)
    # Aggregate remote data separately first to avoid double counting if we assume remote is the source of truth for those days
    remote_map = {} 

    remote_path = os.path.join(DATA_DIR, "nutrition/nutrition_log_remote.json")
    try:
        if os.path.exists(remote_path):
            with open(remote_path, 'r') as f:
                content = f.read().strip()
                if content:
                    # Fix psql COPY output artifacts
                    content = content.replace('\\\\', '\\') 
                    content = content.replace('\\n', ' ')   
                    content = content.replace('\\r', '')    
                    
                    if content.startswith('"') and content.endswith('"'):
                         try:
                             content = json.loads(content) 
                         except: pass

                    try:
                        remote_data = json.loads(content)
                    except json.JSONDecodeError as e:
                        print(f"Failed to decode remote JSON: {e}")
                        # print(f"Context: {content[max(0, e.pos-20):min(len(content), e.pos+20)]}")
                        remote_data = []

                    # Expected format: flat list of objects OR list of lists
                    # Check first element type
                    if isinstance(remote_data, list) and len(remote_data) > 0:
                        first = remote_data[0]
                        if isinstance(first, list):
                            # It's a list of lists: [date, time, items, totals]
                            for row in remote_data:
                                if len(row) >= 4:
                                    d = row[0]
                                    totals = row[3]
                                    if not isinstance(totals, dict): continue
                                    
                                    if d not in remote_map:
                                        remote_map[d] = {'nutrition_cals': 0, 'protein_g': 0, 'fats_g': 0, 'carbs_g': 0}
                                    
                                    # Aggregate meals
                                    remote_map[d]['nutrition_cals'] += totals.get('calories', 0)
                                    remote_map[d]['protein_g'] += totals.get('protein', 0)
                                    remote_map[d]['fats_g'] += totals.get('fats', 0)
                                    remote_map[d]['carbs_g'] += totals.get('carbs', 0)
                                    
                        elif isinstance(first, dict):
                            # It's a list of objects (maybe from json_agg of row_to_json)
                            for row in remote_data:
                                d = row.get('date')
                                totals = row.get('totals')
                                
                                if d and isinstance(totals, dict):
                                    if d not in remote_map:
                                        remote_map[d] = {'nutrition_cals': 0, 'protein_g': 0, 'fats_g': 0, 'carbs_g': 0}
                                    
                                    remote_map[d]['nutrition_cals'] += totals.get('calories', 0)
                                    remote_map[d]['protein_g'] += totals.get('protein', 0)
                                    remote_map[d]['fats_g'] += totals.get('fats', 0)
                                    remote_map[d]['carbs_g'] += totals.get('carbs', 0)

    except Exception as e:
        print(f"Ошибка загрузки удаленного питания: {e}")

    # Merge Remote into Main (Overwrite local)
    for d, v in remote_map.items():
        data_map[d] = v

    # Add alcohol flag
    alcohol_keywords = ["вино", "пиво", "ром\b", "виски", "водка", "негрони", "сидр", "коньяк", "джин", "текила"]
    
    # Needs to process text for alcohol, but since we already aggregated by date and lost the raw text in data_map, 
    # we need to re-parse or add the check inside the remote_date loop.
    # Let's patch the remote loop above, but also apply it retroactively here if we re-read.
    # Actually, let's just initialize it to 0 then update it below correctly.
    for d in data_map:
        if 'alcohol_flag' not in data_map[d]:
            data_map[d]['alcohol_flag'] = 0
            
    # Quick pass over remote data again to catch alcohol words
    try:
        if isinstance(remote_data, list):
            for row in remote_data:
                d = None
                items_str = ""
                if isinstance(row, list) and len(row) >= 4:
                    d = row[0]
                    items_str = str(row[2]).lower()
                elif isinstance(row, dict):
                    d = row.get('date')
                    items_str = str(row.get('items', '')).lower() + " " + str(row.get('meal_name', '')).lower()
                
                if d and d in data_map:
                    for kw in alcohol_keywords:
                        if kw in items_str:
                            data_map[d]['alcohol_flag'] = 1
                            break
    except: pass

    records = []
    for d, v in data_map.items():
        records.append({
            'date': d,
            'nutrition_cals': v['nutrition_cals'],
            'protein_g': v['protein_g'],
            'fats_g': v['fats_g'],
            'carbs_g': v['carbs_g'],
            'alcohol_flag': v.get('alcohol_flag', 0)
        })
    return pd.DataFrame(records)

    records = []
    for d, v in data_map.items():
        records.append({
            'date': d,
            'nutrition_cals': v['nutrition_cals'],
            'protein_g': v['protein_g'],
            'fats_g': v['fats_g'],
            'carbs_g': v['carbs_g']
        })
    return pd.DataFrame(records)


# --- Main Analysis ---

def main():
    print("Загрузка данных...")
    df_weight = load_apple_health_weight()
    df_comp = load_body_composition()
    df_bp = load_apple_health_bp()
    df_daily = load_garmin_daily()
    df_sleep = load_garmin_sleep()
    df_stress = load_garmin_stress()
    df_hrv = load_garmin_hrv()
    df_bb = load_garmin_bb()
    df_netatmo = load_netatmo()
    df_screentime = load_screentime()
    df_nutrition = load_nutrition()
    
    print(f"Загружено: Вес {len(df_weight)}, Состав {len(df_comp)}, АД {len(df_bp)}, Garmin {len(df_daily)}, Сон {len(df_sleep)}, Стресс {len(df_stress)}, HRV {len(df_hrv)}, Netatmo {len(df_netatmo)}, Экраны {len(df_screentime)}")

    # Merge all
    print("Объединение данных...")
    dfs = [df_weight, df_comp, df_bp, df_daily, df_sleep, df_stress, df_hrv, df_bb, df_netatmo, df_screentime, df_nutrition]
    df_final = None
    
    for i, df in enumerate(dfs):
        if df.empty: continue
        # Normalize date column type just in case
        if 'date' in df.columns:
             df['date'] = df['date'].astype(str)
             
        if df_final is None:
            df_final = df
        else:
            df_final = pd.merge(df_final, df, on='date', how='outer')
            
    if df_final is None or df_final.empty:
        print("Данные не найдены!")
        return

    # Filter out None dates before converting
    df_final = df_final[df_final['date'].notna()]
    df_final = df_final[df_final['date'] != 'None']

    df_final['date'] = pd.to_datetime(df_final['date'])
    df_final = df_final.sort_values('date')
    
    # Filter for relevant period (Jan-Feb 2026)
    df_final = df_final[df_final['date'] >= '2026-01-01']
    
    # --- Derived Metrics ---
    if 'total_cals' in df_final.columns and 'nutrition_cals' in df_final.columns:
        df_final['calorie_deficit'] = df_final['total_cals'] - df_final['nutrition_cals']
    else:
        df_final['calorie_deficit'] = np.nan

    # --- Analysis Summary ---
    summary = []
    summary.append(f"Период анализа: {df_final['date'].min().date()} — {df_final['date'].max().date()}")
    summary.append(f"Всего дней: {len(df_final)}")
    
    cols_map = {
        'weight': 'Вес',
        'visceral_fat': 'Висцеральный жир',
        'fat_percent': 'Процент жира',
        'muscle_mass': 'Мышечная масса',
        'nutrition_cals': 'Калории (Еда)',
        'total_cals': 'Калории (Расход)',
        'steps': 'Шаги',
        'sleep_hours': 'Сон (часы)',
        'sleep_score': 'Качество сна',
        'avg_stress': 'Стресс (средний)',
        'hrv_last_night': 'ВСР (Ночная)',
        'bb_charged': 'Заряд Body Battery',
        'netatmo_co2': 'CO2 (Спальня)',
        'netatmo_noise': 'Шум (Спальня)',
        'st_total_hours': 'Экранное время',
        'st_pickups': 'Отвлечения телефона',
        'alcohol_flag': 'Алкоголь (день)',
        'systolic': 'Давление (верхнее)',
        'diastolic': 'Давление (нижнее)',
        'calorie_deficit': 'Дефицит калорий',
        'resting_hr': 'Пульс в покое',
        'fat_percent': 'Процент жира',
        'water_percent': 'Процент воды',
        'muscle_mass': 'Мышечная масса',
        'visceral_fat': 'Висцеральный жир'
    }
    
    cols_of_interest = list(cols_map.keys())
    # Check if cols exist
    available_cols = [c for c in cols_of_interest if c in df_final.columns]
    
    # Calculate correlation matrix
    if len(available_cols) > 1:
        corr_matrix = df_final[available_cols].corr()
        # Rename index and columns for Russian output
        corr_matrix_rus = corr_matrix.rename(index=cols_map, columns=cols_map)
        
        summary.append("\n--- Корреляции с Весом ---")
        if 'weight' in corr_matrix:
            summary.append(corr_matrix_rus.loc['Вес'].sort_values(ascending=False).to_string())
        
        summary.append("\n--- Корреляции с Давлением (Верхнее) ---")
        if 'systolic' in corr_matrix:
            summary.append(corr_matrix_rus.loc['Давление (верхнее)'].sort_values(ascending=False).to_string())
        
        summary.append("\n--- Корреляции со Стрессом ---")
        if 'avg_stress' in corr_matrix:
            summary.append(corr_matrix_rus.loc['Стресс (средний)'].sort_values(ascending=False).to_string())
            
        summary.append("\n--- Сон и Стресс ---")
        if 'sleep_score' in corr_matrix and 'avg_stress' in corr_matrix:
            summary.append(f"Корреляция Качество Сна vs Стресс: {corr_matrix.loc['sleep_score', 'avg_stress']:.2f}")

    summary.append("\n--- Средние показатели (2026) ---")
    summary.append(df_final[available_cols].rename(columns=cols_map).mean().to_string())
    
    # Body Composition Check
    summary.append("\n--- Состав тела: Динамика ---")
    if 'visceral_fat' in df_final.columns:
        first_valid = df_final['visceral_fat'].dropna().iloc[0] if not df_final['visceral_fat'].dropna().empty else "N/A"
        last_valid = df_final['visceral_fat'].dropna().iloc[-1] if not df_final['visceral_fat'].dropna().empty else "N/A"
        summary.append(f"Висцеральный жир: {first_valid} -> {last_valid}")

    if 'fat_percent' in df_final.columns:
        first_valid_fat = df_final['fat_percent'].dropna().iloc[0] if not df_final['fat_percent'].dropna().empty else "N/A"
        last_valid_fat = df_final['fat_percent'].dropna().iloc[-1] if not df_final['fat_percent'].dropna().empty else "N/A"
        summary.append(f"Процент жира: {first_valid_fat} -> {last_valid_fat}")
    
    # Save Summary
    with open(os.path.join(OUTPUT_DIR, "analysis_summary.txt"), "w", encoding='utf-8') as f:
        f.write("\n".join(summary))
    print("Отчет сохранен.")

    # --- Plotting ---
    sns.set_theme(style="whitegrid")
    
    # Plot 1: Weight & Calories
    if 'weight' in df_final.columns and 'calorie_deficit' in df_final.columns:
        fig, ax1 = plt.subplots(figsize=(12, 6))
        color = 'tab:red'
        ax1.set_xlabel('Дата')
        ax1.set_ylabel('Вес (кг)', color=color)
        sns.lineplot(data=df_final, x='date', y='weight', ax=ax1, color=color, marker='o', label='Вес')
        ax1.tick_params(axis='y', labelcolor=color)
        
        ax2 = ax1.twinx()  
        color = 'tab:blue'
        ax2.set_ylabel('Дефицит калорий', color=color)
        # Barplot using matplotlib directly
        ax2.bar(df_final['date'], df_final['calorie_deficit'], color=color, alpha=0.3, label='Дефицит')
        ax2.tick_params(axis='y', labelcolor=color)
        
        plt.title('Динамика Веса и Дефицита Калорий')
        fig.autofmt_xdate()
        plt.savefig(os.path.join(OUTPUT_DIR, "weight_deficit.png"))
        plt.close()
    
    # Plot 2: Stress vs Sleep
    if 'avg_stress' in df_final.columns and 'sleep_score' in df_final.columns:
        plt.figure(figsize=(10, 6))
        sns.scatterplot(
            data=df_final, 
            x='avg_stress', 
            y='sleep_score', 
            size='steps' if 'steps' in df_final.columns else None, 
            sizes=(20, 200),
            hue='resting_hr' if 'resting_hr' in df_final.columns else None
        )
        plt.title('Взаимосвязь Качества Сна и Стресса')
        plt.xlabel('Средний уровень стресса')
        plt.ylabel('Оценка сна (Sleep Score)')
        plt.savefig(os.path.join(OUTPUT_DIR, "stress_sleep.png"))
        plt.close()
    
    # Plot 3: BP Trends
    if 'systolic' in df_final.columns and df_final['systolic'].notna().sum() > 0:
        plt.figure(figsize=(12, 6))
        sns.lineplot(data=df_final, x='date', y='systolic', label='Верхнее', marker='o')
        sns.lineplot(data=df_final, x='date', y='diastolic', label='Нижнее', marker='o')
        plt.axhline(y=120, color='r', linestyle='--', alpha=0.5, label='Норма 120/80')
        plt.axhline(y=80, color='r', linestyle='--', alpha=0.5)
        plt.title('Тренды Артериального Давления')
        plt.xlabel('Дата')
        plt.ylabel('мм рт. ст.')
        plt.legend()
        plt.savefig(os.path.join(OUTPUT_DIR, "bp_trend.png"))
        plt.close()

    # Plot 4: Body Composition (New)
    if 'visceral_fat' in df_final.columns and df_final['visceral_fat'].notna().sum() > 1:
        fig, ax1 = plt.subplots(figsize=(12, 6))
        color = 'tab:orange'
        ax1.set_xlabel('Дата')
        ax1.set_ylabel('Висцеральный жир', color=color)
        sns.lineplot(data=df_final, x='date', y='visceral_fat', ax=ax1, color=color, marker='o', label='Висцеральный')
        ax1.tick_params(axis='y', labelcolor=color)
        
        # If fat percent exists, plot on right axis
        if 'fat_percent' in df_final.columns and df_final['fat_percent'].notna().sum() > 1:
            ax2 = ax1.twinx()
            color = 'tab:green'
            ax2.set_ylabel('Процент жира (%)', color=color)
            sns.lineplot(data=df_final, x='date', y='fat_percent', ax=ax2, color=color, marker='s', linestyle='--', label='% Жира')
            ax2.tick_params(axis='y', labelcolor=color)
            
        plt.title('Динамика Состава Тела')
        fig.autofmt_xdate()
        plt.savefig(os.path.join(OUTPUT_DIR, "body_comp.png"))
        plt.close()
        
    print("Графики сохранены.")

if __name__ == "__main__":
    main()
