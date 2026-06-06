#!/usr/bin/env python3
"""Parse a 23andMe v3/v4/v5 raw genome file into a structured genetics record
and append it to the person's knowledge_base.json.

Usage:
    python3 parse_23andme_to_kb.py "<имя пользователя>"
    python3 parse_23andme_to_kb.py "<имя пользователя>" --dry-run

The script auto-detects the genome_*.txt file in the person's HealthVault folder.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

FAMILY_HEALTH = Path.home() / "Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/HealthVault"


# Curated SNP catalog. Each entry is a system → list of SNPs to look up + an
# interpretation function that takes the raw genotype as 23andMe stores it
# (forward strand of the reference build) and returns a phenotype + summary.
#
# Reference: SNPedia.com, Promethease, Attia "Outlive", peer-reviewed sources.


def interpret_apoe(genotypes: dict[str, str]) -> dict:
    """APOE genotype is determined by combination of rs429358 and rs7412."""
    rs429358 = genotypes.get("rs429358", "")
    rs7412 = genotypes.get("rs7412", "")

    # Allele table (Liu 2013 Nat Rev Neurol):
    #   rs429358-T + rs7412-T = ε1 (very rare)
    #   rs429358-T + rs7412-C = ε3
    #   rs429358-C + rs7412-T = ε2
    #   rs429358-C + rs7412-C = ε4
    def alleles(g429, g7412):
        out = []
        for a429, a7412 in [(g429[0], g7412[0]), (g429[1], g7412[1])]:
            if a429 == "T" and a7412 == "C":
                out.append("ε3")
            elif a429 == "C" and a7412 == "T":
                out.append("ε2")
            elif a429 == "C" and a7412 == "C":
                out.append("ε4")
            elif a429 == "T" and a7412 == "T":
                out.append("ε1")
        return out

    if len(rs429358) != 2 or len(rs7412) != 2:
        return {"phenotype": "unknown", "summary": "Один из SNP отсутствует"}
    pair = sorted(alleles(rs429358, rs7412))
    pheno = "/".join(pair)
    risk_map = {
        "ε2/ε2": ("Низкий риск Альцгеймера, но повышен риск дисбеталипопротеинемии типа III", "low_alz"),
        "ε2/ε3": ("Сниженный риск Альцгеймера", "low_alz"),
        "ε2/ε4": ("Смешанный — ε2 защищает, ε4 повышает", "mixed"),
        "ε3/ε3": ("Самый частый генотип. Наследственный риск Альцгеймера на популяционном уровне", "neutral"),
        "ε3/ε4": ("Повышен риск Альцгеймера ×2-3", "elevated"),
        "ε4/ε4": ("Сильно повышен риск Альцгеймера ×8-12", "high"),
    }
    summary, level = risk_map.get(pheno, ("Редкий генотип, требуется индивидуальная интерпретация", "unknown"))
    return {"phenotype": pheno, "summary": summary, "risk_level": level}


def interpret_mthfr(genotypes: dict[str, str]) -> dict:
    """MTHFR rs1801133 (C677T) and rs1801131 (A1298C).

    23andMe stores rs1801133 on minus strand: G=C(ref), A=T(mutant).
    23andMe stores rs1801131 on minus strand: T=A(ref), G=C(mutant).
    """
    g677 = genotypes.get("rs1801133", "")  # C677T
    g1298 = genotypes.get("rs1801131", "")  # A1298C
    # Convert minus-strand genotypes to standard nomenclature
    map677 = {"G": "C", "A": "T"}
    map1298 = {"T": "A", "G": "C"}
    pheno677 = "".join(sorted(map677.get(a, "?") for a in g677))
    pheno1298 = "".join(sorted(map1298.get(a, "?") for a in g1298))
    activity = {
        ("CC", "AA"): (100, "Норма по обоим аллелям"),
        ("CT", "AA"): (60, "Гетерозигота C677T → ~40% сниженная активность фермента"),
        ("TT", "AA"): (30, "Гомозигота C677T → ~70% сниженная активность"),
        ("CC", "AC"): (80, "Гетерозигота A1298C → лёгкое снижение"),
        ("CC", "CC"): (60, "Гомозигота A1298C → 40% сниженная активность"),
        ("CT", "AC"): (40, "Compound гетерозигота → 60% сниженная активность"),
    }
    pct, summary = activity.get((pheno677, pheno1298), (None, f"Комбинация C677T={pheno677}, A1298C={pheno1298}"))
    actions = []
    if pct is not None and pct < 100:
        actions = [
            "Брать B9 в форме метилфолат (5-MTHF / Quatrefolic), не обычную фолиевую кислоту",
            "Брать B12 в форме метилкобаламин, не цианокобаламин",
            "Контролировать гомоцистеин 1-2 раза в год",
        ]
    return {
        "C677T": pheno677,
        "A1298C": pheno1298,
        "estimated_activity_pct": pct,
        "summary": summary,
        "actions": actions,
    }


def interpret_simple(_snp_id: str, genotype: str, rules: dict) -> dict:
    """Generic interpreter: look up the genotype in a rules dict."""
    info = rules.get(genotype, {"summary": f"Генотип {genotype} — нет курированной интерпретации", "level": "unknown"})
    return {"genotype": genotype, **info}


SNP_CATALOG = {
    "neurology": {
        "APOE": {
            "snps": ["rs429358", "rs7412"],
            "interpreter": "apoe",
            "description": "Аполипопротеин E — главный наследственный фактор риска болезни Альцгеймера",
        },
    },
    "metabolism": {
        "MTHFR": {
            "snps": ["rs1801133", "rs1801131"],
            "interpreter": "mthfr",
            "description": "Метилентетрагидрофолатредуктаза — фолатный цикл, метилирование, гомоцистеин",
        },
        "TCF7L2": {
            "snps": ["rs7903146"],
            "rules": {
                "CC": {"summary": "Норма, базовый риск диабета 2 типа", "level": "neutral"},
                "CT": {"summary": "Гетерозигота, риск диабета 2 ×1.4", "level": "elevated"},
                "TT": {"summary": "Гомозигота, риск диабета 2 ×2.0", "level": "high"},
            },
            "description": "Главный SNP риска диабета 2 типа (Grant 2006)",
            "actions_if_risk": [
                "CGM-протокол актуален (FreeStyle Libre или аналог)",
                "Внимание к гликемии натощак, HbA1c, инсулину, HOMA-IR",
                "Снижение быстрых углеводов, контроль талии",
            ],
        },
        "FTO": {
            "snps": ["rs9939609"],
            "rules": {
                "TT": {"summary": "Норма, базовая склонность к весу", "level": "neutral"},
                "AT": {"summary": "Гетерозигота, склонность к набору веса +0.5 кг в среднем", "level": "elevated"},
                "AA": {"summary": "Гомозигота, склонность к набору +1-1.5 кг, повышенный аппетит", "level": "high"},
            },
            "description": "FTO — один из главных генов аппетита и набора веса",
            "actions_if_risk": [
                "Эффект FTO полностью аннулируется при ≥1 ч физической активности в день (Kilpeläinen 2011)",
                "Особенно важен контроль порций и плотности пищи",
            ],
        },
        "HFE_C282Y": {
            "snps": ["rs1800562"],
            "rules": {
                "GG": {
                    "summary": "Норма, нет мутации C282Y → наследственный гемохроматоз исключён по этому варианту",
                    "level": "neutral",
                },
                "AG": {"summary": "Гетерозигота C282Y, носитель", "level": "carrier"},
                "AA": {
                    "summary": "Гомозигота C282Y → высокий риск наследственного гемохроматоза, регулярный контроль ферритина и насыщения трансферрина",
                    "level": "high",
                },
            },
            "description": "Главная мутация наследственного гемохроматоза",
        },
        "HFE_H63D": {
            "snps": ["rs1799945"],
            "rules": {
                "CC": {"summary": "Норма, нет мутации H63D", "level": "neutral"},
                "CG": {"summary": "Гетерозигота H63D, лёгкое повышение риска накопления железа", "level": "carrier"},
                "GG": {"summary": "Гомозигота H63D, умеренный риск накопления железа", "level": "elevated"},
            },
            "description": "Второй вариант гемохроматоза, легче C282Y",
        },
    },
    "lipids": {
        "Lp_a_rs10455872": {
            "snps": ["rs10455872"],
            "rules": {
                "AA": {"summary": "Низкий генетический Lp(a) — благоприятно для ССЗ", "level": "low"},
                "AG": {"summary": "Гетерозигота, умеренно повышенный Lp(a)", "level": "elevated"},
                "GG": {"summary": "Гомозигота, высокий Lp(a) → повышенный риск ИМ и АС", "level": "high"},
            },
            "description": "Lp(a) генетика — пожизненный фактор риска ССЗ (Clarke 2009 NEJM)",
        },
        "Lp_a_rs3798220": {
            "snps": ["rs3798220"],
            "rules": {
                "TT": {"summary": "Норма, низкий риск через этот SNP", "level": "low"},
                "CT": {"summary": "Гетерозигота, повышенный Lp(a) и ССЗ-риск ×2", "level": "elevated"},
                "CC": {"summary": "Гомозигота, риск ИМ ×3-4", "level": "high"},
            },
            "description": "Второй ключевой Lp(a) SNP",
        },
        "APOC3": {
            "snps": ["rs5128"],
            "rules": {
                "CC": {"summary": "Норма по APOC3", "level": "neutral"},
                "CG": {"summary": "Гетерозигота, чуть повышенные триглицериды", "level": "elevated"},
                "GG": {"summary": "Гомозигота, повышенные TG и риск панкреатита", "level": "high"},
            },
            "description": "APOC3 — регулятор триглицеридов",
        },
        "PCSK9": {
            "snps": ["rs11591147"],
            "rules": {
                "GG": {"summary": "Норма (T-аллель loss-of-function редок в Европе)", "level": "neutral"},
                "GT": {
                    "summary": "Носитель T loss-of-function — пожизненно сниженный LDL и риск ССЗ",
                    "level": "favorable",
                },
                "TT": {
                    "summary": "Гомозигота loss-of-function — экстремально низкий LDL пожизненно",
                    "level": "very_favorable",
                },
            },
            "description": "PCSK9 loss-of-function = генетический эффект статинов",
        },
    },
    "vitamin_d": {
        "VDR_FokI": {
            "snps": ["rs2228570"],
            "rules": {
                "GG": {"summary": "FF — наиболее активный VDR, лучшее усвоение витамина D", "level": "favorable"},
                "AG": {"summary": "Ff — средний VDR", "level": "neutral"},
                "AA": {
                    "summary": "ff — менее активный VDR, может потребоваться доза витамина D выше стандартной",
                    "level": "elevated_need",
                },
            },
            "description": "Рецептор витамина D (FokI полиморфизм)",
        },
        "VDR_BsmI": {
            "snps": ["rs1544410"],
            "rules": {
                "CC": {"summary": "BB — связан с лучшим усвоением кальция", "level": "favorable"},
                "CT": {"summary": "Bb — средний", "level": "neutral"},
                "TT": {"summary": "bb — менее эффективное усвоение кальция", "level": "neutral"},
            },
            "description": "VDR BsmI",
        },
    },
    "omega_3": {
        "FADS1": {
            "snps": ["rs174537"],
            "rules": {
                "GG": {
                    "summary": "Эффективная конверсия ALA→EPA→DHA, растительные омега-3 работают",
                    "level": "favorable",
                },
                "GT": {
                    "summary": "Средняя конверсия (~50% от GG), растительные омега-3 работают хуже",
                    "level": "elevated_need",
                },
                "TT": {
                    "summary": "Низкая конверсия (~25% от GG), нужны рыбные источники EPA/DHA напрямую",
                    "level": "high_need",
                },
            },
            "description": "FADS1 — десатураза, конвертирует растительную ALA в EPA/DHA",
            "actions_if_risk": [
                "Брать омега-3 в форме рыбьего жира EPA+DHA, не льняного масла",
                "Доза EPA+DHA 1-2 г/день",
            ],
        },
        "FADS2": {
            "snps": ["rs1535"],
            "rules": {
                "AA": {"summary": "Эффективная конверсия", "level": "favorable"},
                "AG": {"summary": "Средняя конверсия", "level": "elevated_need"},
                "GG": {"summary": "Сниженная конверсия", "level": "high_need"},
            },
            "description": "FADS2 — вторая десатураза омега-3 цепи",
        },
    },
    "caffeine_alcohol": {
        "CYP1A2": {
            "snps": ["rs762551"],
            "rules": {
                "AA": {
                    "summary": "Fast metabolizer кофеина — кофе ОК, нет повышенного ССЗ-риска",
                    "level": "favorable",
                },
                "AC": {"summary": "Intermediate metabolizer", "level": "neutral"},
                "CC": {"summary": "Slow metabolizer — >2 чашек/день повышают риск ИМ ×4", "level": "elevated"},
            },
            "description": "CYP1A2 — главный фермент метаболизма кофеина (Cornelis 2006 JAMA)",
        },
        "ALDH2": {
            "snps": ["rs671"],
            "rules": {
                "GG": {"summary": "Норма, без 'asian flush', алкоголь метаболизируется обычно", "level": "neutral"},
                "AG": {"summary": "Гетерозигота, частичный flush, риск рака пищевода при алкоголе ×6", "level": "high"},
                "AA": {"summary": "Гомозигота, сильный flush, любой алкоголь токсичен", "level": "very_high"},
            },
            "description": "ALDH2 — метаболизм ацетальдегида (важнее в азиатских популяциях)",
        },
    },
    "sport": {
        "ACTN3": {
            "snps": ["rs1815739"],
            "rules": {
                "CC": {
                    "summary": "RR — функциональный α-актинин-3, fast-twitch фенотип, лучше для силовых/спринта",
                    "level": "sprint",
                },
                "CT": {"summary": "RX — смешанный фенотип, универсальность", "level": "mixed"},
                "TT": {"summary": "XX — нет функционального актинина-3, endurance-фенотип", "level": "endurance"},
            },
            "description": "ACTN3 — sprint-vs-endurance мышечный фенотип",
        },
    },
    "neuropsych": {
        "COMT_Val158Met": {
            "snps": ["rs4680"],
            "rules": {
                "GG": {
                    "summary": "Val/Val 'Warrior' — быстрый метаболизм допамина, лучше под давлением, ищет новизну",
                    "level": "warrior",
                },
                "AG": {"summary": "Val/Met — смешанный, наиболее адаптивный", "level": "mixed"},
                "AA": {
                    "summary": "Met/Met 'Worrier' — медленный метаболизм допамина, лучше в рутине, выше тревожность",
                    "level": "worrier",
                },
            },
            "description": "COMT — метаболизм допамина в префронтальной коре, психотип Warrior/Worrier",
        },
        "BDNF_Val66Met": {
            "snps": ["rs6265"],
            "rules": {
                "CC": {"summary": "Val/Val — норма по нейропластичности и памяти", "level": "neutral"},
                "CT": {"summary": "Val/Met — слегка сниженная BDNF-секреция, но в пределах нормы", "level": "mild"},
                "TT": {
                    "summary": "Met/Met — заметно сниженная нейропластичность, может влиять на память и обучение",
                    "level": "elevated",
                },
            },
            "description": "BDNF — нейротрофический фактор, нейропластичность",
        },
    },
    "celiac": {
        "HLA_DQ2_5": {
            "snps": ["rs2187668"],
            "rules": {
                "CC": {"summary": "Нет HLA-DQ2.5 → целиакия маловероятна (но возможна через DQ8)", "level": "low"},
                "CT": {"summary": "Гетерозигота DQ2.5, повышенный риск целиакии", "level": "elevated"},
                "TT": {"summary": "Гомозигота DQ2.5, высокий риск целиакии", "level": "high"},
            },
            "description": "HLA-DQ2.5 — главный аллель риска целиакии",
        },
    },
    "pharmacogenomics": {
        "CYP2C19_2": {
            "snps": ["rs4244285"],
            "rules": {
                "GG": {"summary": "Норма (нет *2 loss-of-function)", "level": "neutral"},
                "AG": {"summary": "Носитель *2, intermediate metabolizer", "level": "intermediate"},
                "AA": {
                    "summary": "Гомозигота *2, poor metabolizer — клопидогрель не работает, омепразол накапливается",
                    "level": "poor",
                },
            },
            "description": "CYP2C19 *2 — главная LOF-аллель, важна для клопидогреля",
        },
        "CYP2C19_17": {
            "snps": ["rs12248560"],
            "rules": {
                "CC": {"summary": "Норма (нет *17 ultra-rapid)", "level": "neutral"},
                "CT": {"summary": "Носитель *17 — rapid metabolizer, лекарства быстро вымываются", "level": "rapid"},
                "TT": {"summary": "Гомозигота *17, ultra-rapid metabolizer", "level": "ultra_rapid"},
            },
            "description": "CYP2C19 *17 — gain-of-function, ускоряет метаболизм многих препаратов",
        },
    },
}


def parse_genome(genome_path: Path) -> dict[str, str]:
    """Stream the 23andMe txt file and return only the SNPs we care about."""
    wanted = set()
    for system in SNP_CATALOG.values():
        for snp_def in system.values():
            wanted.update(snp_def["snps"])

    found: dict[str, str] = {}
    with genome_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4:
                continue
            rsid = parts[0]
            if rsid in wanted:
                found[rsid] = parts[3]
                if len(found) == len(wanted):
                    break  # Early exit
    return found


def build_record(genome_path: Path, raw: dict[str, str]) -> dict:
    """Build the structured record for knowledge_base.json."""
    record = {
        "file": genome_path.name,
        "filename": genome_path.name,
        "date": "2016-06-28",  # parsed from filename suffix 20160628
        "year": 2016,
        "laboratory": "23andMe",
        "type": "genetics",
        "type_detail": "DNA chip (full raw)",
        "chip_version": "v4",
        "platform": "Illumina OmniExpress + custom (23andMe v4)",
        "snp_count": 610564,
        "raw_file": str(genome_path),
        "parsed_at": datetime.now().isoformat(timespec="seconds"),
        "key_findings": {},
    }

    # Try to parse date from filename — supports two patterns:
    #   genome_..._20160628212325.txt          (старый 23andMe download)
    #   genetics_2016-06-28_23andme_v4_raw.txt (наша нормализованная конвенция)
    import re

    stem = genome_path.stem
    iso_match = re.search(r"(\d{4})-(\d{2})-(\d{2})", stem)
    digits_match = re.search(r"(\d{8})\d*", stem)
    if iso_match:
        y, m, d = iso_match.groups()
        record["date"] = f"{y}-{m}-{d}"
        record["year"] = int(y)
    elif digits_match:
        ts = digits_match.group(1)
        record["date"] = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
        record["year"] = int(ts[:4])

    for system_name, snps in SNP_CATALOG.items():
        record["key_findings"][system_name] = {}
        for snp_name, snp_def in snps.items():
            rsids = snp_def["snps"]
            genotypes = {rid: raw.get(rid, "??") for rid in rsids}

            # Pick interpreter
            interp = snp_def.get("interpreter")
            if interp == "apoe":
                result = interpret_apoe(genotypes)
            elif interp == "mthfr":
                result = interpret_mthfr(genotypes)
            else:
                rules = snp_def.get("rules", {})
                rsid = rsids[0]
                gt = genotypes[rsid]
                result = interpret_simple(rsid, gt, rules)

            entry = {
                "description": snp_def["description"],
                "raw_genotypes": genotypes,
                **result,
            }
            actions_key = "actions_if_risk"
            if actions_key in snp_def and result.get("level") in ("elevated", "high", "elevated_need", "high_need"):
                entry["actions"] = snp_def[actions_key]
            record["key_findings"][system_name][snp_name] = entry

    return record


def merge_into_kb(kb_path: Path, record: dict, dry_run: bool = False) -> None:
    """Append (or replace) the genetics record in knowledge_base.json."""
    if not kb_path.exists():
        print(f"❌ knowledge_base.json не найден: {kb_path}")
        sys.exit(1)

    with kb_path.open("r", encoding="utf-8") as f:
        kb = json.load(f)

    if "genetics" not in kb:
        kb["genetics"] = []
    if not isinstance(kb["genetics"], list):
        print("❌ kb['genetics'] существует, но это не массив. Не трогаю — проверь вручную.")
        sys.exit(1)

    # Replace if same file already there, else append
    target_filename = record["filename"]
    replaced = False
    for i, entry in enumerate(kb["genetics"]):
        if entry.get("filename") == target_filename:
            kb["genetics"][i] = record
            replaced = True
            print(f"♻️  Запись для {target_filename} обновлена.")
            break
    if not replaced:
        kb["genetics"].append(record)
        print(f"➕ Запись для {target_filename} добавлена.")

    if dry_run:
        print("(--dry-run: knowledge_base.json не записан)")
        return

    backup = kb_path.with_suffix(".json.bak")
    backup.write_text(kb_path.read_text(encoding="utf-8"), encoding="utf-8")
    with kb_path.open("w", encoding="utf-8") as f:
        json.dump(kb, f, ensure_ascii=False, indent=2)
    print(f"✅ Записано: {kb_path}")
    print(f"   Бэкап:    {backup}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("person_folder", help='Имя папки в HealthVault, напр. "<имя пользователя>"')
    ap.add_argument("--dry-run", action="store_true", help="Не писать в kb, только показать результат")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    person_dir = FAMILY_HEALTH / args.person_folder
    if not person_dir.exists():
        print(f"❌ Папка не найдена: {person_dir}")
        sys.exit(1)

    # Search for raw 23andMe file by either old (genome_*) or new (genetics_*_23andme_*) pattern
    candidates = sorted(person_dir.glob("genetics_*_23andme_*.txt"))
    candidates += sorted(person_dir.glob("genome_*.txt"))
    if not candidates:
        print(
            "❌ В папке нет файла 23andMe (искал genetics_*_23andme_*.txt и genome_*.txt). Проверь, что zip распакован."
        )
        sys.exit(1)
    if len(candidates) > 1:
        print(f"⚠️  Найдено несколько кандидатов — беру первый: {candidates[0].name}")
        for c in candidates[1:]:
            print(f"     (пропущен: {c.name})")
    genome = candidates[0]
    print(f"📂 Парсинг: {genome.name} ({genome.stat().st_size / 1024 / 1024:.1f} МБ)")

    raw = parse_genome(genome)
    print(f"🧬 Извлечено {len(raw)} SNP из каталога")
    if args.verbose:
        for k, v in sorted(raw.items()):
            print(f"   {k} = {v}")

    record = build_record(genome, raw)
    print(
        f"📊 Систем: {len(record['key_findings'])}, SNP в систематизации: {sum(len(s) for s in record['key_findings'].values())}"
    )

    kb_path = person_dir / "knowledge_base.json"
    merge_into_kb(kb_path, record, dry_run=args.dry_run)

    if args.dry_run:
        print("\n=== DRY RUN OUTPUT ===")
        print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
