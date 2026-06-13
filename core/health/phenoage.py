"""PhenoAge — биологический возраст по Levine et al. 2018 (Aging).

Чистая функция расчёта, вынесена из async-эндпоинта /phenoage ради
юнит-тестируемости (раньше формула была зашита в обработчик с БД-доступом).

Биомаркеры подаются в КАНОНИЧЕСКИХ единицах (как после core.health.kb_schema):
  albumin_g_l  г/л
  creatinine   мкмоль/л
  glucose      ммоль/л
  hs_CRP       мг/л     (внутри → мг/дл для ln)
  lymphocytes  %
  MCV          фл
  RDW_CV       %
  ALP          Ед/л
  WBC          ×10⁹/л

Коэффициенты — строго по публикации Levine 2018. ВНИМАНИЕ: коэффициент ALP
ПОЛОЖИТЕЛЬНЫЙ (+0.00188) — щелочная фосфатаза маркер риска, повышает
PhenoAge. (Прежняя реализация ошибочно использовала -0.00188.)
"""

from __future__ import annotations

import math

PHENOAGE_MARKERS = (
    "albumin_g_l",
    "creatinine",
    "glucose",
    "hs_CRP",
    "lymphocytes",
    "MCV",
    "RDW_CV",
    "ALP",
    "WBC",
)

_GAMMA = 0.0076927


def phenoage_from_markers(chrono_age: float, markers: dict[str, float]) -> float:
    """Возвращает PhenoAge (лет) по хронологическому возрасту и 9 биомаркерам.

    Args:
        chrono_age: хронологический возраст, лет.
        markers: dict с ключами PHENOAGE_MARKERS в канонических единицах.

    Raises:
        KeyError: если не хватает биомаркера.
        ValueError: если hs_CRP <= 0 (нужен ln) или mort вне (0, 1).
    """
    crp_mg_l = markers["hs_CRP"]
    if crp_mg_l <= 0:
        raise ValueError("hs_CRP must be > 0 for ln()")

    xb = (
        -19.907
        + 0.0804 * chrono_age
        - 0.0336 * markers["albumin_g_l"]
        + 0.0095 * markers["creatinine"]
        + 0.1953 * markers["glucose"]
        + 0.0954 * math.log(crp_mg_l * 0.1)  # мг/л → мг/дл, затем ln
        - 0.0120 * markers["lymphocytes"]
        + 0.0268 * markers["MCV"]
        + 0.3306 * markers["RDW_CV"]
        + 0.00188 * markers["ALP"]  # положительный: маркер риска
        + 0.0554 * markers["WBC"]
    )
    mort = 1 - math.exp(-math.exp(xb) * (math.exp(_GAMMA * 120) - 1) / _GAMMA)
    if not (0 < mort < 1):
        raise ValueError(f"mortality score out of range: {mort}")
    return 141.50225 + math.log(-0.00553 * math.log(1 - mort)) / 0.090165
