# core/health/kb_schema.py
"""Единый канонический реестр биомаркеров — source of truth для маппинга
сырых KB-ключей в канонические + единицы измерения.

Заменяет разрозненные маппинги:
  - scripts/generate_biomarkers_json.py (add() lists)
  - core/reports/biomarker_dynamics.py — панели MARKER_CONFIG теперь ключуются
    каноном отсюда (миграция выполнена; параллельный реестр алиасов убран)
И избавляет от форматных расхождений между KB разных пользователей
(CamelCase у Александра vs snake_case_with_units у Димы).

Правила:
  - Только ЯВНЫЕ алиасы. Никакого авто-стрипа суффиксов:
    albumin_pct (электрофорез, %) и albumin_g_l (г/л) — РАЗНЫЕ маркеры.
  - Lookup case-insensitive (по lower() алиаса).
  - Конверсия единиц через множитель; алиас без известного фактора НЕ маппится
    и попадает в warnings (правило «не сглаживать молча»).
  - Явная единица маркера (поле <ключ>_unit, напр. hs_CRP_unit="mg/dl") важнее
    алиас-фактора и признака US-панели: множитель выводится из единицы (масса/моль
    на объём, SI-приставки, MOLAR_MASS для масса↔моль). Нераспознанная единица
    (Ед/л, МЕ/мл, 10^9/л) значение не меняет.

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
    "ALP": CanonicalMarker(
        "Ед/л", {"ALP": 1, "ALKP": 1, "alkaline_phosphatase": 1, "alkaline_phosphatase_u_l": 1, "alp_u_l": 1}
    ),
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
    # Активный B12 — отдельный аналит со своей нормой (≈25–165 пмоль/л). Записанный
    # как vitamin_B12 (пг/мл общего B12) выглядит тяжёлым дефицитом (#558).
    "holotranscobalamin": CanonicalMarker(
        "пмоль/л", {"holotranscobalamin": 1, "holoTC": 1, "active_B12": 1, "vitamin_B12_active": 1}
    ),
    "ferritin": CanonicalMarker("мкг/л", {"ferritin": 1, "ferritin_ng_ml": 1}),
    "folic_acid": CanonicalMarker("нг/мл", {"folic_acid": 1, "folate": 1, "folate_nmol_l": 1 / 2.266}),
    "magnesium": CanonicalMarker("ммоль/л", {"magnesium": 1, "Mg": 1}),
    "zinc": CanonicalMarker("мкмоль/л", {"zinc": 1, "Zn": 1}),
    "iron": CanonicalMarker("мкмоль/л", {"iron": 1, "Fe": 1, "iron_serum_umol_l": 1, "iron_umol_l": 1}),
    # ── Kidneys ──────────────────────────────────────────────────────────────
    "creatinine": CanonicalMarker("мкмоль/л", {"creatinine": 1, "creatinine_umol_l": 1}),
    "egfr": CanonicalMarker("", {"egfr_ckd_epi": 1, "egfr": 1, "gfr": 1}),
    "uric_acid": CanonicalMarker("мкмоль/л", {"uric_acid": 1, "uric_acid_umol_l": 1}),
    "urea": CanonicalMarker("ммоль/л", {"urea": 1, "urea_mmol_l": 1}),
    # ── CBC ──────────────────────────────────────────────────────────────────
    "WBC": CanonicalMarker("10⁹/л", {"WBC": 1, "wbc_10_9_l": 1}),
    "RBC": CanonicalMarker("10¹²/л", {"RBC": 1, "rbc_10_12_l": 1}),
    "Hb": CanonicalMarker("г/л", {"Hb": 1, "HGB": 1, "hemoglobin": 1, "hemoglobin_g_L": 1, "hgb_g_l": 1}),
    "lymphocytes": CanonicalMarker(
        "%", {"lymphocytes": 1, "lymphocytes_percent": 1, "lymphocytes_rel": 1, "lymphocytes_pct": 1, "lymph_pct": 1}
    ),
    "MCV": CanonicalMarker("фл", {"MCV": 1, "mcv_fl": 1}),
    "RDW_CV": CanonicalMarker("%", {"RDW_CV": 1, "RDW": 1, "rdw_cv_pct": 1}),
    "PLT": CanonicalMarker("10⁹/л", {"PLT": 1, "platelets": 1, "platelets_10_9_l": 1, "plt_10_9_l": 1}),
    "ESR": CanonicalMarker("мм/ч", {"ESR": 1, "esr_mm_h": 1}),
    # albumin_pct/_percent (электрофорез, %) — ДРУГОЙ маркер, намеренно НЕ алиас
    "albumin_g_l": CanonicalMarker("г/л", {"albumin_g_l": 1, "albumin": 1}),
    # ── Other ────────────────────────────────────────────────────────────────
    "PSA_total": CanonicalMarker("нг/мл", {"PSA_total": 1, "psa": 1, "psa_ng_ml": 1}),
    "calcium": CanonicalMarker("ммоль/л", {"calcium": 1, "Ca": 1, "calcium_total": 1}),
    # Ионизированный кальций — отдельный аналит (норма ≈1.12–1.32 ммоль/л), не общий (#558).
    "calcium_ionized": CanonicalMarker("ммоль/л", {"calcium_ionized": 1, "Ca_ionized": 1, "ionized_calcium": 1}),
    "potassium": CanonicalMarker("ммоль/л", {"potassium": 1, "K": 1, "potassium_mmol_l": 1}),
    "sodium": CanonicalMarker("ммоль/л", {"sodium": 1, "Na": 1, "sodium_mmol_l": 1}),
    # ── CBC (extended) ───────────────────────────────────────────────────────
    "HCT": CanonicalMarker("%", {"hct_pct": 1, "Ht": 1, "hematocrit": 1}),
    # NB: и "HCT", и "Hct" лоуэркейсятся в "hct" — у Александра это доля (0.451 L/L),
    # неоднозначно с %, поэтому "hct"-вариант НЕ алиас. Маппим только однозначные
    # %-ключи: Ht (Александр, n=11), hematocrit, hct_pct (Дима).
    "MCH": CanonicalMarker("пг", {"MCH": 1, "mch_pg": 1}),
    "MCHC": CanonicalMarker("г/л", {"MCHC": 1, "mchc_g_l": 1}),
    "neutrophils": CanonicalMarker(
        "%", {"neutrophils_percent": 1, "neutrophils_seg": 1, "neutrophils_seg_pct": 1, "neut_pct": 1}
    ),
    # bare "neutrophils" у Александра = абс. число (×10⁹/л) — НЕ алиас.
    # neut_pct (К+31, Андрей) = общий % нейтрофилов (сегменто+палочко) — это %, безопасный алиас.
    "monocytes": CanonicalMarker(
        "%", {"monocytes": 1, "monocytes_percent": 1, "monocytes_rel": 1, "monocytes_pct": 1, "mon_pct": 1}
    ),
    "eosinophils": CanonicalMarker(
        "%", {"eosinophils": 1, "eosinophils_percent": 1, "eosinophils_rel": 1, "eosinophils_pct": 1, "eo_pct": 1}
    ),
    "basophils": CanonicalMarker("%", {"basophils": 1, "basophils_percent": 1, "basophils_pct": 1, "bas_pct": 1}),
    # ── Coagulation ──────────────────────────────────────────────────────────
    "INR": CanonicalMarker("", {"INR": 1}),
    "APTT": CanonicalMarker("сек", {"APTT": 1, "aptt_sec": 1}),
    "fibrinogen": CanonicalMarker("г/л", {"fibrinogen": 1, "fibrinogen_g_l": 1}),
    "d_dimer": CanonicalMarker("нг/мл", {"D_dimer": 1, "d_dimer_ng_feu_ml": 1}),
    # ── Proteins / enzymes (extended) ─────────────────────────────────────────
    "total_protein": CanonicalMarker("г/л", {"total_protein": 1, "protein_total": 1, "total_protein_g_l": 1}),
    "amylase": CanonicalMarker("Ед/л", {"amylase": 1, "alpha_amylase": 1, "amylase_pancreatic_u_l": 1}),
    # амилаза: total (alpha_amylase) и панкреатическая (Дима) — разные аналиты, та же единица.
    # ── Hormones (extended) ──────────────────────────────────────────────────
    "DHT": CanonicalMarker("пг/мл", {"dht": 1, "dihydrotestosterone_pg_ml": 1}),
    "testosterone_free": CanonicalMarker("пмоль/л", {"testosterone_free_pmol_l": 1}),
    # NB: Александровы free_testosterone/testosterone_free в иной шкале (≈16-19, не pmol/L) — НЕ алиасы.
    "Anti_TPO": CanonicalMarker("МЕ/мл", {"anti_TPO": 1, "anti_tpo_iu_ml": 1}),
    "Anti_Tg": CanonicalMarker("МЕ/мл", {"anti_Tg": 1, "anti_tg_iu_ml": 1}),
    # ── Vitamins (extended) ──────────────────────────────────────────────────
    "vitamin_A": CanonicalMarker("мкг/мл", {"vitamin_a_ug_ml": 1}),
    "vitamin_E": CanonicalMarker("мкг/мл", {"vitamin_e_ug_ml": 1}),
    "vitamin_B6": CanonicalMarker("нг/мл", {"vitamin_b6_ng_ml": 1}),
    # ── Cardiac / lipid risk (extended) ───────────────────────────────────────
    # NT-proBNP: канон пг/мл (как в dashboard_generator biomarkers_latest).
    # Альтернативная лабораторная единица — пмоль/л (×0.118 → пг/мл, МВ 8458 Da);
    # фактор НЕ задаём, т.к. реальных pmol/L-значений в KB пока нет — добавить при появлении.
    "NT_proBNP": CanonicalMarker("пг/мл", {"NT_proBNP": 1, "nt_probnp_pg_ml": 1}),
    # Омега-3 индекс (HS-Omega-3 Index, Harris-von Schacht) — % EPA+DHA от жирных
    # кислот мембраны эритроцитов. Безразмерных алиасов нет — только %.
    "omega3_index": CanonicalMarker("%", {"omega3_index": 1, "omega_3_index": 1, "omega3_index_pct": 1}),
}


# Конверсия US (conventional, g/dL · mg/dL · µg/dL) → каноническая (метрическая)
# единица, по КАНОНИЧЕСКОМУ ключу. Применяется на чтении к записям, помеченным
# unit_system="US" (KB-поле "units": "US (mg/dl)"). Маркеры, отсутствующие здесь,
# считаются единично-идентичными US↔метрика (ферменты Ед/л, проценты, нг/мл=мкг/л).
# Множители — стандартные клинические (источник: молекулярная масса аналита):
#   albumin/total_protein: g/dL → г/л          ×10
#   glucose:    mg/dL → ммоль/л   ÷18.0156   (MW 180.16)
#   creatinine: mg/dL → мкмоль/л  ×88.42     (MW 113.12)
#   uric_acid:  mg/dL → мкмоль/л  ×59.48     (MW 168.11)
#   calcium:    mg/dL → ммоль/л   ×0.2495    (MW 40.08)
#   iron:       µg/dL → мкмоль/л  ×0.1791    (MW 55.845)
#   bilirubin_total: mg/dL → мкмоль/л ×17.104 (MW 584.66)
#   cholesterol_total/HDL/LDL: mg/dL → ммоль/л ÷38.67
#   triglycerides: mg/dL → ммоль/л ÷88.57
US_TO_METRIC: dict[str, float] = {
    "albumin_g_l": 10.0,
    "total_protein": 10.0,
    "glucose": 1 / 18.0156,
    "creatinine": 88.42,
    "uric_acid": 59.48,
    "calcium": 0.2495,
    "iron": 0.1791,
    "bilirubin_total": 17.104,
    "cholesterol_total": 1 / 38.67,
    "HDL": 1 / 38.67,
    "LDL": 1 / 38.67,
    "triglycerides": 1 / 88.57,
    "Hb": 10.0,  # гемоглобин g/dL → г/л
    "MCHC": 10.0,  # g/dL → г/л
}

# Правдоподобный диапазон СЫРОГО значения в US-единицах (мг/дл, г/дл, мкг/дл) по
# каноническому ключу. На US-записи множитель US_TO_METRIC применяется, только если сырое
# значение попало в диапазон; иначе оно уже метрическое и не трогается. Нужно для смешанных
# записей (ИНВИТРО: Hb в г/дл, остальная биохимия в метрике). Границы выбраны так, чтобы
# US- и метрические диапазоны не пересекались; тем самым guard идемпотентен.
# Не включены (диапазоны пересекаются, надёжно не различить → прежнее поведение «×множитель»):
#   iron: µg/dL 10–500 vs мкмоль/л 3–60;  bilirubin_total: mg/dL 0.1–30 vs мкмоль/л 3–500.
_US_RAW_RANGE: dict[str, tuple[float, float]] = {
    "albumin_g_l": (1.0, 10.0),  # г/дл 1–7 vs г/л 20–60
    "total_protein": (2.0, 15.0),  # г/дл 3–12 vs г/л 40–100
    "glucose": (30.0, 1500.0),  # мг/дл 30–1000 vs ммоль/л 1.5–55
    "creatinine": (0.1, 15.0),  # мг/дл 0.1–15 vs мкмоль/л 20–1500
    "uric_acid": (0.5, 25.0),  # мг/дл 0.5–20 vs мкмоль/л 100–1000
    "calcium": (4.0, 20.0),  # мг/дл 4–15 vs ммоль/л 1.5–3.5
    "cholesterol_total": (30.0, 800.0),  # мг/дл 70–500 vs ммоль/л 2–15
    "HDL": (10.0, 300.0),  # мг/дл 15–150 vs ммоль/л 0.4–4
    "LDL": (15.0, 600.0),  # мг/дл 20–400 vs ммоль/л 0.5–10
    "triglycerides": (25.0, 5000.0),  # мг/дл 25–2000 vs ммоль/л 0.3–20
    "Hb": (1.0, 30.0),  # г/дл 5–25 vs г/л 50–250
    "MCHC": (20.0, 60.0),  # г/дл 25–40 vs г/л 250–400
}

# Read-time защита от US-панелей, НЕ помеченных _unit_system="US" (напр. maccabi:
# единицы заданы инлайновыми _ref-диапазонами вместо поля "units", поэтому импорт US
# не задетектил). Для маркеров, чья g/dL-величина физиологически несовместима с
# канонической единицей «г/л», значение ниже порога почти наверняка в g/dL → домножаем.
# Порог с большим зазором от реального метрического диапазона (Hb ~130-170, MCHC ~320-360 г/л),
# так что легитимную метрику не трогаем, а на уже сконвертированной US-величине (155) guard
# не срабатывает повторно (идемпотентен относительно US_TO_METRIC).
# {canon_key: (порог_ниже_которого_считаем_gdl, множитель)}
_GDL_MAGNITUDE_GUARD: dict[str, tuple[float, float]] = {
    "Hb": (30.0, 10.0),
    "MCHC": (60.0, 10.0),
}

# Обратный guard: значение ВЫШЕ порога физиологически несовместимо с канонической
# единицей и почти наверняка в мг/дл. Ca ионизированный: ммоль/л ≈ 1.0–1.5, мг/дл ≈ 4–5.6 —
# диапазоны не пересекаются. Признак US-панели для него НЕ используем: он ставится по
# гемоглобину, а ионизированный кальций часто печатают в ммоль/л и на US-панели (ревью #560).
# {canon_key: (порог_выше_которого_считаем_mgdl, множитель)}
_MGDL_MAGNITUDE_GUARD: dict[str, tuple[float, float]] = {
    "calcium_ionized": (3.0, 0.2495),
}

# Служебный ключ в values, несущий систему единиц записи (инжектится импортом
# биохимии из KB, см. scripts/import/kb_to_blood_tests.py). Не маркер.
UNIT_SYSTEM_KEY = "_unit_system"

# Суффикс поля единицы конкретного маркера в KB: {"hs_CRP": 0.11, "hs_CRP_unit": "mg/dl"}.
UNIT_FIELD_SUFFIX = "_unit"

# Явные единицы вида «масса/объём» и «моль/объём» с SI-приставками. Из них
# множитель к канонической единице выводится арифметически — без таблицы на
# каждый маркер. Межразмерная конверсия (мг/дл → ммоль/л) идёт через MOLAR_MASS;
# маркер без молярной массы в такой паре не конвертируется (значение не трогаем).
_MASS_PREFIX = {"g": 1.0, "mg": 1e-3, "µg": 1e-6, "ng": 1e-9, "pg": 1e-12}
_MOL_PREFIX = {"mol": 1.0, "mmol": 1e-3, "µmol": 1e-6, "nmol": 1e-9, "pmol": 1e-12}
_VOL_PREFIX = {"l": 1.0, "dl": 1e-1, "ml": 1e-3, "µl": 1e-6}

# Молярная масса (г/моль) — для перевода масса ↔ моль, когда явная единица и
# каноника разной размерности. Совпадает с источниками множителей US_TO_METRIC.
MOLAR_MASS: dict[str, float] = {
    "glucose": 180.16,
    "creatinine": 113.12,
    "uric_acid": 168.11,
    "calcium": 40.08,
    "calcium_ionized": 40.08,
    "iron": 55.845,
    "bilirubin_total": 584.66,
    "cholesterol_total": 386.65,
    "HDL": 386.65,
    "LDL": 386.65,
    "triglycerides": 885.7,
    "FT4": 776.87,  # нг/дл → пмоль/л ×12.87
    "FT3": 650.97,  # пг/мл → пмоль/л ×1.536
    "PTH_intact": 9425.0,  # пмоль/л → пг/мл ×9.425 (как алиас pth_pmol_l)
    "testosterone": 288.42,
}

# Кириллица → латиница (порядок важен: длинные префиксы раньше коротких).
_UNIT_TRANSLIT = (
    ("ммоль", "mmol"),
    ("мкмоль", "µmol"),
    ("нмоль", "nmol"),
    ("пмоль", "pmol"),
    ("моль", "mol"),
    ("мкг", "µg"),
    ("мг", "mg"),
    ("нг", "ng"),
    ("пг", "pg"),
    ("г", "g"),
    ("дл", "dl"),
    ("мкл", "µl"),
    ("мл", "ml"),
    ("л", "l"),
)


def parse_concentration_unit(unit: str) -> tuple[str, float] | None:
    """'mg/dl' → ('mass', 1e-2) — размерность и масштаб к г/л или моль/л.

    None, если единица не «масса|моль / объём» (Ед/л, %, 10^9/л, МЕ/мл и т.п.) —
    такие единицы не конвертируем и значение не трогаем.
    """
    u = unit.strip().lower().replace(" ", "").replace("μ", "µ")
    if u.count("/") != 1:
        return None
    for cyr, lat in _UNIT_TRANSLIT:
        u = u.replace(cyr, lat)
    num, den = u.split("/")
    # mkmol / mcg / umol → µ-приставка (лабораторная транслитерация)
    for pre in ("mk", "mc", "u"):
        if num.startswith(pre) and num[len(pre) :] in ("mol", "g"):
            num = "µ" + num[len(pre) :]
        if den == pre + "l":
            den = "µl"
    vol = _VOL_PREFIX.get(den)
    if vol is None:
        return None
    if num in _MASS_PREFIX:
        return "mass", _MASS_PREFIX[num] / vol
    if num in _MOL_PREFIX:
        return "molar", _MOL_PREFIX[num] / vol
    return None


def _explicit_unit_factor(canon_key: str, unit: str) -> float | None:
    """Множитель «значение в явной единице unit → каноническая единица маркера».

    None — единицу не распознали или не умеем конвертировать: вызывающий
    оставляет прежнее поведение (алиас-фактор + US_TO_METRIC).
    """
    raw = parse_concentration_unit(unit)
    canon = parse_concentration_unit(CANONICAL[canon_key].unit)
    if raw is None or canon is None:
        return None
    if raw[0] == canon[0]:
        return raw[1] / canon[1]
    mw = MOLAR_MASS.get(canon_key)
    if mw is None:
        return None
    if raw[0] == "mass":  # г/л → моль/л
        return raw[1] / mw / canon[1]
    return raw[1] * mw / canon[1]  # моль/л → г/л


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _canon_numeric(values: dict) -> dict[str, float]:
    """Сырые числовые значения по каноническим ключам (без конверсии единиц)."""
    out: dict[str, float] = {}
    for key, val in values.items():
        n = _num(val)
        hit = _REVERSE.get(key.lower()) if isinstance(key, str) else None
        if n is not None and hit is not None:
            out.setdefault(hit[0], n)
    return out


def looks_like_us_units(values: dict) -> bool:
    """US-панель без явного поля units: единицы заданы величиной маркеров-индикаторов.

    Одного Hb < 30 мало: ИНВИТРО печатает гемоглобин в г/дл, а остальную биохимию в
    метрике. Нужен Hb < 30 И второй US-признак: glucose > 30 (мг/дл), cholesterol_total
    или LDL > 30 (мг/дл), creatinine < 15 (мг/дл). Только Hb в г/дл → False; такой Hb
    конвертируется явной единицей (см. ``mark_gdl_units``).

    Покрывает maccabi-CBC с инлайновыми _ref-диапазонами (issue #295) и документы из
    /doc без поля units (issue #281). Вызывается на записи (импорт KB, /doc), чтобы
    проставить ``_unit_system="US"``; конверсию делает ``to_canonical`` на чтении.
    """
    c = _canon_numeric(values)
    hb = c.get("Hb")
    if hb is None or not 0 < hb < 30:
        return False
    if c.get("glucose", 0) > 30:
        return True
    if c.get("cholesterol_total", 0) > 30 or c.get("LDL", 0) > 30:
        return True
    creat = c.get("creatinine")
    return creat is not None and 0 < creat < 15


def mark_gdl_units(values: dict) -> dict:
    """Копия values с явными ``<ключ>_unit="g/dl"`` для Hb (< 30) и MCHC (< 60).

    Для записей, где только гемоглобин в г/дл, а прочее в метрике: to_canonical
    сконвертирует эти маркеры в г/л через явную единицу, не трогая остальные.
    Существующая явная единица не перезаписывается.
    """
    out = dict(values)
    limits = {"Hb": 30.0, "MCHC": 60.0}
    for key, val in values.items():
        n = _num(val)
        hit = _REVERSE.get(key.lower()) if isinstance(key, str) else None
        if n is None or hit is None or hit[0] not in limits:
            continue
        unit_key = key + UNIT_FIELD_SUFFIX
        if 0 < n < limits[hit[0]] and not out.get(unit_key):
            out[unit_key] = "g/dl"
    return out


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


def to_canonical(
    values: dict, *, passthrough_unmapped: bool = False, unit_system: str | None = None
) -> tuple[dict[str, float], list[str]]:
    """Сырые KB-values → {canonical_key: converted_value}.

    Возвращает (canon, warnings). Числовые значения конвертируются множителем;
    нечисловые пропускаются. Алиас, не найденный в реестре, либо отбрасывается
    с предупреждением, либо (passthrough_unmapped=True) пробрасывается как есть.
    passthrough_unmapped=True пробрасывает немаппленные ключи без warning.

    unit_system: система единиц записи ("US" → конверсия g/dL·mg/dL·µg/dL в
    метрику по US_TO_METRIC). Если None — берётся из values[UNIT_SYSTEM_KEY]
    (так признак доезжает из Postgres JSONB). Явный параметр важнее ключа.
    """
    if unit_system is None:
        carrier = values.get(UNIT_SYSTEM_KEY)
        unit_system = str(carrier) if carrier else None
    is_us = (unit_system or "").upper() == "US"

    canon: dict[str, float] = {}
    exact_source: dict[str, str] = {}  # canon_key → исходный alias, выигравший слот
    warnings: list[str] = []

    for raw_key, raw_val in values.items():
        if raw_key == UNIT_SYSTEM_KEY:
            continue  # служебный признак единиц, не маркер
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
        # Явная единица маркера (hs_CRP_unit="mg/dl") точнее и алиас-фактора, и
        # признака US-панели: если её удалось распознать — берём её множитель.
        unit = values.get(raw_key + UNIT_FIELD_SUFFIX)
        has_unit = isinstance(unit, str) and bool(unit.strip())
        if has_unit and CANONICAL[canon_key].unit == "%" and unit.strip() != "%":
            # Абсолютное число под %-ключом (lymphocytes=2.14, unit "10^9/L") — не доля.
            warnings.append(f"{canon_key}={raw_val} {unit}: единица не %, пропущено")
            continue
        unit_factor = _explicit_unit_factor(canon_key, unit) if has_unit else None
        if unit_factor is not None:
            new_val = raw_val * unit_factor
            if abs(unit_factor - 1.0) > 1e-9:
                warnings.append(f"{canon_key}={raw_val} {unit} → ×{unit_factor:g} ({CANONICAL[canon_key].unit})")
        else:
            new_val = raw_val * factor
            if is_us:
                rng = _US_RAW_RANGE.get(canon_key)
                # Диапазон задан → конвертируем только правдоподобное US-значение;
                # вне диапазона оно уже метрическое (смешанная запись ИНВИТРО).
                if rng is None or rng[0] <= new_val <= rng[1]:
                    new_val *= US_TO_METRIC.get(canon_key, 1.0)
        high_guard = _MGDL_MAGNITUDE_GUARD.get(canon_key)
        if high_guard is not None and new_val > high_guard[0]:
            new_val *= high_guard[1]
            warnings.append(f"{canon_key}={raw_val} похоже на мг/дл (> {high_guard[0]:g}) → ×{high_guard[1]:g}")
        guard = _GDL_MAGNITUDE_GUARD.get(canon_key)
        if guard is not None and 0 < new_val < guard[0]:
            new_val *= guard[1]
            warnings.append(f"{canon_key}={raw_val} похоже на g/dL (< {guard[0]:g} г/л) → ×{guard[1]:g}")
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
