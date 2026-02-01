
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List
import os

logger = logging.getLogger(__name__)

# NOTE: Dual-write REMOVED по решению пользователя 2026-02-01
# Стратегия: Postgres-only + автобэкап БД
# TODO: После полной миграции бота убрать JSON логику вообще

DATA_DIR = Path(__file__).parent.parent / "data" / "weights"

def save_weight_measurement(data: Dict[str, Any]) -> str:
    """
    Saves a weight measurement to JSON file.
    
    NOTE: Только JSON до полной миграции бота на Postgres.
    После миграции: данные будут писаться ТОЛЬКО в Postgres.
    JSON файлы (до 2026-02-01) остаются как архив.
    
    Args:
        data: Dict containing weight, date, source, etc.
        
    Returns:
        Path to the saved JSON file (as string).
    """
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        
        # Determine date
        date_input = data.get('date')
        if not date_input:
            date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            data['date'] = date_str
        else:
            date_str = str(date_input)
            
        # Try to parse date for filename
        try:
            # Handle various formats
            if "T" in date_str:
                dt = datetime.fromisoformat(date_str)
            elif len(date_str) == 10 and "-" in date_str: # YYYY-MM-DD
                dt = datetime.strptime(date_str, "%Y-%m-%d")
            else:
                 # Try deeper parsing for loose formats like "23 January" or "23 Jan"
                 # Default to current year if missing
                 try:
                     # Remove time part if roughly "HH:MM"
                     clean_date = date_str
                     if ":" in clean_date:
                         # Keep only date part if possible, or parse fullStr
                         pass
                     
                     # Simple heuristics
                     current_year = datetime.now().year
                     
                     # "23 January 07:41" -> parse
                     formats = [
                         "%d %B %Y %H:%M", "%d %B %Y", # With year
                         "%d %b %Y %H:%M", "%d %b %Y", 
                         "%d %B %H:%M", "%d %B",       # Without year
                         "%d %b %H:%M", "%d %b",
                         "%Y-%m-%d %H:%M", "%d.%m.%Y", "%d.%m"
                     ]
                     
                     dt = None
                     for fmt in formats:
                         try:
                             parsed = datetime.strptime(clean_date, fmt)
                             # If year is 1900 (default), set to current year
                             if parsed.year == 1900:
                                 parsed = parsed.replace(year=current_year)
                             dt = parsed
                             break
                         except ValueError:
                             continue
                             
                     if not dt:
                         dt = datetime.now()
                 except Exception:
                     dt = datetime.now()
                 
            filename = dt.strftime("%Y-%m-%d") + ".json"
            # Update data with standardized date
            data['date'] = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            filename = datetime.now().strftime("%Y-%m-%d") + ".json"
            
        file_path = DATA_DIR / filename
        
        # Load existing data if file exists (to update or append)
        # Decision: One file per day? Zepp usually has 1 main valid measurement per day.
        # Let's overwrite/update the single entry for the day to avoid duplicates,
        # OR store a list if multiple measurements.
        
        # Simple approach: Store as a list of measurements for that day
        day_measurements = []
        if file_path.exists():
            try:
                with open(file_path, 'r') as f:
                    content = json.load(f)
                    if isinstance(content, list):
                        day_measurements = content
                    else:
                        day_measurements = [content]
            except json.JSONDecodeError:
                pass
                
        # Check for duplicates
        is_duplicate = False
        new_date = data.get('date')
        new_weight = data.get('weight')
        
        for existing in day_measurements:
            if existing.get('date') == new_date and existing.get('weight') == new_weight:
                is_duplicate = True
                break
        
        if not is_duplicate:
            # Append new measurement
            day_measurements.append(data)
        
            # Save
            with open(file_path, 'w') as f:
                json.dump(day_measurements, f, indent=2, ensure_ascii=False)
                
            logger.info(f"✅ Weight saved to JSON backup: {file_path}")
        else:
            logger.info(f"Duplicate weight skipped: {new_date} / {new_weight}")
            
        return str(file_path)

    except Exception as e:
        logger.error(f"Error saving weight: {e}")
        return ""

def get_latest_weight() -> Dict[str, Any]:
    """Retrieves the most recent weight measurement."""
    try:
        if not DATA_DIR.exists():
            return {}
            
        # Find latest file
        files = sorted(DATA_DIR.glob("*.json"), reverse=True)
        if not files:
            return {}
            
        latest_file = files[0]
        with open(latest_file, 'r') as f:
            content = json.load(f)
            if isinstance(content, list) and content:
                return content[-1] # Return last entry
            elif isinstance(content, dict):
                return content
                
        return {}
    except Exception as e:
        logger.error(f"Error reading latest weight: {e}")
        return {}
