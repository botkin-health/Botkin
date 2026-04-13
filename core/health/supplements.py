"""
Supplement Service - PostgreSQL Version

Управление добавками и витаминами через PostgreSQL
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

# Московское время (UTC+3)
MSK = timezone(timedelta(hours=3))

from database import SessionLocal, get_supplements_by_date, create_supplement_log

logger = logging.getLogger(__name__)

# Default supplement schedule — used for new users and migration
DEFAULT_SUPPLEMENTS = [
    {"name": "Псиллиум", "slot": "morning_before"},
    {"name": "Витамин D3", "slot": "morning_with"},
    {"name": "Омега 3", "slot": "morning_with"},
    {"name": "Plant Sterols", "slot": "morning_with"},
    {"name": "Метилфолат", "slot": "morning_with"},
    {"name": "Plant Sterols", "slot": "evening"},
    {"name": "Магний", "slot": "evening"},
    {"name": "Креатин", "slot": "evening"},
]

# Maps internal slot names → display labels
_SLOT_LABELS = {
    "morning_before": "☀️ УТРО (до еды)",
    "morning_with": "🌅 УТРО (с завтраком)",
    "evening": "🌙 ВЕЧЕР (с ужином)",
}


def save_supplements(items: List[str], user_id: int, date_str: Optional[str] = None) -> bool:
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
        date_str = datetime.now(MSK).strftime("%Y-%m-%d")

    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    current_time = datetime.now(MSK).time()

    db = SessionLocal()
    try:
        # Add new items with timestamp
        for item in items:
            create_supplement_log(
                db, user_id=user_id, date=target_date, time=current_time, supplement_name=item, dosage=None
            )

        return True
    except Exception as e:
        logger.error(f"Error saving supplements: {e}")
        return False
    finally:
        db.close()


def get_today_supplements(user_id: int, date_str: Optional[str] = None) -> List[Dict]:
    """
    Возвращает список принятого за указанную дату

    Args:
        user_id: Telegram ID пользователя
        date_str: Дата YYYY-MM-DD (если None - сегодня)

    Returns:
        List of dicts with 'name' and 'time' keys
    """
    if not date_str:
        date_str = datetime.now(MSK).strftime("%Y-%m-%d")

    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()

    db = SessionLocal()
    try:
        supplements = get_supplements_by_date(db, user_id, target_date)

        # Convert to old format for compatibility
        return [
            {
                "name": supp.supplement_name,
                "time": supp.time.strftime("%H:%M") if supp.time else "00:00",
                "source": "telegram_bot",
            }
            for supp in supplements
        ]
    finally:
        db.close()


class SupplementService:
    """Service for supplement tracking via PostgreSQL"""

    def __init__(self, user_id: int):
        """
        Initialize service for specific user

        Args:
            user_id: Telegram ID of the user
        """
        self.user_id = user_id

        # Load schedule from user_settings DB (or migrate defaults for new users)
        self.schedule = self._load_schedule()

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
            "омега": "омега 3",
            "омега-3": "омега 3",
            "омега 3-6-9": "омега 3",
            "omega": "омега 3",
            "omega-3": "омега 3",
            "д3": "витамин d3",
            "d3": "витамин d3",
            "витамин д": "витамин d3",
            "фолат": "метилфолат",
            "метилофолат": "метилфолат",
            "фолиевая": "метилфолат",
            "folate": "метилфолат",
            "metafolin": "метилфолат",
            "methylfolate": "метилфолат",
            "5-mthf": "метилфолат",
            "креатин": "креатин",
            "creatine": "креатин",
            "creatine monohydrate": "креатин",
            "kreatin": "креатин",
            "кретин": "креатин",
            "моногидрат": "креатин",
        }

    def _load_schedule(self) -> dict:
        """Load supplement schedule from user_settings.

        If no settings exist, saves DEFAULT_SUPPLEMENTS and returns them.
        Returns dict: {"☀️ УТРО (до еды)": [...], "🌅 УТРО (с завтраком)": [...], "🌙 ВЕЧЕР (с ужином)": [...]}
        """
        from database.crud import get_user_settings, upsert_user_settings

        db = SessionLocal()
        try:
            settings = get_user_settings(db, self.user_id)
            if settings is None or not settings.supplements:
                upsert_user_settings(db, self.user_id, supplements=DEFAULT_SUPPLEMENTS)
                raw = DEFAULT_SUPPLEMENTS
            else:
                raw = settings.supplements
        finally:
            db.close()

        result = {label: [] for label in _SLOT_LABELS.values()}
        for item in raw:
            slot = item.get("slot", "morning_with")
            name = item.get("name", "")
            label = _SLOT_LABELS.get(slot)
            if label and name:
                result[label].append(name)
        return result

    def get_detailed_schedule(self, for_date: Optional[str] = None) -> str:
        """
        Returns a formatted schedule string with checkboxes for taken items

        Args:
            for_date: Date string YYYY-MM-DD (if None — today MSK)
        Returns:
            Formatted schedule with ✅/⬜ checkboxes
        """
        taken_today = get_today_supplements(user_id=self.user_id, date_str=for_date)
        taken_names = {item["name"].lower() for item in taken_today}

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

    def get_brief_status(self, for_date: Optional[str] = None) -> str:
        """
        Short status for /day command

        Args:
            for_date: Date string YYYY-MM-DD (if None — today MSK)
        Returns:
            Brief status string with taken supplements
        """
        taken_today = get_today_supplements(user_id=self.user_id, date_str=for_date)
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
            "цинк": "Zn",
            "метилфолат": "Фолат",
        }

        names = []
        seen = set()
        for item in taken_today:
            name = item["name"].lower()
            if name not in seen:
                seen.add(name)
                short = short_names.get(name, item["name"])
                names.append(short)

        items_str = ", ".join(names)
        return f"💊 Витамины: ✅ {items_str}"


# Global instance - now requires user_id
# Create instance per-request in handlers
# supplement_service = SupplementService()  # DEPRECATED: use per-user instance
