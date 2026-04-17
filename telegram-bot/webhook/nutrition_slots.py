"""Pure slot mapping for the nutrition day editor.

A "slot" is one of the 4 fixed meal buckets used by the UI:
breakfast / lunch / snack / dinner. DB stores free-form meal_name + meal_time;
this module resolves each meal into exactly one slot.
"""

import re
from datetime import time
from typing import Optional

SLOTS = ("breakfast", "lunch", "snack", "dinner")

_RU_LABELS = {
    "breakfast": "Завтрак",
    "lunch": "Обед",
    "snack": "Перекус",
    "dinner": "Ужин",
}

_CENTER_TIMES = {
    "breakfast": time(9, 0),
    "lunch": time(13, 0),
    "snack": time(16, 0),
    "dinner": time(19, 0),
}

_NAME_TOKENS = {
    "breakfast": ("завтрак", "breakfast"),
    "lunch": ("обед", "lunch"),
    "snack": ("перекус", "snack", "snacks"),
    "dinner": ("ужин", "dinner", "supper"),
}


def slot_from_time(t: time) -> str:
    h = t.hour
    if 6 <= h < 11:
        return "breakfast"
    if 11 <= h < 15:
        return "lunch"
    if 15 <= h < 18:
        return "snack"
    return "dinner"


def _starts_with_token(text: str, token: str) -> bool:
    """True if text begins with the token as a whole word (ignoring leading non-letter chars like emoji).

    Matches "Завтрак", "🌅 Завтрак дома", "breakfast smoothie" for token "завтрак"/"breakfast".
    Does NOT match "Поздний обед" for token "обед" — prefix qualifiers push it to time-based resolution.
    """
    stripped = re.sub(r"^[^\w]+", "", text, flags=re.UNICODE)
    pattern = r"^" + re.escape(token) + r"\b"
    return re.match(pattern, stripped, flags=re.UNICODE) is not None


def slot_from_meal(name: Optional[str], t: Optional[time]) -> str:
    if name:
        lowered = name.lower()
        for slot, tokens in _NAME_TOKENS.items():
            if any(_starts_with_token(lowered, tok) for tok in tokens):
                return slot
    if t is not None:
        return slot_from_time(t)
    return "breakfast"


def slot_center_time(slot: str) -> time:
    return _CENTER_TIMES[slot]


def slot_label_ru(slot: str) -> str:
    return _RU_LABELS[slot]
