"""Подсчёт выпитой воды из позиций nutrition_log (issue #526).

Вода уже пишется как еда (0 ккал, см. PR #455/#457/#458). Новой таблицы и
новых команд нет — воду считаем ИЗ существующих items на чтении, так же как
клетчатку считает `core/food/fiber_table.py`.

Правила подсчёта (согласовано с Александром 23.09.2026):
  - считаем ТОЛЬКО воду: «вода», «вода питьевая», «минеральная вода»,
    «газированная вода», «стакан воды», water;
  - НЕ считаем: чай, кофе, суп, соки, молоко (другой вопрос, не эта задача) —
    они и так не матчатся;
  - НЕ считаем «водку» (омоним по префиксу «вод») и «кокосовую воду»
    (калорийный напиток, а не вода) — явные исключения ниже;
  - объём = граммы (у воды это то же самое, что миллилитры);
  - если объёма нет и это не «стакан» — позицию не считаем и не гадаем.
"""

from typing import Optional

from .fiber_table import _item_name, _item_weight

# «Стакан» без явного объёма — тот же дефолт, что и в core/food/nutrition.py
# (default_weights['вода'] = 250 при source == 'description_simple').
_STAKAN_DEFAULT_ML = 250.0

# Слова, при наличии которых как ЦЕЛОГО ТОКЕНА позиция считается водой.
_WATER_WORDS = {"вода", "воды", "водой", "воду", "water"}

# Явные исключения: содержат "вода"/"воды" как токен, но не должны считаться
# (калорийный напиток, не чистая вода).
_WATER_EXCLUDE_SUBSTRINGS = ("кокосов",)


def _tokens(name: str) -> list:
    """Разбивает название на буквенные токены (кириллица + латиница)."""
    tokens = []
    current = []
    for ch in name:
        if ch.isalpha():
            current.append(ch)
        else:
            if current:
                tokens.append("".join(current))
                current = []
    if current:
        tokens.append("".join(current))
    return tokens


def is_water_item(name: Optional[str]) -> bool:
    """True, если название позиции — вода (а не водка/водоросли/чай и т.п.)."""
    if not name:
        return False
    n = name.lower()
    for excl in _WATER_EXCLUDE_SUBSTRINGS:
        if excl in n:
            return False
    return any(tok in _WATER_WORDS for tok in _tokens(n))


def _is_stakan(name: str) -> bool:
    return "стакан" in name.lower()


def water_ml_for_item(item: dict) -> float:
    """Миллилитры воды в одной позиции item, 0.0 если это не вода или объём
    неизвестен (и это не «стакан», для которого есть согласованный дефолт)."""
    if not isinstance(item, dict):
        # Легаси-формат items как {"eggs": {...}} даёт строковые ключи при
        # итерации — не позиция, пропускаем без падения (см. test_nutrition_service).
        return 0.0
    name = _item_name(item)
    if not is_water_item(name):
        return 0.0
    weight = _item_weight(item)
    if weight and weight > 0:
        return float(weight)
    if _is_stakan(name):
        return _STAKAN_DEFAULT_ML
    return 0.0


def sum_water_ml(items: list) -> float:
    """Сумма воды (мл) по списку items одного приёма пищи или дня."""
    total = 0.0
    for it in items or []:
        total += water_ml_for_item(it)
    return round(total, 1)
