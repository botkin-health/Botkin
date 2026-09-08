"""Agent tools: recent workouts (Garmin + Apple Health)."""

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from webhook.jwt_auth import get_agent_user, get_db
from .common import _today_in_user_tz

router = APIRouter(prefix="/api/agent", tags=["agent-tools-workouts"])


@router.get("/recent_workouts")
async def recent_workouts(
    days: int = 30,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Workout summary by training-load canons (Seiler/Attia/Maffetone).

    Reads workouts_log_<user_id>.json from /app/telegram-bot/ (Garmin activity
    parser writes there). Returns Z2 min/week, HIIT min/week, A:C load ratio,
    polarized distribution, mistagged HIIT flag.

    Источник данных (приоритет):
    1. File `workouts_log_<user_id>.json` — rich data (Z2 zones, training load, MAF).
       Сейчас есть только у owner (Alex, push_workouts_to_container.py).
    2. Fallback: таблица `workouts` в БД — для остальных пользователей.
       Меньше полей (только type, duration, distance, calories), без zones/load,
       но достаточно для базовых вопросов «сколько раз бегал», «когда тренировался».
    """
    import json as _json
    from pathlib import Path as _Path
    from sqlalchemy import text as sql_text

    days = max(1, min(days, 180))
    today_date = _today_in_user_tz(user)
    cutoff = today_date - timedelta(days=days)

    wk_path = _Path(f"/app/telegram-bot/workouts_log_{user.telegram_id}.json")

    # ── Fallback: DB-based мульти-юзер (когда file отсутствует) ──────────────
    if not wk_path.exists():
        db_rows = db.execute(
            sql_text(
                """
                SELECT date, workout_type, duration_minutes, distance_km,
                       calories_burned, source, start_time
                FROM workouts
                WHERE user_id = :uid AND date >= :cutoff
                ORDER BY date DESC, start_time DESC NULLS LAST
                """
            ),
            {"uid": user.telegram_id, "cutoff": cutoff},
        ).fetchall()
        if not db_rows:
            return {"status": "no_data", "available": False, "reason": "no workouts in DB or file"}

        from collections import Counter as _Counter

        type_labels_ru = {
            "running": "бег",
            "walking": "ходьба",
            "strength_training": "силовая",
            "yoga": "йога",
            "cycling": "велосипед",
            "swimming": "плавание",
            "elliptical": "эллипс",
            "cardio": "кардио",
            "hiit": "HIIT",
            "fitness_equipment": "тренажёр",
            "other": "другое",
        }
        type_counts = _Counter(r.workout_type or "unknown" for r in db_rows)
        by_type = {type_labels_ru.get(t, t): {"count": c, "garmin_type": t} for t, c in type_counts.most_common()}

        # Extremes per type (по duration и distance)
        extremes_by_type: dict[str, Any] = {}
        for t in type_counts:
            of_type = [r for r in db_rows if (r.workout_type or "unknown") == t]
            with_dur = [r for r in of_type if r.duration_minutes]
            with_dist = [r for r in of_type if r.distance_km]
            longest_dur = max(with_dur, key=lambda r: r.duration_minutes) if with_dur else None
            longest_dist = max(with_dist, key=lambda r: r.distance_km) if with_dist else None
            extremes_by_type[type_labels_ru.get(t, t)] = {
                "count": len(of_type),
                "longest_by_duration": {
                    "date": longest_dur.date.isoformat(),
                    "duration_min": longest_dur.duration_minutes,
                    "distance_km": float(longest_dur.distance_km) if longest_dur.distance_km else None,
                }
                if longest_dur
                else None,
                "longest_by_distance": {
                    "date": longest_dist.date.isoformat(),
                    "distance_km": float(longest_dist.distance_km),
                    "duration_min": longest_dist.duration_minutes,
                }
                if longest_dist
                else None,
            }

        weeks = days / 7
        return {
            "status": "ok",
            "source": "db",
            "period_days": days,
            "count": len(db_rows),
            "by_type": by_type,
            "extremes_by_type": extremes_by_type,
            "stats": {
                "per_week": round(len(db_rows) / weeks, 1) if weeks else 0,
                "note": "DB-fallback: нет training_load/Z2/zones, только базовые поля",
            },
            "items": [
                {
                    "date": r.date.isoformat(),
                    "type": r.workout_type,
                    "type_ru": type_labels_ru.get(r.workout_type, r.workout_type),
                    "duration_min": r.duration_minutes,
                    "distance_km": float(r.distance_km) if r.distance_km else None,
                    "calories_burned": r.calories_burned,
                    "source": r.source,
                }
                for r in db_rows[:15]
            ],
        }

    try:
        wd = _json.loads(wk_path.read_text())
    except Exception as e:
        return {"status": "error", "error": f"parse failed: {e}"}

    workouts = wd.get("workouts", [])
    if not workouts:
        return {"status": "no_data", "available": False, "reason": "empty workouts array"}

    # today_date was already computed above using user's timezone
    cutoff = today_date - timedelta(days=days)

    def _to_date(s: str):
        try:
            y, m, d = s.split("-")
            return date(int(y), int(m), int(d))
        except Exception:
            return None

    in_window = []
    for w in workouts:
        wd_date = _to_date(w.get("date", ""))
        if wd_date and cutoff <= wd_date <= today_date:
            in_window.append(w)

    if not in_window:
        return {
            "status": "ok",
            "period_days": days,
            "count": 0,
            "items": [],
            "stats": {"per_week": 0, "z2_min_per_week": 0, "hiit_min_per_week": 0},
        }

    # Aggregate zones (prefer MAF — longevity school — over Garmin hr_zones)
    def _zone_min(w, zone_key):
        zones = w.get("maf_zones") or w.get("hr_zones") or {}
        # Ключи в workouts_log: z1_min..z5_min (а не z1..z5) — как пишет
        # build_workouts_log.py и читает dashboard_generator. Раньше читали
        # голый "z2" → всегда 0 → агент сообщал «0 мин Z2». См. F-001 (08.06.2026).
        return zones.get(zone_key, 0) or zones.get(f"{zone_key}_min", 0) or 0

    weeks = days / 7
    z1_total = sum(_zone_min(w, "z1") for w in in_window)
    z2_total = sum(_zone_min(w, "z2") for w in in_window)
    z3_total = sum(_zone_min(w, "z3") for w in in_window)
    z4_total = sum(_zone_min(w, "z4") for w in in_window)
    z5_total = sum(_zone_min(w, "z5") for w in in_window)
    total_zone_min = z1_total + z2_total + z3_total + z4_total + z5_total

    # «Z2 база» в смысле longevity-школы (Attia/Maffetone, HR-коридор 114-131 для
    # 49 лет) — это aerobic_base_min, посчитанный из посекундных HR-сэмплов
    # (scripts/util/compute_aerobic_base.py). НЕ путать с Garmin-зоной z2 (139+ bpm):
    # лёгкий бег на 128 bpm у Garmin = z1, но это и есть aerobic base. Дашборд берёт
    # именно aerobic_base (dashboard_generator._base_min_for) — агент теперь тоже,
    # иначе при цели Attia 150 мин/нед показывал ~0. См. F-001 (08.06.2026).
    def _aerobic_base_min(w):
        v = w.get("aerobic_base_min")
        if v is not None:
            return float(v)
        maf = w.get("maf_zones") or {}
        if maf.get("z2_min") is not None:
            return float(maf["z2_min"])
        return 0.0

    aerobic_base_total = sum(_aerobic_base_min(w) for w in in_window)

    # Acute vs Chronic load
    seven_ago = today_date - timedelta(days=7)
    acute = [w for w in in_window if _to_date(w["date"]) and _to_date(w["date"]) >= seven_ago]
    acute_load = sum(w.get("training_load") or 0 for w in acute)
    chronic_load_avg = sum(w.get("training_load") or 0 for w in in_window) / weeks if weeks > 0 else 0
    ac_ratio = round(acute_load / chronic_load_avg, 2) if chronic_load_avg > 0 else None

    # Type aggregation — count workouts by Garmin type.
    # IMPORTANT: type is the Garmin classification ('running', 'strength_training',
    # 'walking', 'yoga', ...). activity_name is the user-set route/session label
    # ('Москва - База', 'Гимнастика #3') and is NOT a reliable indicator of
    # exercise type — a session named 'Москва - База' may be running OR walking.
    # ALWAYS read `type` field for classification, not `activity_name`.
    from collections import Counter as _Counter

    type_counts = _Counter(w.get("type") or "unknown" for w in in_window)
    # Russian-friendly labels for the common types so the agent uses them
    type_labels_ru = {
        "running": "бег",
        "walking": "ходьба",
        "strength_training": "силовая",
        "yoga": "йога",
        "cycling": "велосипед",
        "swimming": "плавание",
        "elliptical": "эллипс",
        "cardio": "кардио",
        "hiit": "HIIT",
        "fitness_equipment": "тренажёр",
        "other": "другое",
    }
    by_type = {
        type_labels_ru.get(t, t): {
            "count": c,
            "garmin_type": t,
        }
        for t, c in type_counts.most_common()
    }

    # Extremes per type — рекорды по длительности и дистанции в окне.
    # Нужно потому что items[:15] обрезает выборку до самых свежих, и редкие
    # длинные сессии (марафонские пробежки раз в квартал) туда не попадают.
    # Без этого блока вопрос "самая длинная пробежка года" агенту неотвечаем.
    def _max_by(items, key):
        items = [w for w in items if w.get(key) is not None]
        return max(items, key=lambda w: w[key]) if items else None

    def _extreme_record(w):
        return {
            "date": w.get("date"),
            "name": w.get("activity_name"),
            "duration_min": w.get("duration_min"),
            "distance_km": w.get("distance_km"),
            "avg_hr": w.get("avg_hr"),
        }

    extremes_by_type = {}
    for t in type_counts:
        of_type = [w for w in in_window if (w.get("type") or "unknown") == t]
        longest_dur = _max_by(of_type, "duration_min")
        longest_dist = _max_by(of_type, "distance_km")
        extremes_by_type[type_labels_ru.get(t, t)] = {
            "count": len(of_type),
            "longest_by_duration": _extreme_record(longest_dur) if longest_dur else None,
            "longest_by_distance": _extreme_record(longest_dist) if longest_dist else None,
        }

    return {
        "status": "ok",
        "period_days": days,
        "count": len(in_window),
        "by_type": by_type,
        "extremes_by_type": extremes_by_type,
        "stats": {
            "per_week": round(len(in_window) / weeks, 1),
            # z2_min_per_week = aerobic base (longevity-Z2, HR 114-131), как KPI дашборда
            "z2_min_per_week": round(aerobic_base_total / weeks),
            "z2_metric_note": "z2_min_per_week — это aerobic base (HR 114-131, метрика Attia/Maffetone), НЕ Garmin-зона Z2 (139+)",
            "hiit_min_per_week": round((z4_total + z5_total) / weeks),
            "z2_target_attia": 150,  # mins/week
            "hiit_target_norwegian": 16,  # mins/week (4x4)
            "ac_ratio": ac_ratio,
            "ac_sweet_spot": "0.8-1.3",
        },
        "zones_total_min": {
            "z1": round(z1_total),
            "z2": round(z2_total),
            "z3": round(z3_total),
            "z4": round(z4_total),
            "z5": round(z5_total),
        },
        "polarized_pct": {
            "low (z1+z2)": round(100 * (z1_total + z2_total) / total_zone_min, 1) if total_zone_min else 0,
            "mid (z3)": round(100 * z3_total / total_zone_min, 1) if total_zone_min else 0,
            "high (z4+z5)": round(100 * (z4_total + z5_total) / total_zone_min, 1) if total_zone_min else 0,
            "ideal_seiler": "80/5/15",
        },
        "items": [
            {
                "date": w.get("date"),
                "type": w.get("type"),  # GARMIN classification — primary
                "type_ru": type_labels_ru.get(w.get("type"), w.get("type")),
                "name": w.get("activity_name"),  # user-set route name (e.g. "Москва - База")
                "duration_min": w.get("duration_min"),
                "distance_km": w.get("distance_km"),
                "avg_hr": w.get("avg_hr"),
                "training_load": w.get("training_load"),
                # Потренировочная Z2-база (longevity, HR 114-131) и полная MAF-разбивка
                # зон ИМЕННО этой тренировки. Без этого агент на вопрос «сколько Z2
                # в пробежке 7-го» не имел данных и выдумывал числа. См. F (09.06).
                "aerobic_base_min": w.get("aerobic_base_min"),
                "maf_zones": w.get("maf_zones"),
            }
            for w in sorted(in_window, key=lambda w: w.get("date", ""), reverse=True)[:15]
        ],
    }
