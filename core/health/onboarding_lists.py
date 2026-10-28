"""Единый источник чтения/сплита списков онбординга (аллергии, диагнозы).

Переиспользуется отчётом для врача, merge-CRUD, превью /doc и блоком агента,
чтобы «куда пишем» = «откуда читаем» (один порядок ключей и один сплиттер).
"""

from __future__ import annotations

import re
from typing import Any, Iterable, NamedTuple, Optional

ALLERGY_KEYS: tuple[str, ...] = ("allergies", "food_allergies", "allergy")
CONDITION_KEYS: tuple[str, ...] = ("chronic_conditions", "chronic_diagnoses", "diagnoses", "conditions")

_ITEM_SEP_RE = re.compile(r"[\n;]+|\.\s+|\.$")


def split_freetext(val: str) -> list[str]:
    """Разбить свободный текст (диагнозы/аллергии) на пункты.

    Делит по СИЛЬНЫМ разделителям: конец предложения, перенос строки, «;».
    Запятая разделителем НЕ считается (часть описания одного пункта, #7/#309).
    Точка внутри кода МКБ (J45.0) сохраняется. Если сильных разделителей нет,
    а запятые есть — fallback на split по запятой.
    """
    s = str(val).strip()
    if not s:
        return []
    parts = [p.strip(" .;") for p in _ITEM_SEP_RE.split(s)]
    parts = [p for p in parts if p]
    if len(parts) <= 1 and "," in s:
        parts = [p.strip() for p in s.split(",") if p.strip()]
    return parts


def onboarding_list(onboarding: Optional[dict], keys: tuple[str, ...]) -> list[str]:
    """Достать список значений из онбординга по первому непустому ключу.

    Значение — список (берём как есть) или свободная строка (через split_freetext).
    """
    if not onboarding:
        return []
    for key in keys:
        val = onboarding.get(key)
        if not val:
            continue
        if isinstance(val, list):
            return [str(v).strip() for v in val if str(v).strip()]
        return split_freetext(str(val))
    return []


# --- Дедуп пунктов профиля (#645) -------------------------------------------
#
# LLM-разбор /doc при каждой загрузке формулирует диагноз по-новому, а точное
# сравнение строк такие варианты не ловит: «Артериальная гипертензия» /
# «Гипертоническая болезнь II ст. (I10)» / «… II степени (I10)» ложились в
# профиль отдельными пунктами. Здесь — детерминированный ключ сравнения:
# основы слов без регистра и окончаний, код МКБ отдельно, «уточнители»
# (степени, уровни L1-L2, номера) и статус («в анамнезе», «подозрение») —
# отдельно, чтобы клинически значимые детали не схлопывались.

_ICD_RE = re.compile(r"\b([A-TV-Z]\d{2}(?:\.\d{1,2})?)\b")
_QUALIFIER_RE = re.compile(r"^(?:\d+|[a-z]\d+|i{1,3}|iv|vi{0,3})$")
_NOISE_STEMS = frozenset(
    {"ст", "степен", "степ", "класс", "функциональн", "фк", "с", "и", "в", "на", "к", "по", "без", "из", "от", "до"}
)
# Префиксы основ, задающие статус пункта — пункты с разным статусом не дубли.
_STATUS_FLAGS = {
    "history": ("анамнез", "ремисс", "перенесен", "после"),
    "suspected": ("подозрен", "исключ", "вероятн"),
}
_SUFFIXES = sorted(
    "ого его ому ему ими ыми ой ей ый ий ая яя ое ее ые ие ых их ую юю ов ев ам ям ах ях ом ем ы и а я о е у ю ь".split(),
    key=len,
    reverse=True,
)
# Синонимы на уровне основ: только частые случаи, без медицинской «онтологии».
_STEM_SYNONYMS = {
    "двухстворчат": "двустворчат",
    "межпозвонков": "межпозвоночн",
    "кот": "кошк",
    "кошек": "кошк",
    "пылев": "пыл",
}
# Сколько «лишних» основ допускаем у пунктов с совместимым кодом МКБ, чтобы
# считать их одним состоянием («Артериальная гипертензия (I10)» ~
# «Гипертоническая болезнь (I10)»), но не склеить «Двустворчатый клапан (Q23.9)»
# с «Комбинированным пороком: стеноз и недостаточность (Q23.9)».
_CODE_SYNONYM_MAX_EXTRA = 2
# Насколько подробнее может быть пункт, чтобы поглотить более общий
# («Остеопороз» → «Остеопороз, ассоциированный с беременностью»), но не
# растворить его в длинной сводной фразе заключения.
_SUBSET_MAX_EXTRA = 3


