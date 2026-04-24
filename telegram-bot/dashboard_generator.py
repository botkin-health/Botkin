"""
HealthVault Share Dashboard Generator
Читает данные пользователя из PostgreSQL → вставляет JSON-payload в mc_template.html → возвращает HTML.
Дизайн шаблона не меняется — только данные.
"""

from __future__ import annotations

import json
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
        "activity_km": round(sum(a.get("distance_km", 0) or 0 for a in activities), 1),
        "activity_hours": round(sum(a.get("duration_min", 0) for a in activities) / 60),
        "activity_breakdown": [],
        "bp_last": bp_last_str,
        "alco_days_n": len(alco_days),
        "supp_days_n": len(supp_days),
        "kcal_days_n": len(kcal),
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

    # ── achievements ──────────────────────────────────────────────────────────
    achievements = []
    if stats_weight.get("delta", 0) <= -5:
        d = abs(stats_weight["delta"])
        achievements.append(
            ("🔥", f"{d} кг сброшено", f"{stats_weight['first']} → {stats_weight['last']} кг за {total_days} дн")
        )
    hba1c = bv("HbA1c")
    if hba1c and hba1c < 5.7:
        achievements.append(("🎯", "Ушёл из преддиабета", f"HbA1c → {hba1c}% ({bd('HbA1c')})"))
    vd = bv("vitamin_D")
    if vd and vd >= 30:
        achievements.append(("☀️", "Витамин D в оптимуме", f"{vd} нг/мл ({bd('vitamin_D')})"))
    ldl = bv("LDL")
    if ldl and ldl <= 3.1:
        achievements.append(("❤️", "ЛПНП — исторический минимум", f"{ldl} ммоль/л ({bd('LDL')})"))
    if len(kcal) >= 90:
        achievements.append(("🍽️", f"{len(kcal)} дней КБЖУ", "Каждый приём в NutriLogBot"))
    if len(supp_days) >= 70:
        achievements.append(("💊", f"{len(supp_days)} дней добавок", "D3, Mg, Omega-3, фолат"))

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

    return {
        "meta": {
            "today": today.isoformat(),
            "start": start.isoformat(),
            "target_date": target_date,
            "target_weight": target_weight,
            "total_days": total_days,
            "days_to_target": days_to_target,
            "dates": dates,
            "display_name": user.first_name or user.username or f"User {user_id}",
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
        "radar": radar,
        "overall_score": overall_score,
        "achievements": achievements,
        "heatmap": heatmap_data,
    }


# ── main entry point ──────────────────────────────────────────────────────────


def generate_dashboard_html(db: Session, user_id: int) -> str:
    """Главная точка входа: данные из БД → HTML-строка (шаблон Mission Control)."""
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    payload = _build_payload(db, user_id)
    payload_json = json.dumps(payload, ensure_ascii=False)
    return template.replace("{{PAYLOAD}}", payload_json)
