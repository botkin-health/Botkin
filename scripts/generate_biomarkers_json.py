#!/usr/bin/env python3
"""
Генерирует telegram-bot/biomarkers_895655.json из knowledge_base.json Александра.

Запускать локально после добавления новых анализов в knowledge_base.json,
затем деплоить: scripts/deploy_biomarkers.sh

Usage:
    python3 scripts/generate_biomarkers_json.py
    python3 scripts/generate_biomarkers_json.py --deploy   # + автодеплой на сервер
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

KB_PATH = Path.home() / (
    "Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/"
    "Мой диск/HealthVault/Александр Лысковский — Здоровье/knowledge_base.json"
)
OUT_PATH = Path(__file__).resolve().parent.parent / "telegram-bot" / "biomarkers_895655.json"

SERVER = "root@116.203.213.137"
SSHPASS = "/opt/homebrew/bin/sshpass"
SSH_PASS = os.environ.get("SSH_PASS", "SERVER_PASSWORD_REDACTED")


def build_biomarkers(kb: dict) -> dict:
    tests = sorted(kb.get("blood_tests", []), key=lambda x: x.get("date", ""), reverse=True)

    seen: dict[str, dict] = {}
    for t in tests:
        date = t.get("date", "")
        vals = t.get("values") or t.get("results") or {}
        for k, v in vals.items():
            if k not in seen and isinstance(v, (int, float)):
                seen[k] = {"value": v, "date": date}

    bio: dict = {}

    def add(bio_key: str, kb_keys: list[str]) -> None:
        for k in kb_keys:
            if k in seen:
                bio[bio_key] = seen[k]
                return

    # Core metabolic
    add("HbA1c", ["HbA1c"])
    add("glucose", ["glucose"])
    add("insulin", ["insulin"])
    add("HOMA_index", ["HOMA_index"])

    # Lipids
    add("cholesterol_total", ["cholesterol_total"])
    add("HDL", ["HDL"])
    add("LDL", ["LDL"])
    add("triglycerides", ["triglycerides"])
    add("ApoB", ["ApoB"])
    add("ApoA1", ["ApoA1"])
    add("lipoprotein_a", ["lipoprotein_a"])

    # Liver / inflammation
    add("ALT", ["ALT", "alt"])
    add("AST", ["AST", "ast"])
    add("GGT", ["GGT", "ggt"])
    add("ALP", ["ALP", "alkaline_phosphatase"])
    add("bilirubin_total", ["bilirubin_total"])
    # hs_CRP stored in mg/L (0.11 mg/L = excellent, consistent with ESR=5)
    add("hs_CRP", ["hs_CRP"])

    # Hormones
    add("testosterone", ["testosterone"])
    add("TSH", ["TSH", "tsh"])
    add("FT3", ["FT3"])
    add("FT4", ["FT4"])
    add("cortisol", ["cortisol"])
    add("SHBG", ["SHBG"])
    add("prolactin", ["prolactin"])
    add("LH", ["LH"])
    add("FSH", ["FSH"])

    # Vitamins / nutrients
    add("vitamin_D", ["vitamin_D"])
    add("ferritin", ["ferritin"])
    add("folic_acid", ["folic_acid", "folate"])
    add("magnesium", ["magnesium", "Mg"])
    add("zinc", ["zinc", "Zn"])
    add("iron", ["iron", "Fe"])

    # Kidneys
    add("creatinine", ["creatinine"])
    add("egfr", ["egfr_ckd_epi"])
    add("uric_acid", ["uric_acid"])
    add("urea", ["urea"])

    # CBC (for PhenoAge)
    add("WBC", ["WBC"])
    add("RBC", ["RBC"])
    add("Hb", ["Hb"])
    add("lymphocytes", ["lymphocytes"])
    add("MCV", ["MCV"])
    add("RDW_CV", ["RDW_CV", "RDW"])
    add("PLT", ["PLT"])
    add("ESR", ["ESR"])

    # albumin in g/L; dashboard_generator.py converts /10 → g/dL for PhenoAge
    add("albumin_g_l", ["albumin_g_l"])

    # Extra
    add("homocysteine", ["homocysteine"])
    add("PSA_total", ["PSA_total", "psa"])
    add("CRP", ["CRP"])
    add("atherogenic_index", ["atherogenic_index"])
    add("FAI", ["FAI"])
    add("calcium", ["Ca", "calcium"])
    add("potassium", ["K", "potassium"])
    add("sodium", ["Na", "sodium"])

    return bio


def deploy(path: Path) -> None:
    remote_tmp = "/tmp/biomarkers_895655.json"
    print(f"📤 Uploading to {SERVER}...")
    subprocess.run(
        [SSHPASS, "-p", SSH_PASS, "scp", "-o", "StrictHostKeyChecking=no", str(path), f"{SERVER}:{remote_tmp}"],
        check=True,
    )
    print("🐳 Copying into Docker container...")
    subprocess.run(
        [
            SSHPASS,
            "-p",
            SSH_PASS,
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            SERVER,
            f"docker cp {remote_tmp} healthvault_bot:/app/biomarkers_895655.json && "
            f"docker cp {remote_tmp} healthvault_bot:/app/telegram-bot/biomarkers_895655.json && "
            f"echo 'Deployed OK'",
        ],
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deploy", action="store_true", help="Deploy to server after generating")
    args = parser.parse_args()

    print(f"📖 Reading {KB_PATH}")
    kb = json.loads(KB_PATH.read_text())

    bio = build_biomarkers(kb)
    print(f"✅ Built {len(bio)} biomarkers")

    OUT_PATH.write_text(json.dumps(bio, indent=2, ensure_ascii=False) + "\n")
    print(f"💾 Saved to {OUT_PATH}")

    if args.deploy:
        deploy(OUT_PATH)
        print("🚀 Done! Biomarkers updated on server.")
    else:
        print("\nRun with --deploy to push to server, or run scripts/deploy_biomarkers.sh")


if __name__ == "__main__":
    main()
