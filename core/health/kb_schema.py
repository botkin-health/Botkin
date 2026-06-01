# core/health/kb_schema.py
"""Единый канонический реестр биомаркеров — source of truth для маппинга
сырых KB-ключей в канонические + единицы измерения.

Заменяет разрозненные маппинги:
  - scripts/generate_biomarkers_json.py (add() lists)
  - core/reports/biomarker_dynamics.py (MARKER_CONFIG) — TODO: мигрировать сюда
И избавляет от форматных расхождений между KB разных пользователей
(CamelCase у Александра vs snake_case_with_units у Димы).

Правила:
  - Только ЯВНЫЕ алиасы. Никакого авто-стрипа суффиксов:
    albumin_pct (электрофорез, %) и albumin_g_l (г/л) — РАЗНЫЕ маркеры.
  - Lookup case-insensitive (по lower() алиаса).
  - Конверсия единиц через множитель; алиас без известного фактора НЕ маппится
    и попадает в warnings (правило «не сглаживать молча»).

Множители конверсии (сырой → каноническая единица), с источниками:
  insulin:  pmol/L → µIU/mL = ÷6.945   (1 µIU/mL = 6.945 pmol/L)
  folate:   nmol/L → ng/mL  = ÷2.266   (1 ng/mL = 2.266 nmol/L)
  B12:      pmol/L → pg/mL  = ×1.355   (1 pg/mL = 0.7378 pmol/L)
  PTH:      pmol/L → pg/mL  = ×9.434   (1 pg/mL = 0.106 pmol/L, МВ ~9425 Da)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CanonicalMarker:
    unit: str  # каноническая единица (как в дашборде)
    aliases: dict[str, float]  # сырой_ключ → множитель к канонической единице (1.0 = та же)


# Канонические имена СОВПАДАЮТ с ключами текущего biomarkers_<id>.json и
# dashboard_generator biomarkers_latest — менять их нельзя (сломает дашборд).
CANONICAL: dict[str, CanonicalMarker] = {
    # ── Metabolic ────────────────────────────────────────────────────────────
    "HbA1c": CanonicalMarker("%", {"HbA1c": 1, "A1c": 1, "hba1c_pct": 1}),
    "glucose": CanonicalMarker("ммоль/л", {"glucose": 1, "glucose_mmol_l": 1}),
    "insulin": CanonicalMarker("мкЕд/мл", {"insulin": 1, "insulin_pmol_l": 1 / 6.945}),
    # unit="" — безразмерные или единица варьируется по лаборатории
    "HOMA_index": CanonicalMarker("", {"HOMA_index": 1, "homa_ir": 1}),
    # ── Lipids ───────────────────────────────────────────────────────────────
    "cholesterol_total": CanonicalMarker(
        "ммоль/л",
        {
            "cholesterol_total": 1,
            "total_cholesterol": 1,
            "cholesterol": 1,
            "total_cholesterol_mmol_l": 1,
            "cholesterol_mmol_l": 1,
        },
    ),
    "HDL": CanonicalMarker("ммоль/л", {"HDL": 1, "cholesterol_HDL": 1, "hdl_mmol_l": 1}),
    "LDL": CanonicalMarker("ммоль/л", {"LDL": 1, "cholesterol_LDL": 1, "ldl_mmol_l": 1}),
    "triglycerides": CanonicalMarker("ммоль/л", {"triglycerides": 1, "tg": 1, "triglycerides_mmol_l": 1}),
    "ApoB": CanonicalMarker("г/л", {"ApoB": 1, "apo_b": 1, "apob_g_l": 1}),
    "ApoA1": CanonicalMarker("г/л", {"ApoA1": 1, "apo_a1": 1}),
    "lipoprotein_a": CanonicalMarker("г/л", {"lipoprotein_a": 1, "lp_a": 1, "lpa": 1}),
    "atherogenic_index": CanonicalMarker("", {"atherogenic_index": 1, "atherogenic_coefficient": 1}),
    # ── Liver / inflammation ─────────────────────────────────────────────────
    "ALT": CanonicalMarker("Ед/л", {"ALT": 1, "alt_u_l": 1}),
    "AST": CanonicalMarker("Ед/л", {"AST": 1, "ast_u_l": 1}),
    "GGT": CanonicalMarker("Ед/л", {"GGT": 1, "ggt_u_l": 1}),
    "ALP": CanonicalMarker("Ед/л", {"ALP": 1, "alkaline_phosphatase": 1, "alkaline_phosphatase_u_l": 1}),
    "bilirubin_total": CanonicalMarker(
        "мкмоль/л", {"bilirubin_total": 1, "total_bilirubin": 1, "bilirubin_total_umol_l": 1}
    ),
    "hs_CRP": CanonicalMarker("мг/л", {"hs_CRP": 1, "hscrp": 1}),
    "CRP": CanonicalMarker("мг/л", {"CRP": 1, "crp_mg_l": 1}),
    # ── Hormones ─────────────────────────────────────────────────────────────
    "testosterone": CanonicalMarker(
        "нмоль/л", {"testosterone": 1, "total_testosterone": 1, "testosterone_total_nmol_l": 1}
    ),
    "TSH": CanonicalMarker("мМЕ/л", {"TSH": 1, "tsh_miu_l": 1}),
    "FT3": CanonicalMarker("пмоль/л", {"FT3": 1, "T3_free": 1, "t3_free_pmol_l": 1}),
    "FT4": CanonicalMarker("пмоль/л", {"FT4": 1, "T4_free": 1, "t4_free_pmol_l": 1}),
    "cortisol": CanonicalMarker("нмоль/л", {"cortisol": 1}),
    "SHBG": CanonicalMarker("нмоль/л", {"SHBG": 1, "shbg_nmol_l": 1}),
    "prolactin": CanonicalMarker("", {"prolactin": 1}),
    "LH": CanonicalMarker("", {"LH": 1}),
    "FSH": CanonicalMarker("", {"FSH": 1}),
    "DHEA_S": CanonicalMarker("", {"DHEA_S": 1, "DHEAS": 1, "DHEA-S": 1}),
    "FAI": CanonicalMarker("", {"FAI": 1, "free_androgen_index": 1}),
    "PTH_intact": CanonicalMarker("пг/мл", {"PTH_intact": 1, "parathyroid_hormone": 1, "PTH": 1, "pth_pmol_l": 9.434}),
    "homocysteine": CanonicalMarker("мкмоль/л", {"homocysteine": 1, "homocystein": 1, "homocysteine_umol_l": 1}),
    "IGF_1": CanonicalMarker("", {"IGF_1": 1, "IGF-1": 1, "igf1": 1}),
    # ── Vitamins / nutrients ─────────────────────────────────────────────────
    "vitamin_D": CanonicalMarker(
        "нг/мл", {"vitamin_D": 1, "vitamin_D3": 1, "vitD": 1, "vit_d": 1, "vitamin_d_ng_ml": 1}
    ),
    "vitamin_B12": CanonicalMarker("пг/мл", {"vitamin_B12": 1, "vitamin_b12_pmol_l": 1.355}),
    "ferritin": CanonicalMarker("мкг/л", {"ferritin": 1, "ferritin_ng_ml": 1}),
    "folic_acid": CanonicalMarker("нг/мл", {"folic_acid": 1, "folate": 1, "folate_nmol_l": 1 / 2.266}),
    "magnesium": CanonicalMarker("ммоль/л", {"magnesium": 1, "Mg": 1}),
    "zinc": CanonicalMarker("мкмоль/л", {"zinc": 1, "Zn": 1}),
    "iron": CanonicalMarker("мкмоль/л", {"iron": 1, "Fe": 1, "iron_serum_umol_l": 1, "iron_umol_l": 1}),
    # ── Kidneys ──────────────────────────────────────────────────────────────
    "creatinine": CanonicalMarker("мкмоль/л", {"creatinine": 1, "creatinine_umol_l": 1}),
    "egfr": CanonicalMarker("", {"egfr_ckd_epi": 1, "egfr": 1, "gfr": 1}),
    "uric_acid": CanonicalMarker("мкмоль/л", {"uric_acid": 1, "uric_acid_umol_l": 1}),
    "urea": CanonicalMarker("ммоль/л", {"urea": 1}),
    # ── CBC ──────────────────────────────────────────────────────────────────
    "WBC": CanonicalMarker("10⁹/л", {"WBC": 1, "wbc_10_9_l": 1}),
    "RBC": CanonicalMarker("10¹²/л", {"RBC": 1, "rbc_10_12_l": 1}),
    "Hb": CanonicalMarker("г/л", {"Hb": 1, "HGB": 1, "hemoglobin": 1, "hgb_g_l": 1}),
    "lymphocytes": CanonicalMarker(
        "%", {"lymphocytes": 1, "lymphocytes_percent": 1, "lymphocytes_rel": 1, "lymphocytes_pct": 1}
    ),
    "MCV": CanonicalMarker("фл", {"MCV": 1, "mcv_fl": 1}),
    "RDW_CV": CanonicalMarker("%", {"RDW_CV": 1, "RDW": 1}),
    "PLT": CanonicalMarker("10⁹/л", {"PLT": 1, "platelets": 1, "platelets_10_9_l": 1}),
    "ESR": CanonicalMarker("мм/ч", {"ESR": 1, "esr_mm_h": 1}),
    # albumin_pct/_percent (электрофорез, %) — ДРУГОЙ маркер, намеренно НЕ алиас
    "albumin_g_l": CanonicalMarker("г/л", {"albumin_g_l": 1, "albumin": 1}),
    # ── Other ────────────────────────────────────────────────────────────────
    "PSA_total": CanonicalMarker("нг/мл", {"PSA_total": 1, "psa": 1, "psa_ng_ml": 1}),
    "calcium": CanonicalMarker("ммоль/л", {"calcium": 1, "Ca": 1}),
    "potassium": CanonicalMarker("ммоль/л", {"potassium": 1, "K": 1}),
    "sodium": CanonicalMarker("ммоль/л", {"sodium": 1, "Na": 1}),
}


def _build_reverse() -> dict[str, tuple[str, float]]:
    idx: dict[str, tuple[str, float]] = {}
    for canon_key, marker in CANONICAL.items():
        for alias, factor in marker.aliases.items():
            low = alias.lower()
            if low in idx:
                raise ValueError(f"duplicate alias {alias!r} in CANONICAL ({idx[low][0]} vs {canon_key})")
            idx[low] = (canon_key, factor)
    return idx


_REVERSE: dict[str, tuple[str, float]] = _build_reverse()


def reverse_index() -> dict[str, tuple[str, float]]:
    """Копия реверс-индекса (для тестов / интроспекции)."""
    return dict(_REVERSE)


def to_canonical(values: dict, *, passthrough_unmapped: bool = False) -> tuple[dict[str, float], list[str]]:
    """Сырые KB-values → {canonical_key: converted_value}.

    Возвращает (canon, warnings). Числовые значения конвертируются множителем;
    нечисловые пропускаются. Алиас, не найденный в реестре, либо отбрасывается
    с предупреждением, либо (passthrough_unmapped=True) пробрасывается как есть.
    passthrough_unmapped=True пробрасывает немаппленные ключи без warning.
    """
    canon: dict[str, float] = {}
    exact_source: dict[str, str] = {}  # canon_key → исходный alias, выигравший слот
    warnings: list[str] = []

    for raw_key, raw_val in values.items():
        if not isinstance(raw_val, (int, float)) or isinstance(raw_val, bool):
            continue
        hit = _REVERSE.get(raw_key.lower())
        if hit is None:
            if passthrough_unmapped:
                canon[raw_key] = raw_val
            else:
                warnings.append(f"unknown key {raw_key!r}: not in canonical registry, skipped")
            continue
        canon_key, factor = hit
        new_val = raw_val * factor
        if canon_key in canon and exact_source.get(canon_key) != raw_key:
            prev = canon[canon_key]
            prior_alias = exact_source.get(canon_key, "?")
            # коллизия: приоритет exact-case (raw_key == canon_key)
            if raw_key == canon_key:
                canon[canon_key] = new_val
                exact_source[canon_key] = raw_key
            if abs(prev - new_val) > 1e-9:
                warnings.append(f"collision on {canon_key}: {prior_alias}={prev} vs {raw_key}={new_val}")
            continue
        canon[canon_key] = new_val
        exact_source[canon_key] = raw_key

    return canon, warnings
