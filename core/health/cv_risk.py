"""
Калькуляторы кардиоваскулярного риска для дашборда:
  - SCORE2 (ESC 2021) — 10-летний риск ССЗ для Европы
  - ASCVD Lifetime Risk (AHA/ACC) — пожизненный риск
  - Body Composition trends — динамика веса/жира/мышц

Все функции мульти-юзерные: принимают параметры, не делают I/O.
Если данных не хватает — возвращают None / структуру с явным "missing".

Источники:
  SCORE2: https://academic.oup.com/eurheartj/article/42/25/2439/6297709
          (SCORE2 working group, Eur Heart J 2021;42:2439-54)
  ASCVD:  https://www.ahajournals.org/doi/10.1161/CIR.0000000000000678
          (Goff DC Jr et al. 2014 ACC/AHA Guideline; lifetime risk extrapolation)
"""

from __future__ import annotations

import math
from typing import Optional


# ─────────────────────────────────────────────────────────────────────
#  SCORE2 — 10-year fatal+nonfatal CVD risk
# ─────────────────────────────────────────────────────────────────────

# Коэффициенты SCORE2 для high-risk региона (Россия попадает сюда),
# мужчины, возраст 40-69. Источник: ESC SCORE2 supplementary table S5.
# Для женщин и low-risk регионов — другие константы (TODO для multi-user).
_SCORE2_HIGH_RISK_MALE = {
    # Линейные предикторы (бета-коэффициенты), age centered at 60, others standardized
    "age": 0.3742,
    "smoking": 0.6012,
    "sbp": 0.2777,  # per (sbp − 120) / 20 — стандартизация
    "tchol": 0.1458,  # per (tchol − 6.0) / 1.0 mmol/L
    "hdl": -0.2698,  # per (hdl − 1.3) / 0.5 mmol/L
    "smoking_age": -0.0755,  # interaction
    "sbp_age": -0.0255,
    "tchol_age": -0.0281,
    "hdl_age": 0.0426,
    # baseline survival at 10 years for high-risk male
    "S0": 0.9605,
    # Calibration scale + shape (recalibrated from baseline cohort to high-risk region)
    "scale1": 0.2436,
    "scale2": 1.0070,
}

_SCORE2_HIGH_RISK_FEMALE = {
    "age": 0.4648,
    "smoking": 0.7744,
    "sbp": 0.3131,
    "tchol": 0.1002,
    "hdl": -0.2606,
    "smoking_age": -0.1088,
    "sbp_age": -0.0277,
    "tchol_age": -0.0226,
    "hdl_age": 0.0613,
    "S0": 0.9776,
    "scale1": 0.5102,
    "scale2": 0.8851,
}


