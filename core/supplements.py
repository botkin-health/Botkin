"""
Supplement Service - PostgreSQL Version

Управление добавками и витаминами через PostgreSQL
"""

import logging
from datetime import datetime, date, time as time_type
from typing import List, Dict, Optional

from database import (
    SessionLocal,
    get_supplements_by_date,
    create_supplement_log
)

logger = logging.getLogger(__name__)


def save_supplements(items: List[str], user_id: int = 895655, date_str: Optional[str] = None) -> bool:
    """
    Сохраняет список принятых витаминов/БАДов в PostgreSQL
    
    Args:
        items: Список названий (например ["Magnesium", "Zinc"])
        user_id: Telegram ID пользователя
        date_str: Дата YYYY-MM-DD
        
    Returns:
        True if successful
    """
    if not items:
        return False
        
    if not date_str:
        date_str = datetime.now().strftime('%Y-%m-%d')
    
    target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    current_time = datetime.now().time()
    
    db = SessionLocal()
    try:
        # Add new items with timestamp
        for item in items:
            create_supplement_log(
                db,
                user_id=user_id,
                date=target_date,
                time=current_time,
                supplement_name=item,
                dosage=None
            )
        
        return True
    except Exception as e:
        logger.error(f"Error saving supplements: {e}")
        return False
    finally:
        db.close()


def get_today_supplements(user_id: int = 895655, date_str: Optional[str] = None) -> List[Dict]:
    """
    Возвращает список принятого за указанную дату
    
    Args:
        user_id: Telegram ID пользователя
        date_str: Дата YYYY-MM-DD (если None - сегодня)
        
    Returns:
        List of dicts with 'name' and 'time' keys
    """
    if not date_str:
        date_str = datetime.now().strftime('%Y-%m-%d')
        
    target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    
    db = SessionLocal()
    try:
        supplements = get_supplements_by_date(db, user_id, target_date)
        
        # Convert to old format for compatibility
        return [
            {
                'name': supp.supplement_name,
                'time': supp.time.strftime('%H:%M') if supp.time else '00:00',
                'source': 'telegram_bot'
            }
            for supp in supplements
        ]
    finally:
        db.close()


class SupplementService:
    """Service for supplement tracking via PostgreSQL"""
    
    def __init__(self, user_id: int = 895655):
        """
        Initialize service for specific user
        
        Args:
            user_id: Telegram ID of the user
        """
        self.user_id = user_id
        
        # Schedule defined in HEALTH.md
        self.schedule = {
            "☀️ УТРО (до еды)": [
                "Псиллиум"
            ],
            "🌅 УТРО (с завтраком)": [
                "Витамин D3",
                "Омега 3-6-9",
                "Plant Sterols (Утро)"
            ],
            "🌙 ВЕЧЕР (с ужином)": [
                "Plant Sterols (Вечер)",
                "Магний",
                "Цинк"
            ]
        }
        
        # Synonyms map for flexible matching
        self.synonyms = {
            "стирол": "plant sterols",
            "стиролы": "plant sterols",
            "стерол": "plant sterols",
            "стеролы": "plant sterols",
            "растительные стеролы": "plant sterols",
            "plant sterol": "plant sterols",
            "plant sterols": "plant sterols",
            "псилиум": "псиллиум",
            "псиллиум": "псиллиум",
            "psyllium": "псиллиум",
            "омега": "омега 3-6-9",
            "омега-3": "омега 3-6-9",
            "omega": "омега 3-6-9",
            "д3": "витамин d3",
            "d3": "витамин d3",
            "витамин д": "витамин d3",
        }
    
    def get_detailed_schedule(self) -> str:
        """
        Returns a formatted schedule string with checkboxes for taken items
        
        Returns:
            Formatted schedule with ✅/⬜ checkboxes
        """
        taken_today = get_today_supplements(user_id=self.user_id)
        taken_names = {item['name'].lower() for item in taken_today}
        
        def is_taken(req_name: str) -> bool:
            """Check if requirement matches any taken item"""
            req_lower = req_name.lower()
            # Remove time markers for base comparison
            req_base = req_lower.replace(" (утро)", "").replace(" (вечер)", "").strip()
            
            for taken_name in taken_names:
                taken_lower = taken_name.lower()
                taken_base = taken_lower.replace(" (утро)", "").replace(" (вечер)", "").strip()
                
                # Direct match (exact)
                if taken_lower == req_lower or taken_base == req_base:
                    return True
                    
                # Base name match (without time markers)
                if taken_base in req_base or req_base in taken_base:
                    return True
                    
                # Synonym matching
                taken_canonical = self.synonyms.get(taken_base, taken_base)
                req_canonical = self.synonyms.get(req_base, req_base)
                
                if taken_canonical == req_canonical:
                    return True
                    
                if taken_canonical in req_base or req_canonical in taken_base:
                    return True
                    
            return False
        
        lines = ["💊 <b>Чек-лист витаминов на сегодня:</b>\n"]
        
        for time_of_day, items in self.schedule.items():
            lines.append(f"<b>{time_of_day}</b>")
            for item in items:
                status = "✅" if is_taken(item) else "⬜"
                lines.append(f"{status} {item}")
            lines.append("")  # Empty line between blocks
            
        return "\n".join(lines)
    
    def get_brief_status(self) -> str:
        """
        Short status for /day command
        
        Returns:
            Brief status string with taken supplements
        """
        taken_today = get_today_supplements(user_id=self.user_id)
        if not taken_today:
            return "💊 Витамины: ❌ Не принимались"
        
        # Короткие имена
        short_names = {
            "plant sterols (утро)": "Стеролы↑",
            "plant sterols (вечер)": "Стеролы↓", 
            "витамин d3": "D3",
            "омега 3-6-9": "Омега",
            "псиллиум": "Псиллиум",
            "магний": "Mg",
            "цинк": "Zn"
        }
        
        names = []
        seen = set()
        for item in taken_today:
            name = item['name'].lower()
            if name not in seen:
                seen.add(name)
                short = short_names.get(name, item['name'])
                names.append(short)
        
        items_str = ", ".join(names)
        return f"💊 Витамины: ✅ {items_str}"


# Global instance
supplement_service = SupplementService()
