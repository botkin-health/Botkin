#!/usr/bin/env python3
"""
Парсинг PDF-анализов Александра с извлечением лабораторных значений через GPT-4o.

Для каждой KB-записи с PDF-файлом без поля `values`:
  1. Извлекает текст из PDF через PyMuPDF
  2. Отправляет текст в GPT-4o → получает структурированный JSON
  3. Обновляет knowledge_base.json

Запуск:
  python parse_lab_pdfs.py               # парсит всё что нет
  python parse_lab_pdfs.py --dry-run     # только показывает что будет парсить
  python parse_lab_pdfs.py --file blood_2022-12-28_fdoctor_general.pdf  # один файл
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF
import requests

# Пути
ENGINE = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ENGINE))
from config import get_settings

HEALTH_DIR = (
    Path.home()
    / "Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/HealthVault/Александр Лысковский — Здоровье"
)
KB_PATH = HEALTH_DIR / "knowledge_base.json"

SECTIONS = [
    "blood_tests",
    "urine_tests",
    "hormones",
    "vitamins",
    "genetics",
    "covid_tests",
    "ultrasound",
    "medical_records",
    "sports_tests",
    "sleepcycle",
]

# Секции где не нужно парсить lab-значения (протоколы, генетика)
SKIP_SECTIONS = {"genetics", "sleepcycle"}

# COVID PCR — только результат (positive/negative), нет смысла парсить числа
COVID_SKIP_SUBTYPES = {"pcr", "antibodies"}

EXTRACTION_PROMPT = """You are a medical lab report parser. Extract ALL laboratory parameters from the text below.

Return ONLY valid JSON with this flat structure:
{
  "PARAM_KEY": value_as_number,
  "PARAM_KEY_unit": "unit_string",
  "PARAM_KEY_ref": "reference_range_string",
  ...
}

Rules:
- Use standardized English key names (e.g. WBC, RBC, Hb, Ht, MCV, MCH, MCHC, PLT, ESR, ALT, AST, GGT, ALP, bilirubin_total, bilirubin_direct, creatinine, urea, glucose, HbA1c, cholesterol_total, HDL, LDL, triglycerides, atherogenic_index, ferritin, iron, transferrin, TIBC, CRP, hs_CRP, fibrinogen, prothrombin_time, APTT, INR, thrombin_time, antithrombin3, D_dimer, TSH, T3_free, T4_free, anti_TPO, anti_Tg, testosterone, LH, FSH, prolactin, insulin, cortisol, estradiol, progesterone, DHEA_S, vitamin_D, vitamin_B12, vitamin_B9, vitamin_K, homocysteine, zinc, magnesium, calcium_ionized, protein_total, albumin, uric_acid, phosphorus, potassium, sodium, chloride, neutrophils_seg, neutrophils_band, lymphocytes, monocytes, eosinophils, basophils, lipoprotein_a, ApoA1, ApoB, etc.)
- For every numeric parameter include:
  - "KEY": number (the result value)
  - "KEY_unit": "string" (measurement unit, e.g. "g/l", "mmol/l", "thous/mkl", "%", "pg/ml", "IU/ml")
  - "KEY_ref": "string" (reference range as printed, e.g. "4.50-11.00", "<5.0", ">1.2", optional if not present)
- If a value has a flag like "↑", "H", "HIGH", "↓", "L", "LOW" — add "KEY_flag": "H" or "L"
- Skip non-numeric parameters (text comments, methodology notes)
- Skip header info (patient name, doctor, dates — those are already in the KB)
- COVID PCR: if result is "Not detected" / "Не обнаружено" → {"pcr_result": "negative"}, if "Detected" → {"pcr_result": "positive"}
- For antibodies: extract titer or index values if numeric
- For ultrasound/X-ray: return {} (empty — these are descriptive, not lab values)