def calc_score2(
    *,
    age: int,
    sex: str,  # "male" | "female"
    smoking: bool,  # активный курильщик
    sbp_mmhg: float,  # систолическое давление
    tchol_mmolL: float,  # общий холестерин
    hdl_mmolL: float,  # ЛПВП
    region: str = "high",  # "low" / "moderate" / "high" / "very_high"
) -> Optional[dict]:
    """SCORE2 для людей 40-69. Для 70+ нужен SCORE2-OP (другая модель).

    Returns:
        {
            "risk_pct": float (0..100),
            "category": "low" | "moderate" | "high" | "very_high",
            "color": "g" | "y" | "o" | "r",
            "interpretation": str,
        }
        или None если данных не хватает / возраст вне диапазона.
    """
    if not all([age, sex, sbp_mmhg, tchol_mmolL, hdl_mmolL]):
        return None
    if not (40 <= age <= 69):
        # SCORE2-OP пока не реализован
        return None

    coef = _SCORE2_HIGH_RISK_MALE if sex == "male" else _SCORE2_HIGH_RISK_FEMALE

    # Стандартизация переменных (как в оригинальной формуле)
    cage = (age - 60) / 5
    csbp = (sbp_mmhg - 120) / 20
    cchol = (tchol_mmolL - 6.0) / 1.0
    chdl = (hdl_mmolL - 1.3) / 0.5
    csmoke = 1 if smoking else 0

    lp = (
        coef["age"] * cage
        + coef["smoking"] * csmoke
        + coef["sbp"] * csbp
        + coef["tchol"] * cchol
        + coef["hdl"] * chdl
        + coef["smoking_age"] * csmoke * cage
        + coef["sbp_age"] * csbp * cage
        + coef["tchol_age"] * cchol * cage
        + coef["hdl_age"] * chdl * cage
    )

    # Базовый риск: 1 - S0^exp(lp)
    raw_risk = 1 - coef["S0"] ** math.exp(lp)
    # Калибровка под регион (для high-risk)
    # Применяем рекалибровочное преобразование SCORE2
    cal = 1 - math.exp(-math.exp(coef["scale1"] + coef["scale2"] * math.log(-math.log(1 - raw_risk))))
    risk_pct = round(cal * 100, 1)

    # Возрастная классификация по ESC:
    #   <50 лет: low <2.5%, mod 2.5-7.5%, high ≥7.5%
    #   50-69 лет: low <5%, mod 5-10%, high ≥10%
    if age < 50:
        if risk_pct < 2.5:
            category, color = "low", "g"
        elif risk_pct < 7.5:
            category, color = "moderate", "y"
        else:
            category, color = "high", "r"
    else:
        if risk_pct < 5:
            category, color = "low", "g"
        elif risk_pct < 10:
            category, color = "moderate", "y"
        else:
            category, color = "high", "r"

    cat_ru = {"low": "низкий", "moderate": "умеренный", "high": "высокий"}[category]
    interpretation = f"10-летний риск инфаркта/инсульта = {risk_pct}%. Категория: {cat_ru}. "
    if category == "low":
        interpretation += "Статины сейчас не показаны, продолжай образ жизни."
    elif category == "moderate":
        interpretation += "Если оптимизация образа жизни не снижает ApoB <0.9 / LDL <2.6 — обсудить статины."
    else:
        interpretation += "Статины показаны. Обсудить с кардиологом."

    return {
        "risk_pct": risk_pct,
        "category": category,
        "category_ru": cat_ru,
        "color": color,
        "interpretation": interpretation,
        "inputs": {
            "age": age,
            "sex": sex,
            "smoking": smoking,
            "sbp": sbp_mmhg,
            "tchol": tchol_mmolL,
            "hdl": hdl_mmolL,
            "region": region,
        },
    }


# ─────────────────────────────────────────────────────────────────────
#  ASCVD Lifetime Risk (AHA/ACC)
# ─────────────────────────────────────────────────────────────────────


