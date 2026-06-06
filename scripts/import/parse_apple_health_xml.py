#!/usr/bin/env python3
"""Генерация плоских файлов Apple Health в формате, ожидаемом /sync и /dashboard."""

import defusedxml.ElementTree as ET
import json
from pathlib import Path
from collections import defaultdict
from statistics import mean
from datetime import datetime

XML = Path("/tmp/apple_health/apple_health_export/экспорт.xml")
BASE = Path.home() / "Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/Projects/Vibe coding/Botkin"

# бэкап старых файлов
import shutil

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
for f in BASE.glob("data/apple_health_*.json"):
    shutil.copy(f, str(f) + f".bak_{ts}")

bp_sys = []  # list of (start_date, start_time, value)
bp_dia = []
# Шаги: храним РАЗБИВКУ ПО ИСТОЧНИКАМ за день, чтобы потом выбрать один primary,
# а не суммировать дубли (iPhone + Watch + Garmin Connect + HealthSync etc.)
# steps_by_source[date][sourceName] = sum_of_values
steps_by_source = defaultdict(lambda: defaultdict(float))
gait_daily = defaultdict(lambda: {"speed": [], "step_len": [], "ds": [], "asym": []})
hr_daily = defaultdict(list)
weight_daily = defaultdict(list)

print("Парсинг...")
n = 0
for event, elem in ET.iterparse(str(XML), events=("end",)):
    if elem.tag != "Record":
        elem.clear()
        continue
    n += 1
    rtype = elem.get("type")
    start = elem.get("startDate", "")
    val = elem.get("value")
    if not start or val is None:
        elem.clear()
        continue
    date = start[:10]
    time = start[11:19]
    try:
        v = float(val)
    except ValueError:
        elem.clear()
        continue

    if rtype == "HKQuantityTypeIdentifierBloodPressureSystolic":
        bp_sys.append((date, time, v))
    elif rtype == "HKQuantityTypeIdentifierBloodPressureDiastolic":
        bp_dia.append((date, time, v))
    elif rtype == "HKQuantityTypeIdentifierStepCount":
        # Сохраняем sourceName, чтобы не задваивать одни и те же шаги от разных устройств.
        # Выбор primary-источника происходит ниже, после полного прохода XML.
        src = elem.get("sourceName") or "unknown"
        steps_by_source[date][src] += v
    elif rtype == "HKQuantityTypeIdentifierWalkingSpeed":
        gait_daily[date]["speed"].append(v)  # km/h
    elif rtype == "HKQuantityTypeIdentifierWalkingStepLength":
        gait_daily[date]["step_len"].append(v)  # cm
    elif rtype == "HKQuantityTypeIdentifierWalkingDoubleSupportPercentage":
        gait_daily[date]["ds"].append(v * 100)  # value stored as 0-1, convert to %
    elif rtype == "HKQuantityTypeIdentifierWalkingAsymmetryPercentage":
        gait_daily[date]["asym"].append(v * 100)
    elif rtype == "HKQuantityTypeIdentifierHeartRate":
        hr_daily[date].append(v)
    elif rtype == "HKQuantityTypeIdentifierRestingHeartRate":
        hr_daily[date].append(v)
    elif rtype == "HKQuantityTypeIdentifierBodyMass":
        weight_daily[date].append(v)

    elem.clear()

print(f"Записей прочитано: {n:,}")

# === Объединяем BP: пара по времени (одна запись давления = систола + диастола в близкое время) ===
bp_pairs = []
dia_map = defaultdict(list)
for d, t, v in bp_dia:
    dia_map[d].append((t, v))
for d, t, v in sorted(bp_sys):
    matches = dia_map.get(d, [])
    if matches:
        best = min(
            matches,
            key=lambda x: abs(
                (
                    datetime.fromisoformat(f"1970-01-01T{x[0]}") - datetime.fromisoformat(f"1970-01-01T{t}")
                ).total_seconds()
            ),
        )
        bp_pairs.append({"date": d, "time": t, "systolic": int(v), "diastolic": int(best[1])})

bp_pairs.sort(key=lambda x: (x["date"], x["time"]))

# === Сохраняем файлы ===

# 1. Blood pressure
out_bp = {"measurements": bp_pairs, "source": "Apple Health XML export", "generated_at": datetime.now().isoformat()}
(BASE / "data/apple_health_blood_pressure.json").write_text(json.dumps(out_bp, ensure_ascii=False, indent=2))

# 2. Steps daily — выбираем ОДИН primary-источник за день по приоритету,
# чтобы не задваивать шаги (Apple Health KIT часто хранит одно действие
# одновременно от iPhone, Apple Watch, Garmin Connect, HealthSync etc.)
#
# Приоритет: Garmin (часы на руке весь день, наиболее точно для нас)
#         → Apple Watch
#         → iPhone
#         → fallback: максимум из доступных источников.
#
# Если в будущем будет нужна история iPhone-only (например, для периода до 2018,
# когда Garmin Connect ещё не писал в Apple Health), достаточно поменять приоритет.

PRIORITY_PATTERNS = [
    # (имя в выводе, подстрока в sourceName, регистр игнорируется)
    ("garmin", ("garmin", "connect")),
    ("watch", ("apple watch", "watch")),
    ("iphone", ("iphone",)),
]


