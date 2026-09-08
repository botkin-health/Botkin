"""Текстовые модификаторы состава блюда: «без X», «половину», «N г» (#427).

Чистый модуль без побочных эффектов: parse_modifiers разбирает свободный текст
пользователя (обычно caption к фото или ответ в чате) в структурированный
Modifiers, apply_modifiers применяет его к уже посчитанным items/totals, никогда
не мутируя входные данные.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .nutrition import stems_overlap

# Слова-триггеры исключения продукта из состава.
_EXCLUDE_VERBS = ("без", "минус", "убери", "убрать", "исключи")

# Максимум имён в списке исключений («без кускуса, соуса и хлеба»).
_EXCLUDE_MAX_NAMES = 3
# Максимум слов в одном имени продукта, когда имён в списке больше одного.
_EXCLUDE_MULTI_NAME_MAX_WORDS = 2
# Одиночное имя (без списка через «и»/«,») должно быть ровно одним словом —
# иначе «без сахара кола» (название продукта) ошибочно распознаётся как исключение.
_EXCLUDE_SINGLE_NAME_MAX_WORDS = 1

_FRACTION_WORDS = {
    "половину": 0.5,
    "половина": 0.5,
    "половины": 0.5,
    "пол": 0.5,
    "треть": 1 / 3,
    "трети": 1 / 3,
    "четверть": 0.25,
    "четверти": 0.25,
}
_FRACTION_MAX_WORDS = 4

_WEIGHT_MAX_WORDS = 5
_WEIGHT_UNIT_RE = re.compile(r"^г|гр$|^грамм\w*$")
_WEIGHT_JOINED_RE = re.compile(r"^(\d{2,4})(?:г|гр|грамм\w*)$")
_WEIGHT_NUMBER_RE = re.compile(r"^\d{2,4}$")

_ROUND_NDIGITS = 1
_MACRO_KEYS = ("calories", "protein", "fats", "carbs", "fiber")


@dataclass(frozen=True)
class Modifiers:
    exclude: Tuple[str, ...] = ()
    fraction: Optional[float] = None
    weight_g: Optional[float] = None

    @property
    def is_modifier(self) -> bool:
        return bool(self.exclude) or self.fraction is not None or self.weight_g is not None


@dataclass(frozen=True)
class Applied:
    items: List[Dict]
    totals: Dict
    removed: List[Dict] = field(default_factory=list)
    unmatched: List[str] = field(default_factory=list)
    fraction: Optional[float] = None


def _split_name_list(raw: str) -> List[str]:
    """«кускуса, соуса и хлеба» -> ["кускуса", "соуса", "хлеба"]."""
    parts = re.split(r"\s*,\s*|\s+и\s+", raw.strip())
    cleaned = []
    for part in parts:
        words = [w.strip(".,!?;:") for w in part.split()]
        # «без соли и без перца» — повторный глагол внутри списка не часть имени
        if words and words[0].lower() in _EXCLUDE_VERBS:
            words = words[1:]
        name = " ".join(w for w in words if w)
        if name:
            cleaned.append(name)
    return cleaned


def _parse_exclusion(text: str) -> Tuple[str, ...]:
    words = text.strip().split()
    if not words:
        return ()
    verb = words[0].lower()
    if verb not in _EXCLUDE_VERBS:
        return ()
    rest = " ".join(words[1:]).strip()
    if not rest:
        return ()

    names = _split_name_list(rest)
    if not names or len(names) > _EXCLUDE_MAX_NAMES:
        return ()

    max_words = _EXCLUDE_SINGLE_NAME_MAX_WORDS if len(names) == 1 else _EXCLUDE_MULTI_NAME_MAX_WORDS
    for name in names:
        name_words = name.split()
        if not name_words or len(name_words) > max_words:
            return ()
        if name_words[0][0].isdigit():
            return ()

    return tuple(names)


def _parse_fraction(text: str) -> Optional[float]:
    words = text.strip().lower().split()
    if not words or len(words) > _FRACTION_MAX_WORDS:
        return None
    for word in words:
        cleaned = word.strip(".,!?")
        if cleaned in _FRACTION_WORDS:
            return _FRACTION_WORDS[cleaned]
    return None


# Слова, допустимые рядом с весом в правке превью: «это было 200 г», «вес 200 г», «там 200 г».
# Любое другое слово с буквами («съела 300 г супа») — это описание еды, не правка веса.
_WEIGHT_FILLER_WORDS = frozenset(
    {"это", "было", "была", "были", "там", "вес", "весило", "весит", "порция", "всего", "примерно", "около", "~"}
)


def _parse_weight(text: str) -> Optional[float]:
    words = [w.strip(".,!?") for w in text.strip().lower().split()]
    if not words or len(words) > _WEIGHT_MAX_WORDS:
        return None
    for word in words:
        if word in _WEIGHT_FILLER_WORDS or word in ("г", "гр") or re.fullmatch(r"грамм\w*", word):
            continue
        if _WEIGHT_NUMBER_RE.match(word) or _WEIGHT_JOINED_RE.match(word):
            continue
        return None  # постороннее слово — не правка веса

    for i, word in enumerate(words):
        # Слитно: "200г", "200гр", "200грамм".
        joined = _WEIGHT_JOINED_RE.match(word)
        if joined:
            return float(joined.group(1))
        # Раздельно: число, затем следом единица измерения.
        if _WEIGHT_NUMBER_RE.match(word) and i + 1 < len(words):
            unit = words[i + 1]
            if unit in ("г", "гр") or re.fullmatch(r"грамм\w*", unit):
                return float(word)
    return None


def parse_modifiers(text: str) -> Modifiers:
    if not text or not text.strip():
        return Modifiers()

    exclude = _parse_exclusion(text)
    if exclude:
        return Modifiers(exclude=exclude)

    fraction = _parse_fraction(text)
    if fraction is not None:
        return Modifiers(fraction=fraction)

    weight_g = _parse_weight(text)
    if weight_g is not None:
        return Modifiers(weight_g=weight_g)

    return Modifiers()


def _recompute_totals(items: List[Dict]) -> Dict:
    return {key: round(sum(float(it.get(key) or 0) for it in items), _ROUND_NDIGITS) for key in _MACRO_KEYS}


def _scale_item(item: Dict, factor: float, *, round_result: bool = True) -> Dict:
    scaled = dict(item)
    for key in _MACRO_KEYS:
        val = item.get(key)
        if val is not None:
            new_val = float(val) * factor
            scaled[key] = round(new_val, _ROUND_NDIGITS) if round_result else new_val
    weight = item.get("weight_g")
    if weight is not None:
        new_weight = float(weight) * factor
        scaled["weight_g"] = round(new_weight, _ROUND_NDIGITS) if round_result else new_weight
    return scaled


def _apply_exclusion(items: List[Dict], totals: Dict, names: Tuple[str, ...]) -> Applied:
    remaining = [dict(it) for it in items]
    removed: List[Dict] = []
    unmatched: List[str] = []

    for name in names:
        match_idx = None
        for idx, it in enumerate(remaining):
            product = str(it.get("product") or "").lower()
            if stems_overlap(product, name.lower()):
                match_idx = idx
                break
        if match_idx is None:
            unmatched.append(name)
            continue
        removed.append(remaining.pop(match_idx))

    totals_out = _recompute_totals(remaining) if removed else dict(totals)
    return Applied(items=remaining, totals=totals_out, removed=removed, unmatched=unmatched)


def _apply_fraction(items: List[Dict], fraction: float) -> Applied:
    scaled_items = [_scale_item(it, fraction) for it in items]
    totals_out = _recompute_totals(scaled_items)
    return Applied(items=scaled_items, totals=totals_out, fraction=fraction)


def _apply_weight(items: List[Dict], totals: Dict, weight_g: float) -> Applied:
    items_with_weight = [it for it in items if (it.get("weight_g") or 0) > 0]
    if len(items) != 1 or len(items_with_weight) != 1:
        return Applied(
            items=[dict(it) for it in items],
            totals=dict(totals),
            unmatched=[f"{int(weight_g)} г"],
        )

    old_weight = float(items[0]["weight_g"])
    factor = weight_g / old_weight if old_weight else 1.0
    scaled_item = _scale_item(items[0], factor, round_result=False)
    scaled_item["weight_g"] = weight_g  # избегаем накопления погрешности округления
    scaled_items = [scaled_item]
    totals_out = _recompute_totals(scaled_items)
    return Applied(items=scaled_items, totals=totals_out)


def apply_modifiers(items: List[Dict], totals: Dict, mods: Modifiers) -> Applied:
    if not mods.is_modifier:
        return Applied(items=[dict(it) for it in items], totals=dict(totals))
    if mods.exclude:
        return _apply_exclusion(items, totals, mods.exclude)
    if mods.fraction is not None:
        return _apply_fraction(items, mods.fraction)
    return _apply_weight(items, totals, mods.weight_g)


def describe_applied(res: Applied) -> str:
    parts: List[str] = []
    for it in res.removed:
        cal = it.get("calories")
        cal_str = f"{cal:g}" if cal is not None else "?"
        parts.append(f"− {it.get('product')} ≈ {cal_str} ккал")
    if res.fraction is not None:
        parts.append(f"× {res.fraction:g}")
    if res.unmatched:
        parts.append(f"не нашёл в составе: {', '.join(res.unmatched)}")
    return " · ".join(parts)
