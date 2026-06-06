#!/usr/bin/env python3
"""
Backfill second user (user_id from env ANDREY_UID) Apple Health data
into PostgreSQL: activity_log, weights, blood_pressure_logs.

Data source: knowledge_base.json from GDrive (pre-parsed by scripts/parse_apple_health.py).
Run: python3 scripts/backfill_andrey_apple_health.py
"""

import json
import os
import sys
import subprocess
from pathlib import Path
from datetime import date, datetime

TOOL_RESULT_FILE = (
    Path.home() / ".claude/projects"
    "/-Users-alexlyskovsky-Library-CloudStorage-GoogleDrive-lyskovsky-gmail-com"
    "----------Projects-Vibe-coding-HealthVault-engine"
    "/8137eb5b-1989-4bdc-a295-3c6c232c85ef"
    "/tool-results/mcp-google_workspace-get_drive_file_content-1777931935520.txt"
)

SERVER = "root@116.203.213.137"
SSH_OPTS = ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10"]
ANDREY_UID = int(os.getenv("ANDREY_UID", "0"))
if not ANDREY_UID:
    sys.exit("Set ANDREY_UID env var (telegram_id) before running this backfill.")

# ── Load KB ─────────────────────────────────────────────────────────────────
print("Loading knowledge_base.json …")
raw = json.loads(TOOL_RESULT_FILE.read_text())
kb = json.loads(raw["result"].split("--- CONTENT ---\n", 1)[1])
ah = kb["apple_health"]


# ── Helpers ──────────────────────────────────────────────────────────────────
def q(v):
    """Quote value for SQL — None → NULL, str → 'str', number → number."""
    if v is None:
        return "NULL"
    if isinstance(v, str):
        return f"'{v.replace(chr(39), chr(39) * 2)}'"
    return str(v)


sql_lines = []

# ══════════════════════════════════════════════════════════════════
# 1. activity_log
# ══════════════════════════════════════════════════════════════════
print("Building activity_log inserts …")

activity = ah.get("activity_recent_60_days", [])  # [{date, steps, distance_km, ...}]
sleep = {r["night_of"]: r for r in ah.get("sleep_recent_60_nights", [])}
hr_daily = ah.get("summary_by_metric", {}).get("hr", {}).get("daily_means_last_30", {})
hrv_daily = ah.get("summary_by_metric", {}).get("hrv_sdnn", {}).get("daily_means_last_30", {})
rhr_daily = ah.get("summary_by_metric", {}).get("rhr", {}).get("daily_means_last_30", {})

for rec in activity:
    d = rec["date"]
    steps = rec.get("steps")
    dist = rec.get("distance_km")
    active_cal = rec.get("active_kcal")
    basal_cal = rec.get("basal_kcal")
    total_cal = round(active_cal + basal_cal, 1) if active_cal is not None and basal_cal is not None else None
    # Sleep: match by night_of date
    sl = sleep.get(d, {})
    sleep_hours = round(sl.get("asleep_total_min", 0) / 60, 2) if sl.get("asleep_total_min") else None

    # HR / HRV / RHR
    hr_avg = round(hr_daily[d]) if d in hr_daily else None
    hrv = round(hrv_daily[d]) if d in hrv_daily else None

    raw_data = {}
    if sl:
        raw_data["sleep"] = {
            "core_min": sl.get("core_min"),
            "rem_min": sl.get("rem_min"),
            "deep_min": sl.get("deep_min"),
            "awake_min": sl.get("awake_min"),
            "in_bed_min": sl.get("in_bed_min"),
        }
    if rec.get("stairs"):
        raw_data["stairs"] = rec["stairs"]
    if rec.get("exercise_min"):
        raw_data["exercise_min"] = rec["exercise_min"]
    if rec.get("stand_min"):
        raw_data["stand_min"] = rec["stand_min"]
    if d in rhr_daily:
        raw_data["rhr"] = round(rhr_daily[d])

    raw_json = q(json.dumps(raw_data, ensure_ascii=False)) if raw_data else "NULL"

    sql_lines.append(
        f"INSERT INTO activity_log "
        f"(user_id, date, steps, distance_km, active_calories, total_calories, bmr_calories, "
        f"sleep_hours, heart_rate_avg, hrv, source, raw_data) VALUES "
        f"({ANDREY_UID}, '{d}', {q(int(steps) if steps else None)}, {q(dist)}, "
        f"{q(active_cal)}, {q(total_cal)}, {q(basal_cal)}, "
        f"{q(sleep_hours)}, {q(hr_avg)}, {q(hrv)}, 'apple_health', {raw_json}) "
        f"ON CONFLICT (user_id, date) DO UPDATE SET "
        f"steps=EXCLUDED.steps, distance_km=EXCLUDED.distance_km, "
        f"active_calories=EXCLUDED.active_calories, total_calories=EXCLUDED.total_calories, "
        f"bmr_calories=EXCLUDED.bmr_calories, sleep_hours=EXCLUDED.sleep_hours, "
        f"heart_rate_avg=EXCLUDED.heart_rate_avg, hrv=EXCLUDED.hrv, "
        f"raw_data=EXCLUDED.raw_data, source=EXCLUDED.source;"
    )

