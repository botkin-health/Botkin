# core/health/staleness.py
"""Per-marker staleness thresholds and helper functions.

Thresholds are 2× the medically-recommended retest interval.
This means the indicator only fires when data is genuinely stale,
not just due for a routine check-up.
"""

from __future__ import annotations

from datetime import date as _date

# Threshold in days for unknown canonical keys.
DEFAULT_STALENESS_DAYS: int = 730

# canonical_key → staleness threshold in days.
# None = never stale (e.g. adult height).
STALENESS_DAYS: dict[str, int | None] = {
    # ── Anthropometry ─────────────────────────────────────────
    "height_cm": None,  # stable in adults
    "weight": 60,  # 2× monthly
    "bmi": 60,
    "body_fat": 60,
    "muscle_mass": 60,
    "visceral_fat": 60,
    # Body measurements (body_measurements table)
    "waist_cm": 180,  # 2× quarterly
    "neck_cm": 180,
    "hips_cm": 180,
    "chest_cm": 180,
    "thigh_cm": 180,
    "biceps_cm": 180,
    # ── Metabolism ────────────────────────────────────────────
    "HbA1c": 180,  # 2× ADA quarterly
    "glucose": 180,
    "insulin": 180,
    "HOMA_index": 180,
    # ── Coagulation ──────────────────────────────────────────
    "INR": 180,
    "APTT": 180,
    "d_dimer": 180,
    # ── Vitamins & minerals ───────────────────────────────────
    "vitamin_D": 365,  # 2× Endocrine Society semi-annual
    "vitamin_B12": 365,
    "folic_acid": 365,
    "ferritin": 365,
    "iron": 365,
    "transferrin": 365,
    "magnesium": 365,
    "zinc": 365,
    "omega3_index": 365,
    # ── Hormones (dynamic with therapy/optimisation) ──────────
    "testosterone": 365,
    "testosterone_free": 365,
    "DHT": 365,
    "FAI": 365,
    "SHBG": 365,
    "TSH": 365,
    "FT3": 365,
    "FT4": 365,
    "DHEA_S": 365,
    "cortisol": 365,
    "IGF_1": 365,
    "NT_proBNP": 365,
    "ESR": 365,
    # ── Lipids (annual screening) ─────────────────────────────
    "cholesterol_total": 730,
    "HDL": 730,
    "LDL": 730,
    "triglycerides": 730,
    "ApoB": 730,
    "ApoA1": 730,
    "atherogenic_index": 730,
    "lipoprotein_a": 1460,  # 2× biennial; Lp(a) is genetically stable
    # ── Liver ─────────────────────────────────────────────────
    "ALT": 730,
    "AST": 730,
    "GGT": 730,
    "ALP": 730,
    "bilirubin_total": 730,
    "total_protein": 730,
    "albumin_g_l": 730,
    "amylase": 730,
    # ── Kidney ────────────────────────────────────────────────
    "creatinine": 730,
    "egfr": 730,
    "uric_acid": 730,
    "urea": 730,
    # ── CBC ───────────────────────────────────────────────────
    "WBC": 730,
    "RBC": 730,
    "Hb": 730,
    "HCT": 730,
    "MCH": 730,
    "MCHC": 730,
    "MCV": 730,
    "RDW_CV": 730,
    "PLT": 730,
    "lymphocytes": 730,
    "neutrophils": 730,
    "monocytes": 730,
    "eosinophils": 730,
    "basophils": 730,
    # ── Inflammation / other ──────────────────────────────────
    "hs_CRP": 730,
    "CRP": 730,
    "homocysteine": 730,
    "fibrinogen": 730,
    "vitamin_A": 730,
    "vitamin_E": 730,
    "vitamin_B6": 730,
    "calcium": 730,
    "potassium": 730,
    "sodium": 730,
    "PSA_total": 730,
    # ── Hormones (stable, annual check) ──────────────────────
    "prolactin": 730,
    "LH": 730,
    "FSH": 730,
    "PTH_intact": 730,
    "Anti_TPO": 730,
    "Anti_Tg": 730,
}


def get_staleness_days(canonical_key: str) -> int | None:
    """Staleness threshold in days for *canonical_key*.

    Returns ``None`` when the marker never goes stale (e.g. adult height).
    Returns ``DEFAULT_STALENESS_DAYS`` for unknown keys.
    """
    if canonical_key in STALENESS_DAYS:
        return STALENESS_DAYS[canonical_key]
    return DEFAULT_STALENESS_DAYS


def days_ago_from_str(date_str: str | None) -> int | None:
    """Days between ISO-8601 *date_str* and today. Returns ``None`` on bad input."""
    if not date_str or date_str == "—":
        return None
    try:
        return (_date.today() - _date.fromisoformat(date_str)).days
    except (ValueError, TypeError):
        return None


def stale_label(days: int | None, threshold: int | None) -> str | None:
    """Human-readable staleness badge, or ``None`` when data is fresh.

    - ``None`` threshold → marker never goes stale → ``None``.
    - ``days`` ≤ ``threshold`` → fresh → ``None``.
    - ``days`` ≤ ``threshold * 2`` → moderately stale → ``"⚠ N мес назад"``.
    - ``days`` > ``threshold * 2`` → very stale → ``"🚨 N.N года назад"``.
    """
    if days is None or threshold is None or days <= threshold:
        return None
    if days <= threshold * 2:
        return f"⚠ {days // 30} мес назад"
    return f"🚨 {round(days / 365, 1)} года назад"
