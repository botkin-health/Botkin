"""
HealthVault Share Dashboard Generator
Читает данные пользователя из PostgreSQL → вставляет JSON-payload в mc_template.html → возвращает HTML.
Дизайн шаблона не меняется — только данные.
"""

from __future__ import annotations

import json
import math
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.orm import Session

TEMPLATE_PATH = Path(__file__).parent / "mc_template.html"


# ── helpers ───────────────────────────────────────────────────────────────────


def _avg(d: dict) -> float:
    return round(sum(d.values()) / len(d), 1) if d else 0.0


def _rows(db: Session, sql: str, **params):
    return db.execute(text(sql), params).fetchall()


def _one(db: Session, sql: str, **params):
    row = db.execute(text(sql), params).fetchone()
    return row[0] if row else None


# ── sport block (HR-zones, polarized training analysis) ──────────────────────


def _build_sport_block(user_id: int) -> dict:
    """Анализ тренировок по канонам Seiler/Attia/Whoop.

    Источник: workouts_log_{user_id}.json (Garmin activities → parse_workouts.py).
    Считает:
      - 4 KPI: тренировок/нед, Z2 мин/нед, HIIT мин/нед, A:C load ratio
      - распределение по зонам за последние 4 недели (для polarized pyramid)
      - список тренировок с детектом неправильного тега «HIIT»
      - вердикт + рекомендации

    Каноны:
      - Polarized 80/20 (Seiler): 80% Z1+Z2, 5% Z3, 15-20% Z4+Z5
      - Z2 цель: 150 мин/нед (Attia, базовая аэробка)
      - Z4+Z5 цель: 16 мин/нед (4x4 норвежский протокол VO2max)
      - A:C ratio: 0.8-1.3 = sweet spot, >1.5 = риск травмы (Гарвард sports med)
    """
    from datetime import date, timedelta

    wk_path = Path(__file__).parent / f"workouts_log_{user_id}.json"
    if not wk_path.exists():
        return {"available": False}

    try:
        wd = json.loads(wk_path.read_text())
    except Exception:
        return {"available": False}

    workouts = wd.get("workouts", [])
    if not workouts:
        return {"available": False}

    today = date.today()

    def _to_date(s: str):
        try:
            y, m, d = s.split("-")
            return date(int(y), int(m), int(d))
        except Exception:
            return None

    # ── окна: 7 дней (acute), 28 дней (chronic), 30 дней (отображение) ───────
    w7 = [w for w in workouts if _to_date(w["date"]) and (today - _to_date(w["date"])).days <= 7]
    w28 = [w for w in workouts if _to_date(w["date"]) and (today - _to_date(w["date"])).days <= 28]
    w30 = [w for w in workouts if _to_date(w["date"]) and (today - _to_date(w["date"])).days <= 30]

    def _sum_zone(ws, zone_key):
        return round(sum(w.get("hr_zones", {}).get(zone_key, 0) for w in ws))

    def _sum_load(ws):
        return sum(w.get("training_load") or 0 for w in ws)

    # KPI: Z2 минут в неделю (среднее за 28 дней)
    z2_per_week = round(_sum_zone(w28, "z2_min") / 4) if w28 else 0
    # KPI: HIIT минут (Z4+Z5) в неделю
    hiit_per_week = round((_sum_zone(w28, "z4_min") + _sum_zone(w28, "z5_min")) / 4) if w28 else 0
    # KPI: тренировок в неделю (среднее за 28 дней)
    workouts_per_week = round(len(w28) / 4, 1) if w28 else 0
    # KPI: A:C ratio (acute load 7d / chronic avg load per 7d)
    acute_load = _sum_load(w7)
    chronic_load_per_7d = _sum_load(w28) / 4 if w28 else 0
    ac_ratio = round(acute_load / chronic_load_per_7d, 2) if chronic_load_per_7d > 0 else None

    # Status indicators for KPIs
    def _kpi_status(value, target, low_warn=0.5, high_warn=1.3):
        """Returns (color_code, hint). g=green, y=yellow, r=red."""
        if target == 0:
            return ("muted", "—")
        ratio = value / target
        if ratio >= 1.0:
            return ("g", "цель ✓")
        elif ratio >= low_warn:
            return ("y", f"{round(ratio * 100)}% от цели")
        else:
            return ("r", f"{round(ratio * 100)}% от цели · мало")

    z2_color, z2_hint = _kpi_status(z2_per_week, 150)
    hiit_color, hiit_hint = _kpi_status(hiit_per_week, 16)

    # Workouts/week status: 3-5 = green, 1-2 = yellow, 0 or 6+ = red
    if workouts_per_week >= 3 and workouts_per_week <= 5:
        wpw_color, wpw_hint = "g", "оптимально 3–5"
    elif workouts_per_week >= 2:
        wpw_color, wpw_hint = "y", "цель 3–5"
    elif workouts_per_week > 0:
        wpw_color, wpw_hint = "r", "слишком мало"
    else:
        wpw_color, wpw_hint = "r", "перерыв"

    # A:C ratio status
    if ac_ratio is None:
        ac_color, ac_hint = "muted", "нет данных"
    elif 0.8 <= ac_ratio <= 1.3:
        ac_color, ac_hint = "g", "sweet spot"
    elif ac_ratio < 0.8:
        ac_color, ac_hint = "y", "недогруз"
    elif ac_ratio <= 1.5:
        ac_color, ac_hint = "y", "перегруз"
    else:
        ac_color, ac_hint = "r", "риск травмы"

    # ── per-week buckets (last 4 weeks for polarized pyramid) ────────────────
    def _iso_monday(d_str: str) -> str:
        d = _to_date(d_str)
        if not d:
            return ""
        monday = d - timedelta(days=d.weekday())
        return monday.isoformat()

    weeks_dict: dict = {}
    for w in w30:
        wk = _iso_monday(w["date"])
        if not wk:
            continue
        b = weeks_dict.setdefault(
            wk,
            {"week": wk, "z1": 0, "z2": 0, "z3": 0, "z4": 0, "z5": 0, "n": 0, "load": 0, "mins": 0},
        )
        z = w.get("hr_zones", {})
        b["z1"] += z.get("z1_min", 0)
        b["z2"] += z.get("z2_min", 0)
        b["z3"] += z.get("z3_min", 0)
        b["z4"] += z.get("z4_min", 0)
        b["z5"] += z.get("z5_min", 0)
        b["n"] += 1
        b["load"] += w.get("training_load") or 0
        b["mins"] += w.get("duration_min") or 0

    weeks = sorted(weeks_dict.values(), key=lambda x: x["week"])
    # round
    for b in weeks:
        for k in ("z1", "z2", "z3", "z4", "z5", "mins"):
            b[k] = round(b[k])
        total = b["z1"] + b["z2"] + b["z3"] + b["z4"] + b["z5"] or 1
        b["easy_pct"] = round((b["z1"] + b["z2"]) / total * 100)
        b["mid_pct"] = round(b["z3"] / total * 100)
        b["hard_pct"] = round((b["z4"] + b["z5"]) / total * 100)
        b["total_min"] = total

    # ── polarized verdict ────────────────────────────────────────────────────
    total30_z = {z: _sum_zone(w30, f"{z}_min") for z in ("z1", "z2", "z3", "z4", "z5")}
    total30_sum = sum(total30_z.values()) or 1
    easy_pct = (total30_z["z1"] + total30_z["z2"]) / total30_sum * 100
    mid_pct = total30_z["z3"] / total30_sum * 100
    hard_pct = (total30_z["z4"] + total30_z["z5"]) / total30_sum * 100

    if easy_pct >= 75 and hard_pct >= 10 and mid_pct < 15:
        verdict = "polarized"
        verdict_label = "✅ Polarized 80/20 — оптимально"
    elif mid_pct >= 25:
        verdict = "z3_trap"
        verdict_label = "⚠ Z3-trap — слишком много темповой"
    elif hard_pct < 5:
        verdict = "all_easy"
        verdict_label = "⚠ Всё в базе — нет острых сессий для VO2max"
    elif easy_pct < 60:
        verdict = "too_hard"
        verdict_label = "⚠ Слишком много high-intensity — мало базы"
    else:
        verdict = "pyramidal"
        verdict_label = "≈ Pyramidal — рабочий вариант, но polarized эффективнее"

    # ── workout list (last 14 days) ──────────────────────────────────────────
    cutoff14 = (today - timedelta(days=14)).isoformat()
    recent14 = [w for w in workouts if w.get("date", "") >= cutoff14]
    recent14.sort(key=lambda x: x["date"])

    workout_list = []
    misnamed_count = 0
    for w in recent14:
        z = w.get("hr_zones", {})
        total = sum(z.values()) or 1
        item = {
            "date": w.get("date"),
            "type": w.get("type"),
            "type_label": w.get("type_label", w.get("type", "")),
            "duration_min": round(w.get("duration_min") or 0),
            "avg_hr": round(w.get("avg_hr") or 0),
            "z1_pct": round(z.get("z1_min", 0) / total * 100),
            "z2_pct": round(z.get("z2_min", 0) / total * 100),
            "z3_pct": round(z.get("z3_min", 0) / total * 100),
            "z4_pct": round(z.get("z4_min", 0) / total * 100),
            "z5_pct": round(z.get("z5_min", 0) / total * 100),
            "load": w.get("training_load") or 0,
            "is_misnamed": w.get("is_misnamed", False),
            "suggested_type": w.get("suggested_type"),
            "high_zone_pct": w.get("high_zone_pct", 0),
        }
        if item["is_misnamed"]:
            misnamed_count += 1
        workout_list.append(item)

    # ── recommendations ──────────────────────────────────────────────────────
    recs = []
    if z2_per_week < 75:
        deficit = 150 - z2_per_week
        recs.append(
            f"Добавь Z2: сейчас {z2_per_week} мин/нед, цель 150. "
            f"2 пробежки/велик по 30–45 мин на пульсе 110–120 закроют дефицит {deficit} мин."
        )
    if hiit_per_week < 8:
        recs.append(
            f"Добавь настоящий HIIT: Z4+Z5 сейчас {hiit_per_week} мин/нед, цель 16. "
            "Норвежский протокол: 4×4 мин на 90% maxHR (≥155 bpm) с 3 мин восстановления."
        )
    if misnamed_count > 0:
        recs.append(
            f"Переназови {misnamed_count} «HIIT» в Garmin → Strength Training. "
            "Это силовые/функционалка, не интервалы — Garmin корректнее посчитает Body Battery и Training Status."
        )
    if ac_ratio is not None and ac_ratio < 0.8:
        recs.append("Acute load низкий — можно безопасно увеличить объём на 15–20% эту неделю.")
    if ac_ratio is not None and ac_ratio > 1.3:
        recs.append("Acute load высокий — снизь интенсивность 1–2 дня для восстановления.")
    if not recs:
        recs.append("Тренировочный план сбалансирован. Держи ритм.")

    # ── what's working (positive observations) ───────────────────────────────
    works = []
    if workouts_per_week >= 2.5:
        works.append(f"Стабильный ритм: {workouts_per_week} тренировок/нед за последний месяц")
    # Detect well-tagged Z2 sessions (running/cycling with >70% in Z2)
    z2_quality = [
        w for w in w30 if w.get("type") in ("running", "cycling") and w.get("hr_zones", {}).get("z2_min", 0) > 0
    ]
    if z2_quality:
        # Check if these have >70% in Z2
        good_z2 = []
        for w in z2_quality:
            z = w.get("hr_zones", {})
            total = sum(z.values()) or 1
            if z.get("z2_min", 0) / total > 0.7:
                good_z2.append(w)
        if good_z2:
            works.append(
                f"Беговые/велик в правильной Z2: {len(good_z2)} сессий, средне {round(sum(w.get('duration_min', 0) for w in good_z2) / len(good_z2))} мин"
            )
    if not works:
        works.append("Нет данных для позитивных выводов — нужно больше тренировок")

    return {
        "available": True,
        "kpis": {
            "workouts_per_week": workouts_per_week,
            "workouts_per_week_color": wpw_color,
            "workouts_per_week_hint": wpw_hint,
            "z2_per_week": z2_per_week,
            "z2_target": 150,
            "z2_color": z2_color,
            "z2_hint": z2_hint,
            "hiit_per_week": hiit_per_week,
            "hiit_target": 16,
            "hiit_color": hiit_color,
            "hiit_hint": hiit_hint,
            "ac_ratio": ac_ratio,
            "ac_color": ac_color,
            "ac_hint": ac_hint,
            "acute_load": round(acute_load),
            "chronic_load_per_7d": round(chronic_load_per_7d),
        },
        "weeks": weeks,
        "polarized": {
            "easy_pct": round(easy_pct),
            "mid_pct": round(mid_pct),
            "hard_pct": round(hard_pct),
            "verdict": verdict,
            "verdict_label": verdict_label,
            "ideal": {"easy": 80, "mid": 5, "hard": 15},
            "total_min": round(total30_sum),
        },
        "workouts": workout_list,
        "misnamed_count": misnamed_count,
        "works": works,
        "recommendations": recs,
        "window_days": 30,
        "window_workouts": len(w30),
    }