print(f"  → {len(activity)} activity_log rows")

# ══════════════════════════════════════════════════════════════════
# 2. weights
# ══════════════════════════════════════════════════════════════════
print("Building weights inserts …")
weight_daily = ah.get("summary_by_metric", {}).get("weight_kg", {}).get("daily_means_last_30", {})

for d_str, w_kg in weight_daily.items():
    ts = f"{d_str}T08:00:00+03:00"
    sql_lines.append(
        f"INSERT INTO weights (user_id, measured_at, weight, source) VALUES "
        f"({ANDREY_UID}, '{ts}', {q(round(w_kg, 1))}, 'apple_health') "
        f"ON CONFLICT (user_id, measured_at) DO NOTHING;"
    )

print(f"  → {len(weight_daily)} weight rows")

# ══════════════════════════════════════════════════════════════════
# 3. blood_pressure_logs
# ══════════════════════════════════════════════════════════════════
print("Building blood_pressure_logs inserts …")

# Check if blood_pressure_logs table exists first — if not, skip
bp_pairs = ah.get("blood_pressure_pairs", [])
bp_inserts = []
seen_bp = set()
for bp in bp_pairs:
    key = (bp["date"], bp.get("time", ""))
    if key in seen_bp:
        continue
    seen_bp.add(key)
    ts = f"{bp['date']}T{bp.get('time', '12:00:00')}+03:00"
    bp_inserts.append(
        f"INSERT INTO blood_pressure_logs (user_id, measured_at, systolic, diastolic, source) VALUES "
        f"({ANDREY_UID}, '{ts}', {bp['systolic']}, {bp['diastolic']}, 'apple_health') "
        f"ON CONFLICT DO NOTHING;"
    )
sql_lines.extend(bp_inserts)
print(f"  → {len(bp_inserts)} blood_pressure_logs rows")

# ══════════════════════════════════════════════════════════════════
# Execute via SSH
# ══════════════════════════════════════════════════════════════════
full_sql = "\n".join(sql_lines)
total = len(sql_lines)
print(f"\nTotal SQL statements: {total}")
print("Connecting to server …")

cmd = [
    "ssh",
    *SSH_OPTS,
    SERVER,
    "docker exec -i healthvault_postgres psql -U healthvault -d healthvault",
]

result = subprocess.run(cmd, input=full_sql, capture_output=True, text=True, timeout=60)

if result.returncode != 0:
    print("STDERR:", result.stderr[:2000])
    sys.exit(1)

# Count successes
ok = result.stdout.count("INSERT 0 1") + result.stdout.count("UPDATE 1")
skip = result.stdout.count("INSERT 0 0")
err_lines = [l for l in result.stdout.splitlines() if "ERROR" in l or "error" in l.lower()]

print("\n✅ Done!")
print(f"   Inserted/updated: {ok}")
print(f"   Skipped (already exists): {skip}")
if err_lines:
    print(f"   Errors: {len(err_lines)}")
    for e in err_lines[:5]:
        print(f"     {e}")
else:
    print("   Errors: 0")

print("\nVerification query:")
verify_cmd = [
    "ssh",
    *SSH_OPTS,
    SERVER,
    f"docker exec healthvault_postgres psql -U healthvault -d healthvault -c "
    f'"SELECT MIN(date), MAX(date), COUNT(*) as days, '
    f"SUM(steps) as total_steps, AVG(sleep_hours)::numeric(4,2) as avg_sleep "
    f'FROM activity_log WHERE user_id = {ANDREY_UID};"',
]
r2 = subprocess.run(verify_cmd, capture_output=True, text=True, timeout=30)
print(r2.stdout)