class ItemKey(NamedTuple):
    stems: frozenset[str]
    code: Optional[str]
    qualifiers: frozenset[str]
    status: frozenset[str]


def _stem(word: str) -> str:
    for suf in _SUFFIXES:
        if word.endswith(suf) and len(word) - len(suf) >= 3:
            word = word[: -len(suf)]
            break
    return _STEM_SYNONYMS.get(word, word)


def item_key(item: str) -> ItemKey:
    """Ключ сравнения пункта профиля (диагноза или аллергии)."""
    raw = str(item)
    codes = _ICD_RE.findall(raw)
    text = _ICD_RE.sub(" ", raw).casefold().replace("ё", "е")
    stems: set[str] = set()
    qualifiers: set[str] = set()
    status: set[str] = set()
    for word in re.split(r"[^\w]+", text):
        if not word:
            continue
        if _QUALIFIER_RE.match(word):
            qualifiers.add(word)
            continue
        stem = _stem(word)
        if stem in _NOISE_STEMS or len(stem) < 2:
            continue
        flag = next((f for f, prefixes in _STATUS_FLAGS.items() if stem.startswith(prefixes)), None)
        if flag:
            status.add(flag)
            continue
        stems.add(stem)
    return ItemKey(frozenset(stems), codes[0] if codes else None, frozenset(qualifiers), frozenset(status))


def _codes_compatible(a: str, b: str) -> bool:
    """I50 ~ I50.9, H52.2 ~ H52.20; E88.9 и E88.81 — разные."""
    return a.startswith(b) or b.startswith(a)


def _covers(a: ItemKey, b: ItemKey, *, by_code: bool = True) -> bool:
    """Пункт `a` несёт не меньше информации, чем `b` (то есть `b` — дубль `a`).

    by_code — разрешить склейку по совместимому коду МКБ при разных формулировках.
    Её используем только чтобы НЕ добавлять новый пункт, но не чтобы вытеснять
    уже записанный: иначе «Комбинированный порок… (Q23.9)» съел бы
    «Двустворчатый клапан с кальцинозом (Q23.9)».
    """
    if a.status != b.status or not b.qualifiers <= a.qualifiers:
        return False
    if b.stems <= a.stems:
        if len(a.stems - b.stems) > _SUBSET_MAX_EXTRA:
            # «Нарушение статики позвоночника» не растворяем в длинной сводке МРТ.
            return False
        if b.code is None:
            return True
        if a.code is None:
            # У b есть код, которого нет у a, — a не покрывает b (код не теряем).
            return False
        # Совместимые коды — дубль. Несовместимые при одном и том же тексте —
        # тоже: противоречивый второй код в профиль не тащим, оставляем первый.
        return _codes_compatible(a.code, b.code) or b.stems == a.stems
    return bool(
        by_code
        and a.code
        and b.code
        and _codes_compatible(a.code, b.code)
        and len(b.stems - a.stems) <= _CODE_SYNONYM_MAX_EXTRA
    )


def merge_items(existing: list[str], new_items: Iterable[Any]) -> tuple[list[str], int, int]:
    """Слить новые пункты в существующий список без дублей.

    Новый пункт не добавляется, если в списке уже есть то же состояние (с той же
    или большей детализацией). Если новый пункт — то же, но подробнее (добавился
    код МКБ, степень, локализация), он заменяет старый на месте (и все прочие
    пункты, которые он покрывает).
    Возвращает (список, сколько добавлено, сколько уточнено).
    """
    merged = [str(v).strip() for v in existing if str(v).strip()]
    keys = [item_key(s) for s in merged]
    added = refined = 0
    for raw in new_items:
        s = " ".join(str(raw).split())
        if not s:
            continue
        key = item_key(s)
        if any(_covers(k, key) for k in keys):
            continue
        covered = [i for i, k in enumerate(keys) if _covers(key, k, by_code=False)]
        if covered:
            # Встаёт на место первого покрытого, остальные покрытые — те же дубли.
            merged[covered[0]], keys[covered[0]] = s, key
            for i in reversed(covered[1:]):
                del merged[i], keys[i]
            refined += 1
            continue
        merged.append(s)
        keys.append(key)
        added += 1
    return merged, added, refined


def is_known(item: str, existing: list[str]) -> bool:
    """Уже есть в профиле то же состояние (для пометок «уже в профиле» в превью)."""
    key = item_key(item)
    return any(_covers(item_key(e), key) for e in existing)
