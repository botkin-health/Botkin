#!/usr/bin/env python3
import sqlite3
import os
import json
from datetime import datetime
import shutil

# Database paths (usually requires Full Disk Access)
DB_PATH = os.path.expanduser('~/Library/Application Support/Knowledge/knowledgeC.db')
TMP_DB_PATH = '/tmp/knowledgeC.db'  # Copy to avoid locking issues

# CoreData timestamp epoch (Jan 1, 2001) vs Unix epoch (Jan 1, 1970)
MAC_EPOCH_OFFSET = 978307200

def get_screen_time():
    if not os.path.exists(DB_PATH):
        print(f"❌ Ошибка: Файл базы данных не найден по пути {DB_PATH}.")
        print("Если у вас macOS 13+, данные могут храниться в Biome. Убедитесь, что у скрипта есть 'Полный доступ к диску' (Full Disk Access).")
        return []

    print(f"Копирование базы из {DB_PATH} во временный файл...")
    try:
        shutil.copy2(DB_PATH, TMP_DB_PATH)
    except PermissionError:
        print("❌ Ошибка прав доступа (Permission Denied).")
        print("❗️ Пожалуйста, зайдите в 'System Settings' -> 'Privacy & Security' -> 'Full Disk Access'")
        print("❗️ И дайте полный доступ вашей программе Terminal (или iTerm/Python).")
        return []

    print("Подключение к базе данных...")
    conn = sqlite3.connect(TMP_DB_PATH)
    cur = conn.cursor()

    # Запрос на использование приложений
    query_usage = """
    SELECT 
        datetime(ZOBJECT.ZSTARTDATE + 978307200, 'unixepoch', 'localtime') as start_time,
        datetime(ZOBJECT.ZENDDATE + 978307200, 'unixepoch', 'localtime') as end_time,
        (ZOBJECT.ZENDDATE - ZOBJECT.ZSTARTDATE) as duration_seconds,
        ZOBJECT.ZVALUESTRING as bundle_id,
        ZSOURCE.ZDEVICEID as device_id
    FROM ZOBJECT 
    LEFT JOIN ZSTRUCTUREDMETADATA ON ZOBJECT.ZSTRUCTUREDMETADATA = ZSTRUCTUREDMETADATA.Z_PK
    LEFT JOIN ZSOURCE ON ZOBJECT.ZSOURCE = ZSOURCE.Z_PK
    WHERE ZSTREAMNAME = '/app/usage' AND ZSTARTDATE >= 788918400
    ORDER BY ZSTARTDATE DESC;
    """
    
    # Запрос на разблокировки экрана (pickups / экран активен)
    query_pickups = """
    SELECT 
        datetime(ZSTARTDATE + 978307200, 'unixepoch', 'localtime') as pickup_time,
        ZVALUEINTEGER as is_backlit,
        ZSOURCE.ZDEVICEID as device_id
    FROM ZOBJECT
    LEFT JOIN ZSOURCE ON ZOBJECT.ZSOURCE = ZSOURCE.Z_PK
    WHERE ZSTREAMNAME = '/display/isBacklit' AND ZVALUEINTEGER = 1 AND ZSTARTDATE >= 788918400
    ORDER BY ZSTARTDATE DESC;
    """
    
    try:
        cur.execute(query_usage)
        usage_rows = cur.fetchall()
        
        cur.execute(query_pickups)
        pickup_rows = cur.fetchall()
        
        events = []
        for row in usage_rows:
            events.append({
                "type": "app_usage",
                "start_time": row[0],
                "end_time": row[1],
                "duration_seconds": row[2],
                "bundle_id": row[3],
                "device_id": row[4]
            })
            
        pickups = []
        for row in pickup_rows:
            pickups.append({
                "type": "screen_pickup",
                "time": row[0],
                "device_id": row[2]
            })
            
        print(f"✅ Извлечено {len(events)} событий использования приложений и {len(pickups)} разблокировок экрана.")
        return events, pickups
        
    except sqlite3.OperationalError as e:
        print(f"❌ Ошибка SQL: {e}")
        return []
    finally:
        conn.close()
        # Clean up temp DB
        if os.path.exists(TMP_DB_PATH):
            os.remove(TMP_DB_PATH)

def generate_summary(events, pickups):
    from collections import defaultdict
    from datetime import datetime
    
    daily_st = defaultdict(float)
    hourly_st = defaultdict(lambda: defaultdict(float))
    daily_pickups = defaultdict(int)
    daily_categories = defaultdict(lambda: defaultdict(float))
    
    # Simple app categorization based on bundle id
    SOCIAL_APPS = ['instagram', 'facebook', 'tiktok', 'twitter', 'vk', 'youtube']
    MSG_APPS = ['telegram', 'whatsapp', 'messages', 'viber']
    WORK_APPS = ['slack', 'mail', 'notion', 'zoom', 'safari', 'chrome', 'docs']
    
    def categorize(bundle):
        if not bundle: return "Other"
        b = bundle.lower()
        if any(x in b for x in SOCIAL_APPS): return "Social & Entertainment"
        if any(x in b for x in MSG_APPS): return "Messengers"
        if any(x in b for x in WORK_APPS): return "Work & Web"
        return "Other"
    
    for e in events:
        if not e['start_time']: continue
        try:
            dt = datetime.strptime(e['start_time'], '%Y-%m-%d %H:%M:%S')
            date_str = dt.strftime('%Y-%m-%d')
            hour_str = dt.strftime('%H')
            duration = e.get('duration_seconds', 0)
            if duration is None: duration = 0
            
            daily_st[date_str] += duration
            hourly_st[date_str][hour_str] += duration
            
            cat = categorize(e.get('bundle_id'))
            daily_categories[date_str][cat] += duration
        except Exception:
            continue
            
    for p in pickups:
        if not p.get('time'): continue
        try:
            dt = datetime.strptime(p['time'], '%Y-%m-%d %H:%M:%S')
            daily_pickups[dt.strftime('%Y-%m-%d')] += 1
        except Exception:
            continue
            
    summary = []
    for d in sorted(daily_st.keys()):
        hours = daily_st[d] / 3600
        prebed_st = sum([hourly_st[d].get(str(h).zfill(2), 0) for h in range(21, 24)]) / 3600
        
        cats = {k: round(v/3600, 2) for k, v in daily_categories[d].items()}
        
        summary.append({
            "date": d,
            "total_hours": round(hours, 2),
            "pre_bed_hours": round(prebed_st, 2),
            "pickups_count": daily_pickups[d],
            "categories_hours": cats
        })
    return summary

def save_to_json(data, output_file):
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Данные сохранены в {output_file}")

if __name__ == '__main__':
    result = get_screen_time()
    if result and len(result) == 2:
        events, pickups = result
        
        # Save only the short summary, avoid saving the entire raw timeline
        summary = generate_summary(events, pickups)
        save_to_json(summary, 'data/activities/screentime_summary.json')
        print(f"✅ Аналитическая выжимка за последние {len(summary)} дней успешно сформирована.")
