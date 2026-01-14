#!/usr/bin/env python3
"""
Работа с данными Garmin для бота
"""

import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional

# Определяем корневую директорию HealthVault
HEALTHVAULT_ROOT = Path(__file__).parent.parent.parent
GARMIN_DIR = HEALTHVAULT_ROOT / 'data' / 'garmin' / 'daily-summary'


def get_garmin_data_for_date(date: str) -> Optional[Dict]:
    """
    Получает данные Garmin за указанную дату.
    
    Args:
        date: Дата в формате YYYY-MM-DD
        
    Returns:
        Словарь с данными Garmin или None
    """
    file_path = GARMIN_DIR / f"{date}.json"
    
    if not file_path.exists():
        return None
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('stats', {})
    except Exception as e:
        print(f"Ошибка при загрузке данных Garmin: {e}")
        return None


def get_average_stats(days: int = 14) -> Dict[str, float]:
    """
    Получает средние показатели (BMR, Active, Total) за последние N дней.
    Игнорирует дни с некорректными данными (total < 1200 ккал).
    
    Returns:
        Dict с ключами 'bmr', 'active', 'total', 'count'
    """
    valid_data = []
    
    # Собираем данные (пропускаем сегодня, так как день не закончен, берем со вчера)
    # Или берем сегодня, но проверяем порог. Лучше просто проверять порог.
    for i in range(days):
        date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
        garmin_data = get_garmin_data_for_date(date)
        
        if garmin_data:
            total = garmin_data.get('totalKilocalories', 0) or 0
            active = garmin_data.get('activeKilocalories', 0) or 0
            bmr = garmin_data.get('bmrKilocalories', 0) or 0
            
            # Фильтр битых/пустых дней (меньше BMR ребенка 1200)
            if total > 1200: 
                valid_data.append({
                    'total': total,
                    'active': active,
                    'bmr': bmr
                })
                
    count = len(valid_data)
    if count == 0:
        return {'bmr': 0.0, 'active': 0.0, 'total': 0.0, 'count': 0}
        
    # Если данных достаточно (>= 7), убираем выбросы по Total
    if count >= 7:
        valid_data.sort(key=lambda x: x['total'])
        # Убираем только если > 7 дней, по 1 снизу и сверху
        if count > 7:
            valid_data = valid_data[1:-1]
            
    avg_total = sum(d['total'] for d in valid_data) / len(valid_data)
    avg_active = sum(d['active'] for d in valid_data) / len(valid_data)
    avg_bmr = sum(d['bmr'] for d in valid_data) / len(valid_data)
    
    return {
        'bmr': round(avg_bmr),
        'active': round(avg_active),
        'total': round(avg_total),
        'count': len(valid_data)
    }


# Импорт библиотеки (пытаемся, чтобы не падать если нет)
try:
    from garminconnect import Garmin
except ImportError:
    Garmin = None

import os
import logging
from dotenv import load_dotenv

load_dotenv()
load_dotenv(HEALTHVAULT_ROOT / '.env')

logger = logging.getLogger(__name__)

def get_latest_local_date() -> Optional[datetime]:
    """Находит дату последнего сохраненного файла Garmin"""
    if not GARMIN_DIR.exists():
        return None
        
    files = sorted(GARMIN_DIR.glob('*.json'))
    if not files:
        return None
        
    last_file = files[-1]
    try:
        date_str = last_file.stem
        return datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        return None


def sync_garmin_data() -> bool:
    """
    Синхронизирует данные Garmin:
    1. Находит дату последнего локального файла.
    2. Скачивает данные за пропущенные дни (до 14 дней назад).
    3. Всегда скачивает и обновляет данные за СЕГОДНЯ.
    """
    if Garmin is None:
        logger.error("Library 'garminconnect' not found")
        return False
        
    email = os.getenv('GARMIN_EMAIL')
    password = os.getenv('GARMIN_PASSWORD')
    
    if not email or not password:
        logger.error("No Garmin credentials in .env")
        return False
        
    try:
        # 1. Auth
        client = Garmin(email, password)
        client.login()
        
        today = datetime.now()
        start_date = today
        
        # 2. Determine dates to fetch
        last_date = get_latest_local_date()
        
        if last_date:
            # Если есть старые данные, начинаем со следующего дня после последнего известного
            # НО если последний известный - это сегодня (или вчера, который мог обновиться),
            # логичнее просто перекачать диапазон [LastDate -> Today]
            # Чтобы не усложнять, берем [LastDate -> Today]
            start_date = last_date
            
            # Ограничиваем глубину истории 14 днями (чтобы не качать год при первом запуске)
            days_diff = (today - start_date).days
            if days_diff > 14:
                start_date = today - timedelta(days=14)
        else:
            # Если файлов нет вообще, берем сегодня (или можно неделю назад)
            start_date = today
            
        # Генерируем список дат [start_date, ..., today]
        dates_to_fetch = []
        current = start_date
        while current <= today:
            dates_to_fetch.append(current.strftime('%Y-%m-%d'))
            current += timedelta(days=1)
            
        # Удаляем дубли и сортируем (на всякий случай)
        dates_to_fetch = sorted(list(set(dates_to_fetch)))
        
        logger.info(f"Garmin Sync: Fetching {len(dates_to_fetch)} days: {dates_to_fetch}")
        
        # 3. Fetch Loop
        success = True
        for date_str in dates_to_fetch:
            try:
                # Daily Stats
                stats = client.get_stats(date_str)
                
                # Combine
                summary = {
                    'stats': stats
                }
                
                # Try steps
                try:
                     daily_steps = client.get_daily_steps(date_str)
                     summary['daily_steps'] = daily_steps
                except:
                     pass

                # Save
                file_path = GARMIN_DIR / f"{date_str}.json"
                GARMIN_DIR.mkdir(parents=True, exist_ok=True)
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
                    
            except Exception as e_day:
                logger.error(f"Error fetching Garmin day {date_str}: {e_day}")
                success = False # Mark partial failure but continue
                
        return success
        
    except Exception as e:
        logger.error(f"Error updating Garmin data: {e}", exc_info=True)
        return False





