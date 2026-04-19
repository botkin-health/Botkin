#!/usr/bin/env python3
"""Генерация плоских файлов Apple Health в формате, ожидаемом /sync и /dashboard."""

import xml.etree.ElementTree as ET
import json
from pathlib import Path
from collections import defaultdict
from statistics import mean
from datetime import datetime

XML = Path("/tmp/apple_health/apple_health_export/экспорт.xml")
BASE = (
    Path.home()
    / "Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/Projects/Vibe coding/HealthVault-engine"
)

# бэкап старых файлов
import shutil

ts = datetime.now().strftime("%Y%m%d_%H%M%S")
for f in BASE.glob("data/apple_health_*.json"):
    shutil.copy(f, str(f) + f".bak_{ts}")

bp_sys = []  # list of (start_date, start_time, value)
bp_dia = []
steps_daily = defaultdict(int)
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
        steps_daily[date] += v
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

# 2. Steps daily
steps_list = [{"date": d, "steps": int(s)} for d, s in sorted(steps_daily.items())]
out_steps = {
    "steps_by_day": steps_list,
    "source": "Apple Health XML export",
    "generated_at": datetime.now().isoformat(),
}
(BASE / "data/apple_health_steps_daily.json").write_text(json.dumps(out_steps, ensure_ascii=False, indent=2))

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
for name, data_list, last_key in [
    ("blood_pressure", bp_pairs, "date"),
    ("steps_daily", steps_list, "date"),
    ("gait", gait_list, "date"),
    ("heart_rate", hr_list, "date"),
    ("weight_daily", w_list, "date"),
]:
    if data_list:
        print(f"  apple_health_{name:18s}: {len(data_list):,} recs, last = {data_list[-1][last_key]}")
