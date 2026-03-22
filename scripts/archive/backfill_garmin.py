
#!/usr/bin/env python3
"""
Скрипт для ретроспективной синхронизации данных Garmin (Backfill).
Загружает данные за последние N дней.
"""

import sys
import os
from datetime import date, timedelta
from pathlib import Path

# Добавляем корень проекта в путь
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Загружаем переменные окружения
from dotenv import load_dotenv
load_dotenv(project_root / '.env')

from core.garmin_data import sync_garmin_data

def backfill_garmin_data(days: int = 30, user_id: int = 895655):
    """
    Скачивает данные за последние days дней.
    """
    print(f"🔄 Начинаю синхронизацию Garmin за последние {days} дней...")
    
    today = date.today()
    
    for i in range(days):
        target_date = today - timedelta(days=i)
        print(f"   📅 Синхронизация {target_date}...", end=" ", flush=True)
        
        try:
            success = sync_garmin_data(user_id=user_id, sync_date=target_date)
            if success:
                print("✅ OK")
            else:
                print("❌ ERROR (Check logs)")
        except Exception as e:
            print(f"❌ Ошибка: {e}")

    print("\n✅ Синхронизация завершена.")

if __name__ == "__main__":
    days = 30
    if len(sys.argv) > 1:
        try:
            days = int(sys.argv[1])
        except ValueError:
            print(f"Usage: python {sys.argv[0]} [days]")
            sys.exit(1)
            
    backfill_garmin_data(days)
