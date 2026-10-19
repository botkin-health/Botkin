"""Итог КБЖУ, названный пользователем в тексте о еде (#629).

«…сэндвич Tunacado: тунцовый мусс, авокадо… По данным сети 506 ккал, ~Б22 Ж27 У45» — цифра
из меню/с упаковки точнее оценки по компонентам. Здесь только разбор текста; решение,
якорить ли позиции, и само масштабирование — в core.food.nutrition (механизм #427).
"""

import re
from typing import Dict, List, Optional

_NUM = r"(\d{1,5}(?:[.,]\d+)?)"
_KCAL_RE = re.compile(_NUM + r"\s*(?:ккал|kcal|кал(?:ори\w*)?)(?![а-яёa-z])", re.IGNORECASE)
# «120 ккал на 100 г», «350 ккал/100г», «в 100 г 120 ккал» — плотность, а не итог порции
_PER_100_AFTER_RE = re.compile(r"^\s*(?:на|в|/)\s*100\s*(?:г|гр|грам\w*|мл)?", re.IGNORECASE)
_PER_100_BEFORE_RE = re.compile(r"(?:на|в)\s*100\s*(?:г|гр|грам\w*|мл)\.?\s*[:\-—]?\s*$", re.IGNORECASE)

_MACRO_RES = {
    "protein": re.compile(r"(?<![а-яёa-z])(?:б|белк\w*|белок|protein)\s*[:=]?\s*~?" + _NUM, re.IGNORECASE),
    "fats": re.compile(r"(?<![а-яёa-z])(?:ж|жир\w*|fat\w*)\s*[:=]?\s*~?" + _NUM, re.IGNORECASE),
    "carbs": re.compile(r"(?<![а-яёa-z])(?:у|углевод\w*|carb\w*)\s*[:=]?\s*~?" + _NUM, re.IGNORECASE),
}

_TOTAL_MARKER_RE = re.compile(
    r"итого|всего|в сумме|суммарно|общ(?:ая|ий|ее)|по данным|по меню|в меню|на упаковке|на этикетке"
    r"|на карточке|по карточке|по сайту|на сайте|сеть|сети|ресторан\w*|в приложении",
    re.IGNORECASE,
)

_MIN_KCAL, _MAX_KCAL = 30.0, 5000.0
_ITEM_MATCH_TOLERANCE = 0.15  # позиция в пределах 15% от названного итога → это ккал позиции
_MAX_RATIO_WITHOUT_MARKER = 2.0  # без маркера итога якорим, только если расхождение не больше ×2


def _to_float(s: str) -> float:
    return float(s.replace(",", "."))


def extract_stated_totals(text: str) -> Optional[Dict]:
    """Ровно одно значение ккал в тексте (не «на 100 г») → {"calories", [protein/fats/carbs], has_total_marker}."""
    if not text:
        return None
    values = set()
    for m in _KCAL_RE.finditer(text):
        if _PER_100_AFTER_RE.match(text[m.end() :]) or _PER_100_BEFORE_RE.search(text[: m.start()]):
            return None
        values.add(_to_float(m.group(1)))
    if len(values) != 1:
        return None
    kcal = values.pop()
    if not (_MIN_KCAL <= kcal <= _MAX_KCAL):
        return None
    result: Dict = {"calories": kcal}
    for key, pattern in _MACRO_RES.items():
        m = pattern.search(text)
        if m:
            result[key] = _to_float(m.group(1))
    result["has_total_marker"] = bool(_TOTAL_MARKER_RE.search(text))
    return result


def should_anchor(stated: Dict, items: List[Dict], computed_calories: float) -> bool:
    """Названный итог относится ко всему блюду, а не к одной из позиций."""
    kcal = float(stated["calories"])
    if computed_calories <= 0 or len(items) < 2:
        return False
    for it in items:
        item_kcal = float(it.get("calories") or 0)
        if item_kcal > 0 and abs(item_kcal - kcal) / kcal <= _ITEM_MATCH_TOLERANCE:
            return False
    if stated.get("has_total_marker"):
        return True
    ratio = kcal / computed_calories
    return 1 / _MAX_RATIO_WITHOUT_MARKER <= ratio <= _MAX_RATIO_WITHOUT_MARKER
