# core/health/doc_duplicates.py
"""Поиск уже сохранённого документа, похожего на только что разобранный (#558).

Дедуп `handlers.doc_dedup` ловит только тот же файл (хэш содержимого), а люди
пересылают тот же бланк повторной фотографией или вторым экземпляром распечатки —
байты другие, содержимое то же. Сравниваем по смыслу и только предупреждаем:
решение «сохранить ещё раз или нет» остаётся за пользователем.
"""

from __future__ import annotations

import re
from typing import Any, Optional

# Совпадений по числам меньше — случайность (две разные панели с общим Hb).
_MIN_NUMERIC_VALUES = 3
_MIN_SHARE = 0.8
_REL_TOL = 1e-6

# Сходство текста (резюме + название) двух страниц за одну дату и одного типа.
# Порог выбран по eval #558 (23 реальные страницы): повторные снимки одной страницы
# дали 0.36–0.95, разные страницы за тот же день — не выше 0.23. Выборка маленькая,
# поэтому это только предупреждение, решает пользователь.
_TEXT_SIMILARITY = 0.3
# Меньше токенов — сходство неинформативно («УЗИ почек» vs «УЗИ матки» = 1/3),
# тогда требуем точного совпадения названия.
_MIN_TEXT_TOKENS = 5
_STEM = 5
_STOPWORDS = frozenset(
    "и в на с по не из для от до мм мл гэ зр без норма обнаружено обнаружены обнаружен выявлено выявлены".split()
)
_WORD_RE = re.compile(r"[a-zа-яё0-9]+")


def _numeric(values: Any) -> dict[str, float]:
    if not isinstance(values, dict):
        return {}
    return {k: float(v) for k, v in values.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


def _same_number(a: float, b: float) -> bool:
    return abs(a - b) <= max(abs(a), abs(b)) * _REL_TOL


def _dates_compatible(a: Any, b: Any) -> bool:
    """Повторная печать может потерять дату — отсутствие даты с одной стороны не мешает."""
    return not a or not b or a == b


def _norm(text: Any) -> str:
    return " ".join(str(text or "").split()).casefold()


def _values_match(new: dict[str, float], old: dict[str, float]) -> bool:
    if len(new) < _MIN_NUMERIC_VALUES:
        return False
    same = sum(1 for k, v in new.items() if k in old and _same_number(v, old[k]))
    return same / len(new) >= _MIN_SHARE


def _values_conflict(new: dict[str, float], old: dict[str, float]) -> bool:
    """Сопоставимые числа есть и расходятся — это разные анализы, как ни похож текст."""
    common = [k for k in new if k in old]
    if len(common) < _MIN_NUMERIC_VALUES:
        return False
    same = sum(1 for k in common if _same_number(new[k], old[k]))
    return same / len(common) < _MIN_SHARE


def _distinct_lab_pages(new: dict, old: dict, new_values: dict, old_values: dict) -> bool:
    """Две лабораторные страницы с числами без общих аналитов — разные страницы одной
    панели, как ни похож текст (ревью #560). У УЗИ ключи модель придумывает сама —
    там несовпадение ключей ничего не значит, поэтому только lab_panel."""
    if not (new.get("doc_kind") == old.get("doc_kind") == "lab_panel"):
        return False
    if min(len(new_values), len(old_values)) < _MIN_NUMERIC_VALUES:
        return False
    return len(set(new_values) & set(old_values)) < _MIN_NUMERIC_VALUES


def _is_cancelled_archive(entry: dict) -> bool:
    """Отменённый/неразобранный архив — не «уже сохранён» (ревью #560): иначе чёткое
    фото, присланное вместо отменённого размытого, уговорили бы тоже отменить."""
    return bool(entry.get("auto_archived")) and not entry.get("restored")


def _tokens(doc: dict) -> set[str]:
    text = f"{doc.get('summary') or ''} {doc.get('doc_type') or ''}".casefold()
    return {w[:_STEM] for w in _WORD_RE.findall(text) if len(w) > 2 and w not in _STOPWORDS}


def _text_match(new: dict, old: dict) -> bool:
    """Та же дата и тот же тип, и похожее описание: резюме + название (#558).

    Ловит повторные снимки мазков/УЗИ, у которых нет общих числовых ключей: модель
    формулирует название и называет размеры по-разному, а резюме почти совпадают.
    """
    if not new.get("date") or new.get("date") != old.get("date") or new.get("doc_kind") != old.get("doc_kind"):
        return False
    new_tokens, old_tokens = _tokens(new), _tokens(old)
    if min(len(new_tokens), len(old_tokens)) < _MIN_TEXT_TOKENS:
        new_type, old_type = _norm(new.get("doc_type")), _norm(old.get("doc_type"))
        return bool(new_type) and new_type == old_type
    return len(new_tokens & old_tokens) / len(new_tokens | old_tokens) >= _TEXT_SIMILARITY


def find_similar_document(documents: list[Any], extracted: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Первый сохранённый документ, совпадающий с `extracted` по содержимому, или None.

    documents — записи `documents[]` из KB пользователя; extracted — результат
    `doc_extractor.extract_medical_data` для нового файла.
    """
    extracted = extracted or {}
    new_values = _numeric(extracted.get("values"))
    for entry in documents or []:
        if not isinstance(entry, dict) or _is_cancelled_archive(entry):
            continue
        old = entry.get("extracted")
        if not isinstance(old, dict):
            continue
        old_values = _numeric(old.get("values"))
        if new_values and _dates_compatible(extracted.get("date"), old.get("date")):
            if _values_match(new_values, old_values):
                return entry
        if _values_conflict(new_values, old_values) or _distinct_lab_pages(extracted, old, new_values, old_values):
            continue
        if _text_match(extracted, old):
            return entry
    return None
