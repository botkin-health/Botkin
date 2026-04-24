"""
HealthVault Share Dashboard Generator
Читает данные пользователя из PostgreSQL → вставляет JSON-payload в mc_template.html → возвращает HTML.
Дизайн шаблона не меняется — только данные.
"""

from __future__ import annotations

import json
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
        # Body Battery: prefer stats.bodyBatteryAtWakeTime, fallback bodyBatteryHighest
        stats_sub = raw.get("stats") or {}
        bb = stats_sub.get("bodyBatteryAtWakeTime") or raw.get("body_battery_max")
        if bb:
            body_battery[d] = int(bb)

        # Blood pressure (from Apple Health Shortcut)
        sys_val = raw.get("blood_pressure_systolic")
        dia_val = raw.get("blood_pressure_diastolic")
        if sys_val:
            bp_sys[d] = int(sys_val)
        if dia_val:
            bp_dia[d] = int(dia_val)

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

    _alco_kw = [
        "вин",
        "виски",
        "шампан",
        "джин",
        "негрон",
        "пив",
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
        "сидр",
        "глинтвейн",
        "бренди",
        "ром",
        "wine",
        "beer",
        "whisky",
        "vodka",
        "gin",
        "rum",
        "champagne",
    ]

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
                if any(kw in name_lower for kw in _alco_kw):
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

    # ── activities (workouts) — empty list, workout data not in activity_log ──
    activities: list = []

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
        "sleep_score": {},  # not in DB
        "deep_h": {},  # not in DB
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
    }


# ── main entry point ──────────────────────────────────────────────────────────


def generate_dashboard_html(db: Session, user_id: int) -> str:
    """Главная точка входа: данные из БД → HTML-строка (шаблон Mission Control)."""
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    payload = _build_payload(db, user_id)
    payload_json = json.dumps(payload, ensure_ascii=False)
    return template.replace("{{PAYLOAD}}", payload_json)
