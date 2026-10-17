"""Референсные диапазоны биомаркеров и расстановка флагов ↑/↓ с учётом пола (#591).

Единый источник границ нормы для PDF «Отчёт для врача», PNG-динамики и
(в будущем) вкладки «Состояние» миниаппа. Ключи — КАНОНИЧЕСКИЕ имена
`kb_schema.CANONICAL` (инвариант проверяется тестом).

Структура: `REF_RANGES[canon][sex] = (low, high)`.

⚠️ Сейчас заданы ТОЛЬКО мужские границы (взрослые мужчины, общая популяция) —
перенесены без изменений из прежнего `MARKER_CONFIG`.
TODO(#591): женские границы (Hb, HCT, RBC, ферритин, железо, креатинин, ALT/AST,
ЛПВП, тестостерон и др.) НЕ придумывать: добавлять только из источника от
лаборатории или врача проекта, по одной записи вида
`"Hb": {"male": (130, 170), "female": (120, 150)}`. Пока записи для пола нет —
флаг не ставится (значение показывается без оценки).
"""

from __future__ import annotations

from typing import Optional

REF_RANGES: dict[str, dict[str, tuple[float, float]]] = {
    "glucose": {"male": (3.9, 6.0)},
    "HbA1c": {"male": (4.0, 5.7)},
    "Hb": {"male": (130, 170)},
    "RBC": {"male": (4.0, 5.5)},
    "WBC": {"male": (4.0, 9.0)},
    "HCT": {"male": (39, 49)},
    "cholesterol_total": {"male": (3.0, 5.2)},
    "LDL": {"male": (0, 3.0)},
    "HDL": {"male": (1.0, 2.5)},
    "triglycerides": {"male": (0, 1.7)},
    "ApoB": {"male": (0, 0.9)},
    "ALT": {"male": (0, 41)},
    "AST": {"male": (0, 40)},
    "creatinine": {"male": (64, 104)},
    "bilirubin_total": {"male": (5, 21)},
    "CRP": {"male": (0, 5)},
    "ferritin": {"male": (30, 300)},
    "PSA_total": {"male": (0, 4)},
    "TSH": {"male": (0.4, 4.0)},
    "vitamin_D": {"male": (30, 100)},
    "testosterone": {"male": (8.6, 29)},
    "iron": {"male": (10, 30)},
}

# Пол, для которого нормы заданы хотя бы для части маркеров (для пометки в отчёте).
KNOWN_SEXES = frozenset(sex for ranges in REF_RANGES.values() for sex in ranges)


def normalize_sex(sex: Optional[str]) -> Optional[str]:
    """'male'/'m' → 'male', 'female'/'f' → 'female', всё остальное → None."""
    s = (sex or "").strip().lower()
    if s in ("male", "m"):
        return "male"
    if s in ("female", "f"):
        return "female"
    return None


def ref_range(canon_key: str, sex: Optional[str]) -> Optional[tuple[float, float]]:
    """Границы нормы (low, high) для маркера и пола; None — если для пары нормы нет."""
    sex_n = normalize_sex(sex)
    if sex_n is None:
        return None
    return REF_RANGES.get(canon_key, {}).get(sex_n)


def flag_for(canon_key: str, value: object, sex: Optional[str]) -> str:
    """'↑' / '↓' / '' (в норме или нет референса для этого пола / нечисловое значение)."""
    bounds = ref_range(canon_key, sex)
    if bounds is None:
        return ""
    low, high = bounds
    try:
        if value > high:  # type: ignore[operator]
            return "↑"
        if value < low:  # type: ignore[operator]
            return "↓"
    except TypeError:
        return ""
    return ""
