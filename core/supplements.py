import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional

logger = logging.getLogger(__name__)

class SupplementService:
    def __init__(self):
        self.data_dir = Path(__file__).parent.parent / 'data'
        self.supplements_file = self.data_dir / 'supplements.json'
        # Log is now in data/logs/supplements/log.json
        self.log_file = self.data_dir / 'logs' / 'supplements' / 'log.json'
        # Ensure dir exists
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        
        self.schema = self._load_schema()
        self._ensure_log_file()

    def _load_schema(self) -> List[Dict]:
        """Loads static supplement definition"""
        if not self.supplements_file.exists():
            logger.error(f"Supplements schema not found at {self.supplements_file}")
            return []
        try:
            with open(self.supplements_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading supplements schema: {e}")
            return []

    def _ensure_log_file(self):
        """Ensures the log file exists"""
        if not self.log_file.exists():
            with open(self.log_file, 'w', encoding='utf-8') as f:
                json.dump({}, f)

    def _get_log(self) -> Dict:
        """Reads the intake log"""
        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_log(self, data: Dict):
        """Saves the intake log"""
        with open(self.log_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def log_intake(self, text: str) -> Tuple[List[str], List[str]]:
        """
        Parses text for supplement keywords and logs them for today.
        Smartly handles time-based duplicates (e.g. Sterols AM vs PM).
        """
        today_str = datetime.now().strftime('%Y-%m-%d')
        current_hour = datetime.now().hour
        text_lower = text.lower()
        
        # 1. Identify potential matches
        candidates = []
        for item in self.schema:
            if not item.get('is_active', True):
                continue
            
            # Check for exact matches with keywords
            matched_keyword = None
            for keyword in item['keywords']:
                if keyword in text_lower:
                    matched_keyword = keyword
                    break
            
            if matched_keyword:
                candidates.append(item)
        
        if not candidates:
            return [], []

        # 2. Filter duplicates (AM/PM logic)
        log_data = self._get_log()
        daily_log = log_data.get(today_str, {})
        
        final_ids_to_log = set()
        
        # Group duplicates by name similarity or explicit ID patterns
        # Simple heuristic: If we selected multiple items, and they have different times, 
        # we need to decide which one(s) to keep.
        
        # Helper: Check if name implies specific time
        def is_time_specific(name):
            return "утро" in name.lower() or "вечер" in name.lower() or "morning" in name.lower() or "evening" in name.lower()

        # Group candidates by "base name" (removing (Утро)/(Вечер)) to find conflicts
        groups = {}
        for item in candidates:
            # Simplify name to find pairs like "Plant Sterols (Утро)" and "Plant Sterols (Вечер)"
            base_name = item['name'].split('(')[0].strip()
            if base_name not in groups:
                groups[base_name] = []
            groups[base_name].append(item)
            
        for base_name, items in groups.items():
            if len(items) == 1:
                # No conflict, just log it
                final_ids_to_log.add(items[0]['id'])
                continue
                
            # Conflict resolution (e.g. Sterols AM vs PM)
            # Strategy:
            # 1. If user explicitly said "morning" or "evening" in text, filter by that.
            # 2. If one is already taken, take the other.
            # 3. Else, use current time.
            
            # Check for explicit time in text
            has_morning_word = any(w in text_lower for w in ["утро", "утрен", "morning"])
            has_evening_word = any(w in text_lower for w in ["вечер", "evening"])
            
            items_to_add = []
            
            for item in items:
                # If specifically requested time
                if item['time'] == 'morning' and has_morning_word:
                    items_to_add.append(item)
                elif item['time'] == 'evening' and has_evening_word:
                    items_to_add.append(item)
            
            if items_to_add:
                # Found explicit time match
                for i in items_to_add:
                    final_ids_to_log.add(i['id'])
                continue
                
            # No explicit time, check logic
            morning_item = next((i for i in items if i['time'] == 'morning'), None)
            evening_item = next((i for i in items if i['time'] == 'evening'), None)
            
            if morning_item and evening_item:
                is_am_taken = morning_item['id'] in daily_log
                is_pm_taken = evening_item['id'] in daily_log
                
                if is_am_taken and not is_pm_taken:
                    # AM taken, assume PM
                    final_ids_to_log.add(evening_item['id'])
                elif not is_am_taken and is_pm_taken:
                    # PM taken (unlikely but possible), assume AM? Or user meant PM again? 
                    # Let's assume user corrects strict order.
                    final_ids_to_log.add(morning_item['id'])
                else:
                    # Neither taken (or both). Decide by time.
                    if current_hour < 15: # Before 3 PM -> Morning
                        final_ids_to_log.add(morning_item['id'])
                    else: # After 3 PM -> Evening
                        final_ids_to_log.add(evening_item['id'])
            else:
                # Can't pair them up easily, just add all (safer)
                for i in items:
                    final_ids_to_log.add(i['id'])

        # 3. Determine names for response
        logged_names = []
        if not today_str in log_data:
            log_data[today_str] = {}
            
        for supp_id in final_ids_to_log:
            # Add to log
            log_data[today_str][supp_id] = True
            # Find name
            name = next((i['name'] for i in self.schema if i['id'] == supp_id), supp_id)
            logged_names.append(name)
            
        self._save_log(log_data)
        
        return logged_names, self.get_remaining_today()

    def get_remaining_today(self) -> List[str]:
        """Returns list of supplement names NOT yet taken today (Russian)"""
        today_str = datetime.now().strftime('%Y-%m-%d')
        log_data = self._get_log()
        daily_log = log_data.get(today_str, {})
        
        remaining = []
        
        # Translation map
        time_map = {
            'morning': 'утро',
            'day': 'день',
            'evening': 'вечер',
            'situational': 'по ситуации'
        }
        
        # Sort order
        time_order = {'morning': 1, 'day': 2, 'evening': 3, 'situational': 4}
        sorted_schema = sorted(self.schema, key=lambda x: time_order.get(x['time'], 5))
        
        for item in sorted_schema:
            if not item.get('is_active', True):
                continue
            if item['time'] == 'situational':
                continue
                
            if item['id'] not in daily_log:
                time_ru = time_map.get(item['time'], item['time'])
                # Format: "Name (time)"
                remaining.append(f"{item['name']} ({time_ru})")
                
        return remaining

    def get_brief_status(self) -> str:
        """
        Returns a compact status for /day command.
        Contains ONLY taken/remaining blocks. NO schedule.
        """
        today_str = datetime.now().strftime('%Y-%m-%d')
        log_data = self._get_log()
        daily_log = log_data.get(today_str, {})
        
        taken_names = []
        remaining_list = []
        
        time_order = {'morning': 1, 'day': 2, 'evening': 3, 'situational': 4}
        sorted_schema = sorted(self.schema, key=lambda x: time_order.get(x['time'], 5))
        
        for item in sorted_schema:
            if not item.get('is_active', True):
                continue
            
            name = item['name']
            
            if item['id'] in daily_log:
                taken_names.append(name)
            elif item['time'] != 'situational':
                remaining_list.append(f"⭕️ {name}")
                
        # Build logic
        result = "<b>💊 Витамины:</b> "
        if taken_names:
            result += "✅ " + ", ".join(taken_names)
        else:
            result += "—"
        
        if remaining_list:
            result += "\n<b>Осталось:</b> " + ", ".join(remaining_list)
        elif taken_names:
            result += "\n🎉 <b>Всё принято!</b>"
            
        return result

    def get_detailed_schedule(self) -> str:
        """
        Returns detailed status for /vitamins command.
        Includes Status + Detailed Schedule with doses.
        """
        # 1. Base Status (using brief logic but maybe formatted differently if needed)
        status_part = self.get_brief_status()
        
        # 2. Build Dynamic Schedule
        schedule_map = {'morning': [], 'evening': [], 'situational': []}
        
        for item in self.schema:
            if not item.get('is_active', True):
                continue
            
            time_key = item['time']
            if time_key not in schedule_map:
                continue
            
            # Format: "Name (Dose)"
            dose = item.get('dose', '')
            entry = f"{item['name']}"
            if dose:
                entry += f" ({dose})"
            schedule_map[time_key].append(entry)
            
        result = status_part + "\n\n<b>📋 Схема приема:</b>\n"
        
        if schedule_map['morning']:
            result += f"☀️ <b>Утро:</b> {', '.join(schedule_map['morning'])}.\n"
            
        if schedule_map['evening']:
            result += f"🌙 <b>Вечер:</b> {', '.join(schedule_map['evening'])}.\n"
            
        return result

    # Deprecated alias to keep code working if called elsewhere
    def get_daily_status(self) -> str:
        return self.get_brief_status()

# Singleton instance
supplement_service = SupplementService()