The lab text to parse:
"""


def extract_pdf_text(pdf_path: Path) -> str:
    """Извлекает текст из PDF через PyMuPDF."""
    try:
        doc = fitz.open(str(pdf_path))
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        return text.strip()
    except Exception as e:
        return f"ERROR: {e}"


def call_gpt4o(text: str, api_key: str) -> dict | None:
    """Отправляет текст в GPT-4o и возвращает JSON со значениями."""
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": EXTRACTION_PROMPT + text}],
        "max_tokens": 1500,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }

    for attempt in range(3):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=30)
            if r.status_code == 429:
                time.sleep(2 ** (attempt + 1))
                continue
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            return json.loads(content)
        except Exception as e:
            if attempt == 2:
                print(f"    ❌ GPT-4o error: {e}")
                return None
            time.sleep(1)
    return None


def get_items_needing_parse(kb: dict, single_file: str = None) -> list[tuple]:
    """Возвращает список (section, item_idx, item) для парсинга."""
    result = []
    for section in SECTIONS:
        if section in SKIP_SECTIONS:
            continue
        for idx, item in enumerate(kb.get(section, [])):
            if not isinstance(item, dict):
                continue
            fname = item.get("filename", "")
            if not fname.endswith(".pdf"):
                continue
            if item.get("values"):
                continue  # уже распарсен
            if single_file and fname != single_file:
                continue
            # Пропускаем COVID PCR/antibodies — там нечего числового
            if section == "covid_tests":
                subtype = item.get("filename", "").split("_")[-1].replace(".pdf", "")
                if subtype in COVID_SKIP_SUBTYPES:
                    continue
            # Проверяем, что файл существует
            fpath = HEALTH_DIR / fname
            if not fpath.exists():
                print(f"  ⚠️  Файл не найден: {fname}")
                continue
            result.append((section, idx, item))
    return result


def main():
    parser = argparse.ArgumentParser(description="Парсинг PDF лаб-анализов → KB values")
    parser.add_argument("--dry-run", action="store_true", help="Только показать что будет парсить")
    parser.add_argument("--file", type=str, default=None, help="Парсить только один файл")
    args = parser.parse_args()

    settings = get_settings()
    api_key = settings.openai_api_key
    if not api_key:
        print("❌ OPENAI_API_KEY не найден в .env")
        sys.exit(1)

    # Загружаем KB
    kb = json.loads(KB_PATH.read_text())

    # Бэкап
    backup = KB_PATH.with_suffix(".json.bak_parse_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    backup.write_text(json.dumps(kb, ensure_ascii=False, indent=2))
    print(f"📦 Бэкап: {backup.name}")

    # Список на парсинг
    items = get_items_needing_parse(kb, args.file)
    print(f"\n📋 Нужно распарсить: {len(items)} PDF файлов")

    if args.dry_run:
        for section, idx, item in items:
            print(f"  [{section}] {item['filename']} ({item.get('date', '?')})")
        return

    print()
    parsed_ok = 0
    parsed_empty = 0
    parsed_err = 0

    for i, (section, idx, item) in enumerate(items):
        fname = item["filename"]
        fpath = HEALTH_DIR / fname
        print(f"[{i + 1}/{len(items)}] {fname}")

        # Извлекаем текст
        text = extract_pdf_text(fpath)
        if text.startswith("ERROR"):
            print(f"    ❌ PDF read error: {text}")
            parsed_err += 1
            continue

        if len(text) < 50:
            print(f"    ⚠️  Слишком короткий текст ({len(text)} chars) — пропускаем")
            parsed_err += 1
            continue

        print(f"    📄 Текст: {len(text)} chars → GPT-4o-mini...")

        # Отправляем в GPT
        values = call_gpt4o(text, api_key)

        if values is None:
            print("    ❌ GPT вернул None")
            parsed_err += 1
            continue

        if not values:
            print("    ℹ️  Пустой результат (нет числовых параметров) — ставим {}")
            kb[section][idx]["values"] = {}
            parsed_empty += 1
        else:
            print(
                f"    ✅ Извлечено параметров: {sum(1 for k in values if not k.endswith(('_unit', '_ref', '_flag')))}"
            )
            kb[section][idx]["values"] = values
            parsed_ok += 1

        # Сохраняем после каждого файла (чтобы не терять прогресс)
        KB_PATH.write_text(json.dumps(kb, ensure_ascii=False, indent=2))

        # Небольшая пауза чтобы не перегружать API
        if i < len(items) - 1:
            time.sleep(0.3)

    print(f"\n{'=' * 50}")
    print(f"✅ Распарсено с данными:    {parsed_ok}")
    print(f"   Пустой результат:        {parsed_empty}")
    print(f"   Ошибки:                  {parsed_err}")
    print(
        f"   Пропущено (covid pcr):   {len([x for x in get_items_needing_parse(json.loads(KB_PATH.read_text())) if x[0] == 'covid_tests']) if False else '—'}"
    )
    print(f"\n📁 KB обновлён: {KB_PATH.name}")


if __name__ == "__main__":
    main()