# ── payload builder ───────────────────────────────────────────────────────────


def _build_payload(db: Session, user_id: int) -> dict:
    """Собирает данные пользователя из PostgreSQL в структуру, совместимую с mc_template.html."""
    from database.models import User, UserSettings

    user = db.query(User).filter_by(telegram_id=user_id).first()
    if not user:
        raise ValueError(f"User {user_id} not found")

    today = date.today()
    project_start = date(2026, 1, 6)
    registered = user.registered_at.date() if user.registered_at else project_start
    start = min(project_start, registered)  # берём всё с 06.01 или с регистрации

    settings = db.query(UserSettings).filter_by(user_id=user_id).first()
    target_weight = (settings.target_weight_kg if settings else None) or user.target_weight_kg
    target_date_val = settings.target_weight_date if settings else None
    target_date = target_date_val.isoformat() if target_date_val else None
    days_to_target = (target_date_val - today).days if target_date_val else None

    total_days = (today - start).days + 1
    dates = [(start + timedelta(days=i)).isoformat() for i in range(total_days)]

    # ── weight / fat / visceral ────────────────────────────────────────────────
    w_rows = _rows(
        db,
        """
        SELECT DATE(measured_at) as d, weight, body_fat, visceral_fat
        FROM weights
        WHERE user_id=:uid AND measured_at >= :s AND measured_at <= :e
        ORDER BY measured_at
        """,
        uid=user_id,
        s=datetime.combine(start, datetime.min.time()),
        e=datetime.combine(today, datetime.max.time()),
    )
    weight: dict[str, float] = {}
    fat: dict[str, float] = {}
    visceral: dict[str, float] = {}
    for row in w_rows:
        d = row.d.isoformat() if hasattr(row.d, "isoformat") else str(row.d)
        weight[d] = round(row.weight, 2)
        if row.body_fat:
            fat[d] = round(row.body_fat, 1)
        if row.visceral_fat:
            visceral[d] = round(row.visceral_fat, 1)

    stats_weight: dict = {}
    if weight:
        fd, ld = min(weight), max(weight)
        stats_weight = {
            "first": weight[fd],
            "first_date": fd,
            "last": weight[ld],
            "last_date": ld,
            "min": min(weight.values()),
            "max": max(weight.values()),
            "delta": round(weight[ld] - weight[fd], 2),
        }
    stats_fat: dict = {}
    if fat:
        fd, ld = min(fat), max(fat)
        stats_fat = {
            "first": fat[fd],
            "last": fat[ld],
            "delta": round(fat[ld] - fat[fd], 1),
        }

    # ── activity_log: sleep / stress / hrv / rhr / steps / body_battery ───────
    act_rows = _rows(
        db,
        """
        SELECT date, steps, sleep_hours, hrv, stress_level, heart_rate_avg,
               raw_data
        FROM activity_log
        WHERE user_id=:uid AND date >= :s AND date <= :e
        ORDER BY date
        """,
        uid=user_id,
        s=start,
        e=today,
    )
    sleep_h: dict[str, float] = {}
    stress: dict[str, int] = {}
    hrv: dict[str, int] = {}
    rhr: dict[str, int] = {}
    steps: dict[str, int] = {}
    body_battery: dict[str, int] = {}
    bp_sys: dict[str, int] = {}
    bp_dia: dict[str, int] = {}

    for row in act_rows:
        d = row.date.isoformat()
        if row.sleep_hours and row.sleep_hours > 0.5:
            sleep_h[d] = round(row.sleep_hours, 1)
        if row.stress_level:
            stress[d] = row.stress_level
        if row.hrv:
            hrv[d] = row.hrv
        if row.heart_rate_avg:
            rhr[d] = row.heart_rate_avg
        if row.steps:
            steps[d] = row.steps

        raw = row.raw_data or {}
        # Body Battery: Garmin daily-summary has these fields at top level of raw_data
        bb = raw.get("bodyBatteryHighestValue") or raw.get("bodyBatteryAtWakeTime") or raw.get("body_battery_max")
        if bb:
            body_battery[d] = int(bb)

        # NOTE: blood_pressure is read exclusively from blood_pressure_logs table below.

    # ── nutrition ──────────────────────────────────────────────────────────────
    nut_rows = _rows(
        db,
        """
        SELECT date, totals, items
        FROM nutrition_log
        WHERE user_id=:uid AND date >= :s AND date <= :e
        ORDER BY date
        """,
        uid=user_id,
        s=start,
        e=today,
    )
    kcal: dict[str, int] = {}
    prot: dict[str, float] = {}
    fat_g: dict[str, float] = {}
    carb: dict[str, float] = {}
    alco_days: list[str] = []

    # Substring-safe keywords (long enough to avoid false positives)
    _alco_kw_substr = [
        "виски",
        "шампан",
        "коньяк",
        "водк",
        "текил",
        "портвейн",
        "рислинг",
        "просекко",
        "аперол",
        "мартини",
        "ликёр",
        "ликер",
        "мерло",
        "каберне",
        "саперав",
        "мохито",
        "глинтвейн",
        "бренди",
        "негрон",
        "джин",  # "джин" safe — no common food false positives
        "wine",
        "whisky",
        "vodka",
        "champagne",
    ]
    # Short words requiring word-boundary matching to avoid false positives:
    # "ром"  → catches "сыром", "кальмаром", "гарниром", "сахаром" (Russian -ром ending)
    # "вин"  → catches "свинина", "винегрет" (not wine)
    # "пив"  → could catch non-alcohol words
    # Use \bром\w{0,3}\b → catches ром/рома/ромом/рому but NOT кальмаром/сыром
    _alco_kw_word_re = re.compile(
        r"\bром\w{0,3}\b"  # ром (rum) and its inflections — NOT сыром/кальмаром
        r"|\bвин[оаеыу]\b"  # вино/вина/вине/вины/вину — NOT свинина/винегрет
        r"|\bпив[оа]?\b"  # пиво/пива/пив
        r"|\bсидр\w{0,3}\b"  # сидр (cider)
        r"|\bbeer\b"
        r"|\bgin\b"
        r"|\brum\b"
    )

    for row in nut_rows:
        d = row.date.isoformat()
        totals = row.totals or {}
        k = int(totals.get("calories") or 0)
        p = float(totals.get("protein") or 0)
        fg = float(totals.get("fat") or 0)
        cr = float(totals.get("carbs") or totals.get("carbohydrates") or 0)
        if k > 0:
            kcal[d] = kcal.get(d, 0) + k
        if p > 0:
            prot[d] = round(prot.get(d, 0.0) + p, 1)
        if fg > 0:
            fat_g[d] = round(fat_g.get(d, 0.0) + fg, 1)
        if cr > 0:
            carb[d] = round(carb.get(d, 0.0) + cr, 1)

        items = row.items or []
        if isinstance(items, list):
            for item in items:
                name_lower = str(item.get("food", "")).lower()
                is_alco = any(kw in name_lower for kw in _alco_kw_substr) or bool(_alco_kw_word_re.search(name_lower))
                if is_alco:
                    if d not in alco_days:
                        alco_days.append(d)
                    break

    alco_days.sort()

    # ── supplements ───────────────────────────────────────────────────────────
    supp_rows = _rows(
        db,
        "SELECT DISTINCT date FROM supplements_log WHERE user_id=:uid AND date >= :s AND date <= :e",
        uid=user_id,
        s=start,
        e=today,
    )
    supp_days = sorted(r.date.isoformat() for r in supp_rows)

    # ── biomarkers: try to load from per-user JSON in container ───────────────
    biomarkers: dict = {}
    bio_path = Path(__file__).parent / f"biomarkers_{user_id}.json"
    if bio_path.exists():
        try:
            biomarkers = json.loads(bio_path.read_text())
        except Exception:
            pass

    # ── environmental (optional, empty if no file) ────────────────────────────
    co2: dict[str, int] = {}
    temp_home: dict[str, float] = {}
    env_path = Path(__file__).parent / f"env_data_{user_id}.json"
    if env_path.exists():
        try:
            env = json.loads(env_path.read_text())
            co2 = env.get("co2", {})
            temp_home = env.get("temp_home", {})
        except Exception:
            pass

    # ── blood pressure from dedicated table ──────────────────────────────────
    bp_rows = _rows(
        db,
        """
        SELECT DATE(measured_at)::text as d, systolic, diastolic
        FROM blood_pressure_logs
        WHERE user_id=:uid AND measured_at >= :s AND measured_at <= :e
        ORDER BY measured_at
        """,
        uid=user_id,
        s=datetime.combine(start, datetime.min.time()),
        e=datetime.combine(today, datetime.max.time()),
    )
    for row in bp_rows:
        # Take the last reading of each day (rows ordered by measured_at ASC,
        # so later readings overwrite earlier ones — same behaviour as before)
        if row.systolic:
            bp_sys[row.d] = row.systolic
        if row.diastolic:
            bp_dia[row.d] = row.diastolic

    # ── activities (workouts) ─────────────────────────────────────────────────
    wk_rows = _rows(
        db,
        """
        SELECT date::text as d, workout_type, duration_minutes, calories_burned, distance_km
        FROM workouts
        WHERE user_id=:uid AND date >= :s AND date <= :e
        ORDER BY date
        """,
        uid=user_id,
        s=start,
        e=today,
    )
    activities: list = []
    for row in wk_rows:
        activities.append(
            {
                "date": row.d,
                "type": row.workout_type or "other",
                "duration_min": row.duration_minutes or 0,
                "calories": row.calories_burned or 0,
                "distance_km": float(row.distance_km) if row.distance_km else None,
            }
        )

    # ── computed: averages / totals ───────────────────────────────────────────
    def _davg(d: dict, rnd: int = 0) -> float:
        if not d:
            return 0
        v = sum(d.values()) / len(d)
        return round(v, rnd) if rnd else round(v)

    # Activity breakdown by type (for workout card bars)
    _WORKOUT_LABELS = {
        "hiit": "HIIT",
        "yoga": "Йога",
        "running": "Бег",
        "walking": "Ходьба",
        "cycling": "Велосипед",
        "swimming": "Плавание",
        "strength": "Силовая",
        "cardio": "Кардио",
        "other": "Прочее",
    }
    # Only running/walking/cycling/swimming have meaningful distance
    _DISTANCE_TYPES = {"running", "walking", "cycling", "swimming"}
    _breakdown: dict = {}
    for a in activities:
        t = a["type"]
        if t not in _breakdown:
            _breakdown[t] = {"n": 0, "km": 0.0}
        _breakdown[t]["n"] += 1
        if t in _DISTANCE_TYPES and a.get("distance_km"):
            _breakdown[t]["km"] += a["distance_km"]
    activity_breakdown = sorted(
        [
            {
                "label": _WORKOUT_LABELS.get(t, t.capitalize()),
                "n": v["n"],
                "km": round(v["km"], 1) if v["km"] > 0 else 0,
            }
            for t, v in _breakdown.items()
        ],
        key=lambda x: -x["n"],
    )

    bp_sys_sorted = sorted(bp_sys.items())
    bp_last_str = f"{bp_sys_sorted[-1][1]}/{bp_dia.get(bp_sys_sorted[-1][0], '?')}" if bp_sys_sorted else "—"

    totals = {
        "kcal_avg": _davg(kcal),
        "prot_avg": _davg(prot, 1),
        "sleep_avg": _davg(sleep_h, 1),
        "stress_avg": _davg(stress),
        "hrv_avg": _davg(hrv),
        "rhr_avg": _davg(rhr),
        "steps_avg": _davg(steps),
        "bb_avg": _davg(body_battery),
        "co2_avg": _davg(co2),
        "temp_home_avg": _davg(temp_home, 1),
        "activities_total": len(activities),
        "activity_min": sum(a.get("duration_min", 0) for a in activities),
        "activity_km": round(
            sum((a.get("distance_km") or 0) for a in activities if a["type"] in _DISTANCE_TYPES),
            1,
        ),
        "activity_hours": round(sum(a.get("duration_min", 0) for a in activities) / 60),
        "activity_breakdown": activity_breakdown,
        "bp_last": bp_last_str,
        "alco_days_n": len(alco_days),
        "supp_days_n": len(supp_days),
        "kcal_days_n": len(kcal),
        "prot_target": 140,  # g/day — 56 kg lean mass × 2.5
        "prot_avg_7d": round(sum(v for _, v in sorted(prot.items())[-7:]) / min(7, max(len(prot), 1))) if prot else 0,
    }

    # ── biomarkers_latest: structured for biotable JS ─────────────────────────
    def bv(key):
        return (biomarkers.get(key) or {}).get("value")

    def bd(key):
        return (biomarkers.get(key) or {}).get("date", "—")

    biomarkers_latest = {
        "HbA1c": {"val": bv("HbA1c"), "date": bd("HbA1c"), "unit": "%", "ok": 5.7},
        "glucose": {"val": bv("glucose"), "date": bd("glucose"), "unit": "ммоль/л", "ok": 5.6},
        "cholesterol": {"val": bv("cholesterol_total"), "date": bd("cholesterol_total"), "unit": "ммоль/л", "ok": 5.2},
        "LDL": {"val": bv("LDL"), "date": bd("LDL"), "unit": "ммоль/л", "ok": 3.0},
        "HDL": {"val": bv("HDL"), "date": bd("HDL"), "unit": "ммоль/л", "ok": 1.2},
        "testosterone": {"val": bv("testosterone"), "date": bd("testosterone"), "unit": "нмоль/л", "ok": 12.1},
        "vitamin_D": {"val": bv("vitamin_D"), "date": bd("vitamin_D"), "unit": "нг/мл", "ok": 30},
        "ferritin": {"val": bv("ferritin"), "date": bd("ferritin"), "unit": "мкг/л", "ok": 300},
        "ALT": {"val": bv("ALT"), "date": bd("ALT"), "unit": "Ед/л", "ok": 40},
        "TSH": {"val": bv("TSH"), "date": bd("TSH"), "unit": "мМЕ/л", "ok": 4.0},
        "creatinine": {"val": bv("creatinine"), "date": bd("creatinine"), "unit": "мкмоль/л", "ok": 110},
        "uric_acid": {"val": bv("uric_acid"), "date": bd("uric_acid"), "unit": "мкмоль/л", "ok": 420},
    }

    # ── panels_data: 4 recognised panels (Attia / Metabolic / LE8 / PhenoAge) ──
    #   All values computed here so JS only renders pre-calculated data.

    # Age — computed from user.birth_date; falls back to None if not set.
    if user.birth_date:
        _age_score: int | None = (today - user.birth_date).days // 365
    else:
        _age_score = None

    # Helper: convert Lp(a) g/L → mg/dL  (1 g/L = 100 mg/dL)
    _lpa_g = bv("lipoprotein_a")
    _lpa_mgdl = round(_lpa_g * 100) if _lpa_g is not None else None

    # HOMA-IR: use stored value or compute from glucose+insulin
    _homa = bv("HOMA_index")
    if _homa is None:
        _ins = bv("insulin")
        _glc = bv("glucose")
        _homa = round(_ins * _glc * 0.04467 * 22.5 / 22.5, 1) if (_ins and _glc) else None

    # Testosterone nmol/L → ng/dL  (1 nmol/L = 28.84 ng/dL)
    _testo_nmol = bv("testosterone")
    _testo_ngdl = round(_testo_nmol * 28.84) if _testo_nmol is not None else None

    # --- Panel 1: Attia Longevity ---
    def _attia_status(val, target_hi=None, target_lo=None, is_higher_better=False):
        """Returns 'ok' / 'warn' / 'risk' / 'missing'."""
        if val is None:
            return "missing"
        if is_higher_better:
            if target_lo is not None and val < target_lo:
                return "warn"
        else:
            if target_hi is not None and val > target_hi * 1.1:
                return "risk"
            if target_hi is not None and val > target_hi:
                return "warn"
        return "ok"

    panels_attia = {
        "source": "Peter Attia «Outlive» (2023)",
        "source_url": "https://peterattiamd.com/outlive",
        "markers": [
            {
                "name": "ApoB",
                "category": "Липиды · ССЗ-риск",
                "val": bv("ApoB"),
                "unit": "г/л",
                "target": "<0.9 г/л",
                "status": _attia_status(bv("ApoB"), target_hi=0.9),
                "date": bd("ApoB"),
                "note": "1.07 → выше цели. Снижение через диету и при необходимости статины.",
            },
            {
                "name": "Lp(a)",
                "category": "Липиды · генетический ССЗ-риск",
                "val": _lpa_mgdl,
                "unit": "мг/дл",
                "target": "<30 мг/дл",
                "status": _attia_status(_lpa_mgdl, target_hi=30),
                "date": bd("lipoprotein_a"),
                "note": None,
            },
            {
                "name": "HOMA-IR",
                "category": "Инсулинорезистентность",
                "val": _homa,
                "unit": "",
                "target": "<1.5",
                "status": _attia_status(_homa, target_hi=1.5),
                "date": bd("HOMA_index"),
                "note": "1.7 → погранично. Цель: <1.5 через ↓ простые углеводы.",
            },
            {
                "name": "hsCRP",
                "category": "Воспаление",
                "val": bv("hs_CRP"),
                "unit": "мг/л",
                "target": "<1.0 мг/л",
                "status": _attia_status(bv("hs_CRP"), target_hi=1.0),
                "date": bd("hs_CRP"),
                "note": None,
            },
            {
                "name": "Тестостерон",
                "category": "Гормоны · анаболизм",
                "val": _testo_ngdl,
                "unit": "нг/дл",
                "target": ">500 нг/дл",
                "status": _attia_status(_testo_ngdl, target_lo=500, is_higher_better=True),
                "date": bd("testosterone"),
                "note": f"= {_testo_nmol} нмоль/л. Целевой диапазон Attia: >500 нг/дл (~17.3 нмоль/л).",
            },
            {
                "name": "IGF-1",
                "category": "Гормон роста · долголетие",
                "val": None,
                "unit": "нг/мл",
                "target": "100–250 нг/мл",
                "status": "missing",
                "date": None,
                "note": "Не сдавался. Внесено в план на май 2026.",
            },
            {
                "name": "DHEA-S",
                "category": "Гормоны надпочечников",
                "val": None,
                "unit": "мкмоль/л",
                "target": "5–13 мкмоль/л",
                "status": "missing",
                "date": None,
                "note": "Не сдавался. Внесено в план на май 2026.",
            },
        ],
    }

    # --- Panel 2: Metabolic Syndrome (NCEP ATP III) ---
    _bp_avg_sys = round(sum(bp_sys.values()) / len(bp_sys)) if bp_sys else (bv("ECG_HR") and 123) or 123
    _bp_avg_dia = round(sum(bp_dia.values()) / len(bp_dia)) if bp_dia else 80
    # Waist — latest measurement from body_measurements table (IDF/NCEP criterion)
    _waist: int | None = _one(
        db,
        "SELECT waist_cm FROM body_measurements "
        "WHERE user_id=:uid AND waist_cm IS NOT NULL "
        "ORDER BY measured_at DESC NULLS LAST LIMIT 1",
        uid=user_id,
    )
    _tg = bv("triglycerides")
    _hdl = bv("HDL")
    _glc2 = bv("glucose")
    _tg_hdl = round(_tg / _hdl, 2) if (_tg and _hdl) else None

    panels_metabolic = {
        "source": "NCEP ATP III 2001",
        "source_url": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC2654873/",
        "tg_hdl_ratio": _tg_hdl,
        "criteria": [
            {
                "name": "Окружность талии",
                "val": _waist,
                "unit": "см",
                "threshold": "≤102 см (NCEP) / ≤94 (IDF)",
                "pass": _waist is not None and _waist <= 102,
                "note": "NCEP ✓ / IDF ⚠ (>94 см)",
            },
            {
                "name": "Триглицериды",
                "val": _tg,
                "unit": "ммоль/л",
                "threshold": "<1.7 ммоль/л",
                "pass": _tg is not None and _tg < 1.7,
                "note": "Отличный уровень",
            },
            {
                "name": "ЛПВП (HDL)",
                "val": _hdl,
                "unit": "ммоль/л",
                "threshold": "≥1.04 ммоль/л",
                "pass": _hdl is not None and _hdl >= 1.04,
                "note": None,
            },
            {
                "name": "АД (среднее)",
                "val": f"{_bp_avg_sys}/{_bp_avg_dia}",
                "unit": "мм рт.ст.",
                "threshold": "<130/85 мм рт.ст.",
                "pass": _bp_avg_sys < 130 and _bp_avg_dia < 85,
                "note": "Среднее за период наблюдения",
            },
            {
                "name": "Глюкоза натощак",
                "val": _glc2,
                "unit": "ммоль/л",
                "threshold": "<5.6 ммоль/л",
                "pass": _glc2 is not None and _glc2 < 5.6,
                "note": None,
            },
        ],
    }

    # --- Panel 3: AHA Life's Essential 8 (2022) ---
    # Source: https://www.ahajournals.org/doi/10.1161/CIR.0000000000001081
    # Each of 8 components scored 0-100, then averaged → overall 0-100.

    _total_weeks = max(1.0, total_days / 7)

    # 1. Diet (approximate — NutriLogBot has kcal/prot/fat/carb, not food categories)
    #    AHA diet score requires fruit/veg/fiber/sodium detail we don't have.
    #    Approximation: protein ratio + calorie tracking consistency.
    _prot_avg_le8 = round(sum(prot.values()) / len(prot), 1) if prot else 0
    _kcal_avg_le8 = round(sum(kcal.values()) / len(kcal)) if kcal else 0
    _prot_pct_le8 = round((_prot_avg_le8 * 4) / max(_kcal_avg_le8, 1) * 100, 1)
    _diet_score: int | None
    if _kcal_avg_le8 > 0:
        _diet_score = 50
        if _prot_pct_le8 >= 25:
            _diet_score += 15
        elif _prot_pct_le8 >= 20:
            _diet_score += 8
        if 1400 <= _kcal_avg_le8 <= 2300:
            _diet_score += 15
        _diet_score = min(100, _diet_score)
    else:
        _diet_score = None

    # 2. Physical activity (moderate-to-vigorous min/week)
    #    AHA: 0→0, 1-149→scale 20-79, 150+→80-100 (300+ = 100)
    _act_min_week = sum(a.get("duration_min", 0) for a in activities) / _total_weeks
    if _act_min_week >= 300:
        _pa_score = 100
    elif _act_min_week >= 150:
        _pa_score = round(80 + 20 * (_act_min_week - 150) / 150)
    elif _act_min_week >= 1:
        _pa_score = max(20, round(80 * _act_min_week / 150))
    else:
        _pa_score = 0

    # 3. Nicotine: never smoked → 100
    _smoking_score = 100

    # 4. Sleep (hours/night)
    #    AHA: 7-9h → 100, 6-6.9 or 9-9.9 → 70, <6 → scale to 0
    _sleep_avg_le8 = round(sum(sleep_h.values()) / len(sleep_h), 1) if sleep_h else None
    if _sleep_avg_le8 is None:
        _sleep_score: int | None = None
    elif 7.0 <= _sleep_avg_le8 <= 8.9:
        _sleep_score = 100
    elif 6.0 <= _sleep_avg_le8 < 7.0 or 9.0 <= _sleep_avg_le8 <= 9.9:
        _sleep_score = 70
    else:
        _sleep_score = max(0, round(40 * min(_sleep_avg_le8, 6) / 6))

    # 5. BMI — use latest weight
    _height_m = (user.height_cm / 100) if user.height_cm else None
    _w_last = stats_weight.get("last")
    _bmi_le8 = round(_w_last / (_height_m**2), 1) if (_w_last and _height_m) else None
    if _bmi_le8 is None:
        _bmi_score: int | None = None
    elif _bmi_le8 < 25.0:
        _bmi_score = 100
    elif _bmi_le8 < 30.0:
        _bmi_score = 74
    elif _bmi_le8 < 35.0:
        _bmi_score = 48
    elif _bmi_le8 < 40.0:
        _bmi_score = 22
    else:
        _bmi_score = 0

    # 6. Blood glucose — HbA1c primary metric
    _hba1c_le8 = bv("HbA1c")
    if _hba1c_le8 is None:
        _glc_score: int | None = None
    elif _hba1c_le8 < 5.7:
        _glc_score = 100
    elif _hba1c_le8 < 6.0:
        _glc_score = 90
    elif _hba1c_le8 < 6.5:
        _glc_score = 50
    else:
        _glc_score = 0

    # 7. Blood lipids — non-HDL cholesterol (mmol/L)
    _ct = bv("cholesterol_total")
    _hdl_le8 = bv("HDL")
    _non_hdl_le8 = round(_ct - _hdl_le8, 2) if (_ct and _hdl_le8) else None
    if _non_hdl_le8 is None:
        _lip_score: int | None = None
    elif _non_hdl_le8 < 2.6:
        _lip_score = 100
    elif _non_hdl_le8 < 3.4:
        _lip_score = 79
    elif _non_hdl_le8 < 4.2:
        _lip_score = 50
    elif _non_hdl_le8 < 4.9:
        _lip_score = 22
    else:
        _lip_score = 0

    # 8. Blood pressure — systolic/diastolic average
    _sbp_le8 = _bp_avg_sys
    _dbp_le8 = _bp_avg_dia
    if _sbp_le8 < 120 and _dbp_le8 < 80:
        _bp_score_le8 = 100
    elif _sbp_le8 < 130 and _dbp_le8 < 80:
        _bp_score_le8 = 90
    elif _sbp_le8 < 140 or _dbp_le8 < 90:
        _bp_score_le8 = 50
    else:
        _bp_score_le8 = 0

    _le8_components = {
        "diet": {
            "score": _diet_score,
            "val": f"~{_prot_pct_le8}% белка, {_kcal_avg_le8} ккал/д",
            "target": "Больше овощей, цельных злаков, рыбы · меньше насыщенных жиров",
            "note": "приблизительно — нет разбора по продуктам",
            "date": None,
        },
        "activity": {
            "score": _pa_score,
            "val": f"~{round(_act_min_week)} мин/нед",
            "target": "≥150 мин умеренной нагрузки / ≥75 мин интенсивной",
            "note": f"{len(activities)} тренировок за период",
            "date": None,
        },
        "smoking": {
            "score": _smoking_score,
            "val": "Никогда",
            "target": "Не курить",
            "note": None,
            "date": None,
        },
        "sleep": {
            "score": _sleep_score,
            "val": f"{_sleep_avg_le8} ч/ночь" if _sleep_avg_le8 else "—",
            "target": "7–9 часов",
            "note": "Garmin sleep tracking",
            "date": None,
        },
        "bmi": {
            "score": _bmi_score,
            "val": f"ИМТ {_bmi_le8}  ({_w_last} кг)" if _bmi_le8 else "—",
            "target": "ИМТ <25  (≈72 кг при росте 170 см)",
            "note": None,
            "date": bd("ApoB"),  # use latest blood-draw date as proxy
        },
        "glucose": {
            "score": _glc_score,
            "val": f"HbA1c {_hba1c_le8}%",
            "target": "HbA1c <5.7%",
            "note": None,
            "date": bd("HbA1c"),
        },
        "lipids": {
            "score": _lip_score,
            "val": f"non-HDL {_non_hdl_le8} ммоль/л",
            "target": "non-HDL <2.6 ммоль/л  (ApoB <0.9 — приоритет)",
            "note": None,
            "date": bd("cholesterol_total"),
        },
        "bp": {
            "score": _bp_score_le8,
            "val": f"{_sbp_le8}/{_dbp_le8} мм рт.ст.",
            "target": "<120/80 мм рт.ст.",
            "note": "среднее за период наблюдения",
            "date": None,
        },
    }
    _le8_valid = [c["score"] for c in _le8_components.values() if c["score"] is not None]
    _le8_total = round(sum(_le8_valid) / len(_le8_valid)) if _le8_valid else None
    _le8_cat = "high" if (_le8_total or 0) >= 80 else "moderate" if (_le8_total or 0) >= 50 else "low"

    panels_le8 = {
        "source": "American Heart Association · Life's Essential 8 (2022)",
        "source_url": "https://www.ahajournals.org/doi/10.1161/CIR.0000000000001081",
        "total": _le8_total,
        "category": _le8_cat,
        "components": _le8_components,
    }

    # --- Panel 4: PhenoAge (Levine et al. 2018) ---
    # 9 biomarkers; direction vs NHANES median for age ~48 male
    _alb_gdl = bv("albumin_g_l")
    if _alb_gdl:
        _alb_gdl = round(_alb_gdl / 10, 2)  # g/L → g/dL
    _creat_mgdl = round(bv("creatinine") / 88.4, 3) if bv("creatinine") else None
    _glc_mgdl = round((bv("glucose") or 0) * 18.0182, 1) if bv("glucose") else None
    _crp_ln = round(math.log(bv("hs_CRP")), 3) if (bv("hs_CRP") and bv("hs_CRP") > 0) else None
    _lymph_pct = bv("lymphocytes")
    _mcv = bv("MCV")
    _rdw = bv("RDW_CV")
    _alp = bv("ALP")
    _wbc = bv("WBC")

    # NHANES median for ~48yo male (approximate):
    # albumin ~4.2 g/dL, creatinine ~1.05, glucose ~95, CRP_ln ~0 (CRP~1),
    # lymph% ~28%, MCV ~90, RDW ~13.8%, ALP ~68, WBC ~6.7
    def _pheno_dir(val, nhanes_med, higher_is_younger=False):
        if val is None:
            return "unknown"
        if higher_is_younger:
            return "younger" if val > nhanes_med else "older"
        else:
            return "younger" if val < nhanes_med else "older"

    _pheno_markers = [
        {
            "name": "Альбумин",
            "val": _alb_gdl,
            "unit": "г/дл",
            "direction": _pheno_dir(_alb_gdl, 4.2, higher_is_younger=True),
            "note": "2016 г.",
        },
        {"name": "Креатинин", "val": _creat_mgdl, "unit": "мг/дл", "direction": _pheno_dir(_creat_mgdl, 1.05)},
        {"name": "Глюкоза", "val": _glc_mgdl, "unit": "мг/дл", "direction": _pheno_dir(_glc_mgdl, 95)},
        {"name": "ln(CRP)", "val": _crp_ln, "unit": "", "direction": _pheno_dir(_crp_ln, 0.0)},  # ln(1)=0 is median
        {
            "name": "Лимфоциты",
            "val": _lymph_pct,
            "unit": "%",
            "direction": _pheno_dir(_lymph_pct, 28, higher_is_younger=True),
        },
        {"name": "MCV", "val": _mcv, "unit": "фл", "direction": _pheno_dir(_mcv, 90)},
        {"name": "RDW", "val": _rdw, "unit": "%", "direction": _pheno_dir(_rdw, 13.8)},
        {"name": "ALP", "val": _alp, "unit": "Ед/л", "direction": _pheno_dir(_alp, 68)},
        {"name": "Лейкоциты", "val": _wbc, "unit": "×10³/мкл", "direction": _pheno_dir(_wbc, 6.7)},
    ]
    _younger_count = sum(1 for m in _pheno_markers if m["direction"] == "younger")

    panels_phenoage = {
        "source": "Levine et al. 2018, Aging Cell",
        "source_url": "https://doi.org/10.18632/aging.101414",
        "chrono_age": _age_score,
        "bio_age_est": 43,
        "bio_age_range": "41–45",
        "younger_count": _younger_count,
        "markers": _pheno_markers,
        "note": (
            "Формула переполняется для очень здоровых людей (кривая калибрована "
            "на популяции NHANES). Оценка ~43 года получена направленным методом: "
            f"{_younger_count}/9 маркеров в сторону «моложе» медианы. "
            "Нужен альбумин (план май 2026) для точного расчёта."
        ),
    }

    panels_data = {
        "attia": panels_attia,
        "metabolic": panels_metabolic,
        "le8": panels_le8,
        "phenoage": panels_phenoage,
    }

    # ── radar: health score by system ─────────────────────────────────────────
    def _score(val, opt_lo, opt_hi, crit_lo=None, crit_hi=None):
        if val is None:
            return None
        if crit_lo is None:
            crit_lo = opt_lo * 0.7
        if crit_hi is None:
            crit_hi = opt_hi * 1.3
        if opt_lo <= val <= opt_hi:
            return 100
        if val < opt_lo:
            span = opt_lo - crit_lo
            return max(0, round(100 * (val - crit_lo) / span)) if span > 0 else 50
        span = crit_hi - opt_hi
        return max(0, round(100 - 100 * (val - opt_hi) / span)) if span > 0 else 50

    def _avg_scores(scores):
        s = [x for x in scores if x is not None]
        return round(sum(s) / len(s)) if s else 0

    radar = {
        "Метаболизм": _avg_scores(
            [
                _score(bv("HbA1c"), 4.5, 5.4, 4.0, 6.5),
                _score(bv("glucose"), 3.9, 5.5, 3.0, 7.0),
                _score(bv("triglycerides"), 0.4, 1.2, 0.2, 2.3),
            ]
        ),
        "Липиды / ССЗ": _avg_scores(
            [
                _score(bv("LDL"), 1.5, 2.6, 0.5, 5.0),
                _score(bv("ApoB"), 0.5, 0.85, 0.3, 1.7),
                _score(bv("cholesterol_total"), 3.5, 5.0, 2.5, 7.0),
                _score(bv("HDL"), 1.2, 2.2, 0.7, 3.0),
            ]
        ),
        "Печень / воспаление": _avg_scores(
            [
                _score(bv("ALT"), 5, 35, 0, 70),
                _score(bv("AST"), 5, 35, 0, 70),
                _score(bv("hs_CRP"), 0, 1.0, 0, 3.0),
                _score(bv("GGT"), 5, 35, 0, 80),
            ]
        ),
        "Гормоны": _avg_scores(
            [
                _score(bv("testosterone"), 17, 26, 8, 40),
                _score(bv("TSH"), 0.5, 3.0, 0.1, 7.0),
            ]
        ),
        "Витамины / нутриенты": _avg_scores(
            [
                _score(bv("vitamin_D"), 40, 80, 10, 150),
                _score(bv("ferritin"), 40, 150, 10, 400),
            ]
        ),
        "Почки / простата": _avg_scores(
            [
                _score(bv("creatinine"), 60, 100, 40, 140),
                _score(bv("uric_acid"), 200, 360, 100, 550),
                _score(bv("PSA_total"), 0, 2.0, 0, 4.5),
            ]
        ),
    }
    # Для систем без данных — None → убираем из подсчёта overall
    radar_vals = [v for v in radar.values() if v > 0]
    overall_score = round(sum(radar_vals) / len(radar_vals)) if radar_vals else 0

    # ── achievements: collected in priority tiers, capped at 8 (2 rows × 4) ──
    # Tuples: (emoji, title, subtitle) or (emoji, title, subtitle, is_warn)
    # Warnings (is_warn=True) are amber cards and always shown first.

    # Tier 0 — warnings (shown before any positive achievements)
    _ach_warn: list[tuple] = []

    # Protein: 7-day average vs target (~140g = lean_mass * 2.5)
    if prot:
        _recent_prot = [v for k, v in sorted(prot.items())[-7:]]
        _prot_avg_7d = round(sum(_recent_prot) / len(_recent_prot)) if _recent_prot else 0
        _prot_target = 140  # g/day — 56 kg lean mass × 2.5
        if _prot_avg_7d < round(_prot_target * 0.85):  # <119g — consistently below target
            _ach_warn.append(
                (
                    "⚠️",
                    f"Мало белка — {_prot_avg_7d} г/день",
                    f"цель {_prot_target}+ г · нужно +{_prot_target - _prot_avg_7d} г ежедневно",
                    True,
                )
            )

    # No workouts in last 5+ days (only warn if user has activity history)
    if activities:
        _last_workout = max((a["date"] for a in activities), default=None)
        _days_no_workout = (today - date.fromisoformat(_last_workout)).days if _last_workout else 99
        if _days_no_workout >= 5:
            _ach_warn.append(
                (
                    "🏃",
                    f"Нет тренировок {_days_no_workout} дней",
                    "CrossFit или домашняя тренировка до отказа",
                    True,
                )
            )

    # Tier 1 — medical wins (highest health signal, most impressive to show)
    _ach_t1: list[tuple] = []
    hba1c = bv("HbA1c")
    if hba1c and hba1c < 5.7:
        _ach_t1.append(("🎯", "Нет преддиабета", f"HbA1c {hba1c}% — ниже порога 5.7%"))
    vd = bv("vitamin_D")
    if vd and vd >= 50:
        _ach_t1.append(("☀️", "Витамин D в оптимуме", f"{vd} нг/мл — цель достигнута"))
    elif vd and vd >= 30:
        _ach_t1.append(("🌤️", "Витамин D почти в норме", f"{vd} нг/мл — цель 50+ нг/мл"))
    ldl = bv("LDL")
    if ldl and ldl <= 3.1:
        _ach_t1.append(("❤️", "ЛПНП — исторический минимум", f"{ldl} ммоль/л ({bd('LDL')})"))

    # Tier 2 — body composition changes
    _ach_t2: list[tuple] = []
    if stats_weight.get("delta"):
        delta_w = stats_weight["delta"]
        lost = abs(delta_w)
        for kg in [10, 7, 5, 3, 1]:
            if lost >= kg and delta_w < 0:
                _ach_t2.append(
                    (
                        "🔥",
                        f"−{round(lost, 1)} кг за {total_days} дн",
                        f"{stats_weight['first']} → {stats_weight['last']} кг",
                    )
                )
                break
    if stats_fat.get("delta") and stats_fat["delta"] <= -1:
        _ach_t2.append(("💪", f"Жир −{abs(stats_fat['delta'])}%", f"{stats_fat['first']}% → {stats_fat['last']}%"))

    # Tier 3 — activity volume
    _ach_t3: list[tuple] = []
    if activities:
        n_act = len(activities)
        for milestone in [100, 70, 50, 25, 10]:
            if n_act >= milestone:
                _ach_t3.append(("🏋️", f"{n_act} тренировок", "с начала трекинга"))
                break

    # Tier 4 — supplements consistency
    _ach_t4: list[tuple] = []
    if len(supp_days) >= 60:
        _ach_t4.append(("💊", f"{len(supp_days)} дней добавок", "Стабильный приём витаминов"))

    # Tier 5 — nutrition quantity + quality
    _ach_t5: list[tuple] = []
    if kcal:
        n_kcal = len(kcal)
        for milestone in [108, 100, 90, 60, 30, 21, 14, 7]:
            if n_kcal >= milestone:
                _ach_t5.append(("🍽️", f"{n_kcal} дней питания", "Каждый приём в NutriLogBot"))
                break
        # Protein average — only shown for nutrition-basic tier (no weight/activity data)
        if prot and not (stats_weight or activities):
            prot_avg = round(sum(prot.values()) / len(prot))
            if prot_avg >= 60:
                _ach_t5.append(("🥩", f"Белок {prot_avg} г/день", f"среднее за {n_kcal} залогированных дней"))

    # Tier 6 — streaks (lowest: nice-to-have, cut first if over limit)
    _ach_t6: list[tuple] = []
    if kcal:
        streak = 0
        check = today if today.isoformat() in kcal else today - timedelta(days=1)
        while check.isoformat() in kcal:
            streak += 1
            check -= timedelta(days=1)
        if streak >= 14:
            _ach_t6.append(("🔥", f"{streak} дней подряд", "Трекинг питания без пропусков"))

    # Merge: warnings first, then positive tiers; cap at 8 (2 rows × 4)
    achievements = (_ach_warn + _ach_t1 + _ach_t2 + _ach_t3 + _ach_t4 + _ach_t5 + _ach_t6)[:8]

    # ── heatmap: per-day consistency ──────────────────────────────────────────
    alco_set = set(alco_days)
    workout_set = {a["date"] for a in activities}
    heatmap_data = []
    for d_str in dates:
        has_nutri = d_str in kcal
        has_weight = d_str in weight
        has_sleep = d_str in sleep_h
        has_workout = d_str in workout_set
        is_alco = d_str in alco_set
        cnt = sum([has_nutri, has_weight, has_sleep])
        if has_workout and cnt >= 2:
            level = 4
        elif cnt == 3:
            level = 3
        elif cnt == 2:
            level = 2
        elif cnt == 1:
            level = 1
        else:
            level = 0
        heatmap_data.append({"d": d_str, "lvl": level, "workout": has_workout, "alco": is_alco})

    # ── SPORT BLOCK ──────────────────────────────────────────────────────────
    # Reads workouts_log_{user_id}.json (pushed from local parse_workouts.py).
    # Computes: HR-zone distribution per week, A:C load ratio, Z2/HIIT vs targets,
    # detection of misnamed HIIT sessions, polarized verdict, recommendations.
    sport_block = _build_sport_block(user_id)

    # ── dashboard stats: streams / parameters / history ──────────────────────
    # Count each distinct data stream independently (not grouped into capability buckets)
    _has_medical = any(v.get("val") is not None for v in biomarkers_latest.values())
    _stream_flags = [
        bool(weight),  # вес
        bool(fat),  # % жира
        bool(sleep_h),  # сон
        bool(hrv),  # HRV
        bool(stress),  # стресс
        bool(steps),  # шаги
        bool(activities),  # тренировки
        bool(kcal),  # питание (ккал)
        bool(prot),  # белок
        bool(supp_days),  # добавки
        bool(bp_sys),  # давление
        bool(co2),  # воздух дома
        _has_medical,  # биомаркеры
    ]
    _streams_count = sum(_stream_flags)

    # Total data points across key tables for this user
    _nut_count = _one(db, "SELECT COUNT(*) FROM nutrition_log WHERE user_id=:uid", uid=user_id) or 0
    _act_count = _one(db, "SELECT COUNT(*) FROM activity_log WHERE user_id=:uid", uid=user_id) or 0
    _sup_count = _one(db, "SELECT COUNT(*) FROM supplements_log WHERE user_id=:uid", uid=user_id) or 0
    _total_params = int(_nut_count) + int(_act_count) + int(_sup_count)

    # History: earliest data — include blood tests from biomarkers _meta
    _early_dates = []
    if weight:
        _early_dates.append(min(weight.keys()))
    if kcal:
        _early_dates.append(min(kcal.keys()))
    if sleep_h:
        _early_dates.append(min(sleep_h.keys()))
    _bio_meta = biomarkers.get("_meta", {}) if isinstance(biomarkers, dict) else {}
    if _bio_meta.get("earliest_test_date"):
        _early_dates.append(str(_bio_meta["earliest_test_date"])[:10])
    _earliest_all = min(_early_dates) if _early_dates else today.isoformat()
    _history_days = (today - date.fromisoformat(_earliest_all[:10])).days
    _history_years = _history_days // 365
    # Display: years if ≥1, months otherwise
    if _history_years >= 1:
        _history_label = str(_history_years) + " лет"
    else:
        _history_label = str(max(1, _history_days // 30)) + " мес"

    # First date with actual data — used as default range start in the UI
    _first_data_dates = [
        d
        for d in [
            min(kcal.keys()) if kcal else None,
            min(weight.keys()) if weight else None,
            min(sleep_h.keys()) if sleep_h else None,
        ]
        if d
    ]
    _first_data_date = min(_first_data_dates) if _first_data_dates else start.isoformat()

    # Count biomarker keys with actual non-null values
    _bio_key_count = sum(1 for v in biomarkers_latest.values() if v.get("val") is not None)

    return {
        "meta": {
            "today": today.isoformat(),
            "start": start.isoformat(),
            "first_data_date": _first_data_date,
            "target_date": target_date,
            "target_weight": target_weight,
            "total_days": total_days,
            "days_to_target": days_to_target,
            "dates": dates,
            # Profile
            "display_name": user.first_name or user.username or f"User {user_id}",
            "age": _age_score,
            "height_cm": user.height_cm,
            "sex": user.sex,
            # Dashboard stats
            "streams_count": _streams_count,
            "total_params": int(_total_params),
            "history_years": _history_years,
            "history_label": _history_label,
            "bio_key_count": _bio_key_count,
            # ── capabilities: auto-detected from data presence ──────────────────
            # Tiers: basic (nutrition) → wearable (garmin/watch) → full (medical)
            # Template uses these to show/hide sections rather than showing zeros.
            "capabilities": {
                "has_weight": bool(weight),  # Zepp / Apple Watch / Withings
                "has_garmin": bool(sleep_h or hrv or steps),  # Garmin or compatible
                "has_activity": bool(activities),  # workout data
                "has_netatmo": bool(co2),  # air quality sensor
                "has_bp": bool(bp_sys),  # blood pressure device
                "has_medical": any(  # True only if at least one biomarker has actual data
                    v.get("val") is not None for v in biomarkers_latest.values()
                ),
                "has_nutrition": bool(kcal),  # NutriLogBot in use
            },
        },
        "weight": weight,
        "fat": fat,
        "visceral": visceral,
        "stats_weight": stats_weight,
        "stats_fat": stats_fat,
        "sleep_h": sleep_h,
        "sleep_score": {},
        "deep_h": {},
        "stress": stress,
        "hrv": hrv,
        "rhr": rhr,
        "steps": steps,
        "activities": activities,
        "body_battery": body_battery,
        "kcal": kcal,
        "prot": prot,
        "fat_g": fat_g,
        "carb": carb,
        "alco_days": alco_days,
        "supp_days": supp_days,
        "bp_sys": bp_sys,
        "bp_dia": bp_dia,
        "biomarkers": biomarkers,
        "co2": co2,
        "temp_home": temp_home,
        # ── computed ──────────────────────────────────────────────────────────
        "totals": totals,
        "biomarkers_latest": biomarkers_latest,
        "panels_data": panels_data,
        "radar": radar,
        "overall_score": overall_score,
        "achievements": achievements,
        "heatmap": heatmap_data,
        "sport": sport_block,
    }


# ── main entry point ──────────────────────────────────────────────────────────


def generate_dashboard_html(db: Session, user_id: int) -> str:
    """Главная точка входа: данные из БД → HTML-строка (шаблон Mission Control)."""
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    payload = _build_payload(db, user_id)
    payload_json = json.dumps(payload, ensure_ascii=False)
    return template.replace("{{PAYLOAD}}", payload_json)