def pick_primary_steps(sources: dict) -> tuple[int, str]:
    """Возвращает (steps, source_label) выбранного источника за день."""
    for label, patterns in PRIORITY_PATTERNS:
        for src_name, val in sources.items():
            sn_lower = src_name.lower()
            if any(p in sn_lower for p in patterns):
                return int(val), f"{label}:{src_name}"
    # fallback: максимум из всех источников
    if not sources:
        return 0, "none"
    best_name = max(sources, key=lambda k: sources[k])
    return int(sources[best_name]), f"fallback:{best_name}"


steps_list = []
steps_by_source_out = []  # для дебага и аудита
for d in sorted(steps_by_source.keys()):
    sources = dict(steps_by_source[d])
    steps, picked = pick_primary_steps(sources)
    steps_list.append({"date": d, "steps": steps, "primary_source": picked})
    steps_by_source_out.append(
        {
            "date": d,
            "primary": picked,
            "primary_steps": steps,
            "all_sources": {k: int(v) for k, v in sources.items()},
        }
    )

out_steps = {
    "steps_by_day": steps_list,
    "source": "Apple Health XML export (primary-source dedup)",
    "priority": [label for label, _ in PRIORITY_PATTERNS] + ["fallback-max"],
    "generated_at": datetime.now().isoformat(),
}
(BASE / "data/apple_health_steps_daily.json").write_text(json.dumps(out_steps, ensure_ascii=False, indent=2))

# Также сохраняем сырую разбивку по источникам — для дебага и проверки логики дедупликации.
out_steps_by_src = {
    "by_day": steps_by_source_out,
    "source": "Apple Health XML export (raw per-source breakdown)",
    "generated_at": datetime.now().isoformat(),
}
(BASE / "data/apple_health_steps_by_source.json").write_text(json.dumps(out_steps_by_src, ensure_ascii=False, indent=2))

# 3. Gait
gait_list = []
for d in sorted(gait_daily.keys()):
    g = gait_daily[d]
    gait_list.append(
        {
            "date": d,
            "speed_km_h": round(mean(g["speed"]), 2) if g["speed"] else None,
            "step_length_cm": round(mean(g["step_len"]), 1) if g["step_len"] else None,
            "double_support_pct": round(mean(g["ds"]), 2) if g["ds"] else None,
            "asymmetry_pct": round(mean(g["asym"]), 2) if g["asym"] else None,
        }
    )
out_gait = {"gait_by_day": gait_list, "source": "Apple Health XML export", "generated_at": datetime.now().isoformat()}
(BASE / "data/apple_health_gait.json").write_text(json.dumps(out_gait, ensure_ascii=False, indent=2))

# 4. Heart rate daily (min/max/avg for each day)
hr_list = []
for d in sorted(hr_daily.keys()):
    vs = hr_daily[d]
    hr_list.append(
        {
            "date": d,
            "avg": round(mean(vs), 1),
            "min": int(min(vs)),
            "max": int(max(vs)),
            "n": len(vs),
        }
    )
out_hr = {"measurements": hr_list, "source": "Apple Health XML export", "generated_at": datetime.now().isoformat()}
(BASE / "data/apple_health_heart_rate.json").write_text(json.dumps(out_hr, ensure_ascii=False, indent=2))

# 5. Weight daily
w_list = []
for d in sorted(weight_daily.keys()):
    vs = weight_daily[d]
    w_list.append({"date": d, "kg": round(mean(vs), 2), "n": len(vs)})
out_w = {"daily_averages": w_list, "source": "Apple Health XML export", "generated_at": datetime.now().isoformat()}
(BASE / "data/apple_health_weight_daily.json").write_text(json.dumps(out_w, ensure_ascii=False, indent=2))

# Также сохраняем "сырые" веса — последовательный список замеров (для совместимости)
w_seq = []
for d in sorted(weight_daily.keys()):
    for v in weight_daily[d]:
        w_seq.append({"date": d, "kg": round(v, 2)})
out_wseq = {"measurements": w_seq, "source": "Apple Health XML export", "generated_at": datetime.now().isoformat()}
(BASE / "data/apple_health_weight.json").write_text(json.dumps(out_wseq, ensure_ascii=False, indent=2))

print("\n=== Готово ===")
all_ok = True
for name, data_list, last_key in [
    ("blood_pressure", bp_pairs, "date"),
    ("steps_daily", steps_list, "date"),
    ("gait", gait_list, "date"),
    ("heart_rate", hr_list, "date"),
    ("weight_daily", w_list, "date"),
]:
    if data_list:
        print(f"  apple_health_{name:18s}: {len(data_list):,} recs, last = {data_list[-1][last_key]}")
    else:
        all_ok = False

# Уборка: zip из ~/Downloads и распакованная папка /tmp/apple_health.
# Удаляем только если все пять датасетов успешно записаны.
if all_ok:
    print("\n=== Уборка ===")
    downloads = Path.home() / "Downloads"
    for name in ("экспорт.zip", "export.zip"):
        zf = downloads / name
        if zf.exists():
            size_mb = zf.stat().st_size / 1024 / 1024
            zf.unlink()
            print(f"  удалён {zf} ({size_mb:.1f} МБ)")
    tmp_dir = Path("/tmp/apple_health")
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
        print(f"  удалён {tmp_dir}")
else:
    print("\n⚠️  Часть датасетов пуста — оставляю zip и /tmp/apple_health для разбора")
