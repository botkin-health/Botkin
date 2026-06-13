"""Correctness-тест формулы PhenoAge (Levine et al. 2018, Aging).

ВАЖНО: это НЕ характеризующий тест. Он проверяет *правильный* ответ по
опубликованной формуле, а не текущее поведение кода. Если в расчёте есть
ошибка коэффициента (например, знак ALP), тест её ловит — поэтому оракул ниже
реализован независимо, строго по статье Levine 2018.

TDD: тест нацелен на чистую функцию `core.health.phenoage.phenoage_from_markers`,
которой ещё нет (формула сейчас зашита в async-эндпоинте /phenoage и неюнит-
тестируема: тянет БД, а raw-SQL `SELECT ... values ...` падает на SQLite —
`values` зарезервировано). Фикс выносит формулу в чистую функцию и правит знак
ALP. До фикса: ImportError → RED. После: GREEN.

Опубликованные коэффициенты линейной комбинации (xb), единицы:
  intercept   -19.907
  age          0.0804   (лет)
  albumin     -0.0336   (г/л)
  creatinine   0.0095   (мкмоль/л)
  glucose      0.1953   (ммоль/л)
  ln(CRP)      0.0954   (CRP в мг/дл)
  lymphocyte% -0.0120   (%)
  MCV          0.0268   (фл)
  RDW          0.3306   (%)
  ALP          0.00188  (Ед/л)  ← ПОЛОЖИТЕЛЬНЫЙ (маркер риска)
  WBC          0.0554   (×10⁹/л)
Затем:
  g = 0.0076927
  mort = 1 - exp(-exp(xb) * (exp(g*120) - 1) / g)
  PhenoAge = 141.50225 + ln(-0.00553 * ln(1 - mort)) / 0.090165
"""

import math

import pytest


# ── Независимый оракул (опубликованная формула Levine 2018) ──────────────────
def _levine_phenoage(chrono_age: float, m: dict) -> float:
    crp_mgdl = m["hs_CRP"] * 0.1  # мг/л → мг/дл
    xb = (
        -19.907
        + 0.0804 * chrono_age
        - 0.0336 * m["albumin_g_l"]
        + 0.0095 * m["creatinine"]
        + 0.1953 * m["glucose"]
        + 0.0954 * math.log(crp_mgdl)
        - 0.0120 * m["lymphocytes"]
        + 0.0268 * m["MCV"]
        + 0.3306 * m["RDW_CV"]
        + 0.00188 * m["ALP"]  # положительный коэффициент!
        + 0.0554 * m["WBC"]
    )
    g = 0.0076927
    mort = 1 - math.exp(-math.exp(xb) * (math.exp(g * 120) - 1) / g)
    return 141.50225 + math.log(-0.00553 * math.log(1 - mort)) / 0.090165


_MARKERS = {
    "albumin_g_l": 45.0,
    "creatinine": 80.0,
    "glucose": 5.0,
    "hs_CRP": 1.0,
    "lymphocytes": 30.0,
    "MCV": 90.0,
    "RDW_CV": 13.0,
    "ALP": 95.0,
    "WBC": 6.0,
}


def test_phenoage_matches_levine_reference():
    """phenoage_from_markers совпадает с независимым оракулом Levine 2018.

    Ловит ошибку знака ALP: эндпоинт использует -0.00188, формула требует
    +0.00188. До фикса (нет чистой функции) — ImportError. После — равенство.
    """
    from core.health.phenoage import phenoage_from_markers

    chrono = 48
    got = phenoage_from_markers(chrono, _MARKERS)
    expected = _levine_phenoage(chrono, _MARKERS)
    assert got == pytest.approx(expected, abs=0.05), (
        f"phenoage={got} != Levine-оракул={expected:.2f}; проверь коэффициенты (вероятно знак ALP)"
    )


def test_phenoage_higher_alp_ages_you():
    """Рост ALP при прочих равных УВЕЛИЧИВАЕТ bio_age (маркер риска).

    Семантический тест направления: падает при инвертированном знаке ALP.
    """
    from core.health.phenoage import phenoage_from_markers

    low = phenoage_from_markers(48, dict(_MARKERS, ALP=50.0))
    high = phenoage_from_markers(48, dict(_MARKERS, ALP=300.0))
    assert high > low, f"высокий ALP дал bio_age={high} ≤ низкий ALP {low} — знак ALP инвертирован"


def test_phenoage_known_reference_case():
    """Якорное значение: фиксируем абсолютный bio_age для эталонного набора,
    чтобы будущие правки формулы не сдвинули результат незаметно."""
    from core.health.phenoage import phenoage_from_markers

    # Значение посчитано независимым оракулом выше для chrono=48 и _MARKERS.
    expected = _levine_phenoage(48, _MARKERS)
    got = phenoage_from_markers(48, _MARKERS)
    assert got == pytest.approx(expected, abs=0.05)
    # sanity: для здоровых маркеров и 48 лет PhenoAge должен быть в разумном
    # диапазоне (не отрицательный, не абсурдно большой).
    assert 20 < got < 80, f"bio_age={got} вне физиологичного диапазона"