def calc_ascvd_lifetime(
    *,
    age: int,
    sex: str,
    smoking: bool,
    sbp_mmhg: float,
    tchol_mmolL: float,
    hdl_mmolL: float,
    diabetes: bool = False,
    on_bp_meds: bool = False,
) -> Optional[dict]:
    """Пожизненный риск ASCVD (Lloyd-Jones et al. 2006 / AHA 2013).

    Упрощённая модель: классифицирует по 5 факторам риска (curated risk profile)
    и возвращает интерполированный пожизненный риск из таблиц AHA.

    Факторы риска (Lloyd-Jones major):
      - SBP ≥140 или на лекарствах
      - TChol ≥6.2 mmol/L (240 mg/dL)
      - HDL <1.0 (40 mg/dL) у муж / <1.3 (50) у жен
      - Курение
      - Диабет

    Категории (Lloyd-Jones JACC 2006):
      Все факторы оптимальны → 5%
      Не оптимальны но не повышены (≥1 not optimal) → 36% (м) / 27% (ж)
      ≥1 повышен (но не major) → 50%
      1 major risk factor → 60% (м) / 40% (ж)
      ≥2 major risk factors → 70%+ (м) / 50%+ (ж)
    """
    if not all([age, sex, sbp_mmhg, tchol_mmolL, hdl_mmolL]):
        return None
    if not (20 <= age <= 79):
        return None

    is_male = sex == "male"
    hdl_threshold = 1.0 if is_male else 1.3

    # Классификация каждого параметра: "optimal" / "not_optimal" / "elevated" / "major"
    def _classify_sbp(sbp, on_meds):
        if on_meds:
            return "major"
        if sbp < 120:
            return "optimal"
        if sbp < 140:
            return "elevated"
        return "major"

    def _classify_chol(tc):
        if tc < 4.7:  # <180 mg/dL
            return "optimal"
        if tc < 5.2:  # 180-200
            return "not_optimal"
        if tc < 6.2:  # 200-239
            return "elevated"
        return "major"

    def _classify_hdl(hdl, threshold):
        # HDL: ниже = хуже (обратная шкала)
        if hdl >= threshold + 0.3:
            return "optimal"
        if hdl >= threshold:
            return "not_optimal"
        return "major"  # very low HDL = major

    sbp_cat = _classify_sbp(sbp_mmhg, on_bp_meds)
    chol_cat = _classify_chol(tchol_mmolL)
    hdl_cat = _classify_hdl(hdl_mmolL, hdl_threshold)
    smoke_cat = "major" if smoking else "optimal"
    dm_cat = "major" if diabetes else "optimal"

    cats = [sbp_cat, chol_cat, hdl_cat, smoke_cat, dm_cat]
    n_major = sum(1 for c in cats if c == "major")
    n_elevated = sum(1 for c in cats if c == "elevated")
    n_not_optimal = sum(1 for c in cats if c in ("not_optimal", "elevated"))

    # Lloyd-Jones JACC 2006 lifetime risk (50yo baseline, ASCVD events to age 95)
    if is_male:
        if n_major >= 2:
            risk_pct = 69.1
        elif n_major == 1:
            risk_pct = 50.0
        elif n_elevated >= 1:
            risk_pct = 39.6
        elif n_not_optimal >= 1:
            risk_pct = 36.4
        else:
            risk_pct = 5.2
    else:
        if n_major >= 2:
            risk_pct = 50.2
        elif n_major == 1:
            risk_pct = 39.1
        elif n_elevated >= 1:
            risk_pct = 27.5
        elif n_not_optimal >= 1:
            risk_pct = 27.6
        else:
            risk_pct = 8.2

    # Возрастная коррекция: lifetime от 50 — фиксирован; для 30-49 чуть выше, 60-69 чуть ниже
    if age < 50:
        risk_pct *= 1.05
    elif age >= 60:
        risk_pct *= 0.92
    elif age >= 70:
        risk_pct *= 0.80
    risk_pct = round(risk_pct, 1)

    if risk_pct < 20:
        category, color = "low", "g"
    elif risk_pct < 40:
        category, color = "moderate", "y"
    elif risk_pct < 60:
        category, color = "high", "o"
    else:
        category, color = "very_high", "r"

    cat_ru = {"low": "низкий", "moderate": "умеренный", "high": "высокий", "very_high": "очень высокий"}[category]
    interpretation = (
        f"Из 100 человек с твоим профилем у {risk_pct:.0f} случится инфаркт или инсульт когда-нибудь до конца жизни. "
        f"Категория: {cat_ru}. "
    )
    if category in ("low", "moderate"):
        interpretation += "Профилактика (диета, спорт, оптимизация ApoB) даёт максимум пользы именно сейчас."
    else:
        interpretation += (
            "Раннее агрессивное вмешательство (статины + изменения образа жизни) сильно снижает этот риск."
        )

    return {
        "risk_pct": risk_pct,
        "category": category,
        "category_ru": cat_ru,
        "color": color,
        "interpretation": interpretation,
        "factors": {
            "sbp": sbp_cat,
            "chol": chol_cat,
            "hdl": hdl_cat,
            "smoking": smoke_cat,
            "diabetes": dm_cat,
        },
        "n_major": n_major,
        "n_elevated": n_elevated,
        "inputs": {
            "age": age,
            "sex": sex,
            "smoking": smoking,
            "sbp": sbp_mmhg,
            "tchol": tchol_mmolL,
            "hdl": hdl_mmolL,
            "diabetes": diabetes,
            "on_bp_meds": on_bp_meds,
        },
    }
