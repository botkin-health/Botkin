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


def _build_sport_block(user_id: int, user_age: int | None = None) -> dict:
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

    # ── окна: 7 дней (acute), 90 дней (главное окно — учёт отпусков/перерывов) ─
    # 90 дней даёт устойчивые средние (≈12.86 недель), не искажаемые поездками
    WINDOW_DAYS = 90
    WINDOW_WEEKS = WINDOW_DAYS / 7  # 12.857
    w7 = [w for w in workouts if _to_date(w["date"]) and (today - _to_date(w["date"])).days <= 7]
    w90 = [w for w in workouts if _to_date(w["date"]) and (today - _to_date(w["date"])).days <= WINDOW_DAYS]

    def _sum_zone(ws, zone_key):
        return round(sum(w.get("hr_zones", {}).get(zone_key, 0) for w in ws))

    def _sum_load(ws):
        return sum(w.get("training_load") or 0 for w in ws)

    # KPI: Z2 минут в неделю (среднее за 90 дней — сглаживает отпуска)
    z2_per_week = round(_sum_zone(w90, "z2_min") / WINDOW_WEEKS) if w90 else 0
    # KPI: Z4+Z5 высокая интенсивность (не зависит от тега тренировки)
    hiit_per_week = round((_sum_zone(w90, "z4_min") + _sum_zone(w90, "z5_min")) / WINDOW_WEEKS) if w90 else 0
    # KPI: тренировок в неделю (среднее за 90 дней)
    workouts_per_week = round(len(w90) / WINDOW_WEEKS, 1) if w90 else 0
    # KPI: A:C ratio (acute load 7d / chronic avg load per 7d за 90 дней)
    acute_load = _sum_load(w7)
    chronic_load_per_7d = _sum_load(w90) / WINDOW_WEEKS if w90 else 0
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

    # ── per-month buckets (last 3 calendar months for polarized pyramid) ─────
    RU_MONTHS = [
        "январь",
        "февраль",
        "март",
        "апрель",
        "май",
        "июнь",
        "июль",
        "август",
        "сентябрь",
        "октябрь",
        "ноябрь",
        "декабрь",
    ]

    def _month_key(d_str: str) -> str:
        d = _to_date(d_str)
        if not d:
            return ""
        return f"{d.year}-{d.month:02d}"

    def _normalize_to_100(easy: int, mid: int, hard: int) -> tuple[int, int, int]:
        """Корректируем округление чтобы сумма была ровно 100 (или 0 если данных нет)."""
        s = easy + mid + hard
        if s == 0:
            return 0, 0, 0
        if s == 100:
            return easy, mid, hard
        # Дельту прибавляем к самой большой компоненте
        delta = 100 - s
        parts = [("easy", easy), ("mid", mid), ("hard", hard)]
        idx = max(range(3), key=lambda i: parts[i][1])
        adjusted = [easy, mid, hard]
        adjusted[idx] += delta
        return adjusted[0], adjusted[1], adjusted[2]

    window_start = today - timedelta(days=WINDOW_DAYS)

    months_dict: dict = {}
    for w in w90:
        mk = _month_key(w["date"])
        if not mk:
            continue
        d = _to_date(w["date"])
        # Первый день месяца и последний день месяца
        first_of_month = d.replace(day=1)
        if d.month == 12:
            last_of_month = date(d.year + 1, 1, 1) - timedelta(days=1)
        else:
            last_of_month = date(d.year, d.month + 1, 1) - timedelta(days=1)
        # Месяц частичный если окно начинается ПОЗЖЕ первого числа
        # или если последний день месяца ПОЗЖЕ сегодня (текущий месяц)
        partial_from = max(window_start, first_of_month) if window_start > first_of_month else None
        partial_to = today if last_of_month > today else None
        label = RU_MONTHS[d.month - 1]
        if partial_from:
            label = f"{label} · с {partial_from.day}"
        elif partial_to:
            label = f"{label} · по {partial_to.day}"
        b = months_dict.setdefault(
            mk,
            {
                "month": mk,
                "label": label,
                "z1": 0,
                "z2": 0,
                "z3": 0,
                "z4": 0,
                "z5": 0,
                "n": 0,
                "load": 0,
                "mins": 0,
            },
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

    months = sorted(months_dict.values(), key=lambda x: x["month"])
    # round + нормализуем до 100% ровно (для каждой зоны отдельно)
    for b in months:
        for k in ("z1", "z2", "z3", "z4", "z5", "mins"):
            b[k] = round(b[k])
        total = b["z1"] + b["z2"] + b["z3"] + b["z4"] + b["z5"] or 1
        # Сырые проценты для каждой зоны
        raw = {z: b[z] / total * 100 for z in ("z1", "z2", "z3", "z4", "z5")}
        rounded = {z: round(v) for z, v in raw.items()}
        # Корректируем сумму до 100% (отдаём дельту самой большой зоне)
        diff = 100 - sum(rounded.values())
        if diff != 0:
            biggest = max(rounded, key=rounded.get)
            rounded[biggest] += diff
        b["z1_pct"], b["z2_pct"], b["z3_pct"], b["z4_pct"], b["z5_pct"] = (
            rounded["z1"],
            rounded["z2"],
            rounded["z3"],
            rounded["z4"],
            rounded["z5"],
        )
        # Backward compat: easy/mid/hard для старого кода
        e = rounded["z1"] + rounded["z2"]
        m = rounded["z3"]
        h = rounded["z4"] + rounded["z5"]
        b["easy_pct"], b["mid_pct"], b["hard_pct"] = _normalize_to_100(e, m, h)
        b["total_min"] = total

    # ── polarized verdict ────────────────────────────────────────────────────
    total90_z = {z: _sum_zone(w90, f"{z}_min") for z in ("z1", "z2", "z3", "z4", "z5")}
    total90_sum = sum(total90_z.values()) or 1
    easy_pct = (total90_z["z1"] + total90_z["z2"]) / total90_sum * 100
    mid_pct = total90_z["z3"] / total90_sum * 100
    hard_pct = (total90_z["z4"] + total90_z["z5"]) / total90_sum * 100

    if easy_pct >= 75 and hard_pct >= 10 and mid_pct < 15:
        verdict = "polarized"
        verdict_label = "✅ Polarized 80/20 — оптимально"
    elif mid_pct >= 25:
        verdict = "z3_trap"
        verdict_label = "⚠ Z3-trap — слишком много темповой"
    elif hard_pct < 5:
        verdict = "all_easy"
        verdict_label = "⚠ Мало интервалов на высоком пульсе"
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
        # 5 зон отдельно — ключ для отрисовки полосок
        raw5 = {f"z{i}": z.get(f"z{i}_min", 0) / total * 100 for i in range(1, 6)}
        rounded5 = {k: round(v) for k, v in raw5.items()}
        diff = 100 - sum(rounded5.values())
        if diff != 0:
            biggest = max(rounded5, key=rounded5.get)
            rounded5[biggest] += diff
        # Backward compat
        e = rounded5["z1"] + rounded5["z2"]
        m = rounded5["z3"]
        h = rounded5["z4"] + rounded5["z5"]
        easy_p, mid_p, hard_p = _normalize_to_100(e, m, h)
        item = {
            "date": w.get("date"),
            "type": w.get("type"),
            "type_label": w.get("type_label", w.get("type", "")),
            "duration_min": round(w.get("duration_min") or 0),
            "avg_hr": round(w.get("avg_hr") or 0),
            "z1_pct": rounded5["z1"],
            "z2_pct": rounded5["z2"],
            "z3_pct": rounded5["z3"],
            "z4_pct": rounded5["z4"],
            "z5_pct": rounded5["z5"],
            "easy_pct": easy_p,
            "mid_pct": mid_p,
            "hard_pct": hard_p,
            "load": w.get("training_load") or 0,
            "is_misnamed": w.get("is_misnamed", False),
            "suggested_type": w.get("suggested_type"),
            "high_zone_pct": w.get("high_zone_pct", 0),
            "is_synthesized": w.get("is_synthesized", False),
        }
        if item["is_misnamed"]:
            misnamed_count += 1
        workout_list.append(item)

    # ── HR-zones bpm границы (мульти-юзерно: от user_age) ─────────────────
    # Используется в текстах рекомендаций. Для юзера без birth_date — среднее 49.
    _max_hr = (220 - user_age) if user_age else (220 - 49)
    _z2_bottom = round(_max_hr * 0.60)
    _z2_top = round(_max_hr * 0.70)
    _z4_bottom = round(_max_hr * 0.80)
    _z4_norway = round(_max_hr * 0.90)

    # ── recommendations ──────────────────────────────────────────────────────
    # Флаг: была ли недавно качественная Z2-сессия (на основе good_z2 логики ниже).
    # Считается тут заранее, чтобы избежать дубля с recs.insert(0,...) в работающей секции.
    _last_good_z2_days = None
    _z2_quality_pre = [
        w for w in w90 if w.get("type") in ("running", "cycling") and w.get("hr_zones", {}).get("z2_min", 0) > 0
    ]
    _good_z2_pre = []
    for w in _z2_quality_pre:
        z = w.get("hr_zones", {}) or {}
        if z.get("z2_min", 0) / (sum(z.values()) or 1) > 0.7:
            _good_z2_pre.append(w)
    if _good_z2_pre:
        try:
            _last_good_z2_days = (today - max(date.fromisoformat(w["date"]) for w in _good_z2_pre)).days
        except Exception:
            _last_good_z2_days = None

    recs = []
    if z2_per_week < 75:
        deficit = 150 - z2_per_week
        # Не дублируем «Z2 пауза» если запись «возобновить Z2» уже добавится ниже.
        if _last_good_z2_days is None or _last_good_z2_days <= 30:
            recs.append(
                f"Добавь Z2: сейчас {z2_per_week} мин/нед, цель 150. "
                f"2 пробежки/велик по 30–45 мин на пульсе {_z2_bottom}–{_z2_top} закроют дефицит {deficit} мин."
            )
    if hiit_per_week < 8:
        recs.append(
            f"Добавь острые интервалы: Z4+Z5 сейчас {hiit_per_week} мин/нед, цель 16. "
            f"Норвежский протокол 4×4: четыре повтора по 4 мин на 90% maxHR (≥{_z4_norway} bpm) "
            f"с 3 мин восстановления между. Раз в неделю."
        )
    if misnamed_count > 0:
        recs.append(
            f"Переназови {misnamed_count} «ВИИТ» в Garmin → «Сил. трен.». "
            "Это силовые/функционалка, не интервалы — Garmin корректнее посчитает "
            "Body Battery, Training Status и оценку VO2max."
        )
    if ac_ratio is not None and ac_ratio < 0.8:
        recs.append(
            "Острая нагрузка (за 7 дней) ниже базовой (среднее за 90 дней) — "
            "есть запас, можно безопасно прибавить 15–20% объёма эту неделю."
        )
    if ac_ratio is not None and ac_ratio > 1.3:
        recs.append(
            "Острая нагрузка (за 7 дней) выше базовой — риск перегруза. Снизь интенсивность 1–2 дня для восстановления."
        )
    if not recs:
        recs.append("Тренировочный план сбалансирован. Держи ритм.")

    # ── what's working (positive observations) ───────────────────────────────
    # ВАЖНО: только объективные факты с реальной полезностью. Не льстим, не дублируем.
    # Каждый пункт должен показывать ОТДЕЛЬНОЕ полезное качество тренировок:
    #   - регулярность (consistency) — отсутствие пропусков
    #   - тип нагрузки (силовые после 45 — anti-sarcopenia)
    #   - качество тренировок (реальный анаболический стимул)
    works = []

    # 1. Регулярность силовых (после 45 — главное для anti-sarcopenia)
    # Объединяем «ритм» + «без провалов» в один пункт про силовые,
    # потому что это самое значимое по доказательной базе для возраста 45+.
    strength_w90 = [w for w in w90 if w.get("type") in ("strength_training", "hiit")]
    strength_per_week = round(len(strength_w90) / 13, 1)  # 90/7 = ~13 недель
    months_with_data = [m for m in months if m.get("n", 0) > 0]
    has_regular_strength = strength_per_week >= 2 and len(strength_w90) >= 18
    has_no_gaps = len(months_with_data) >= 3 and all(m.get("n", 0) >= 5 for m in months_with_data)

    if has_regular_strength and has_no_gaps:
        # Лучший случай — и регулярно, и без провалов
        works.append(
            f"Силовые {strength_per_week}/нед, без пропусков "
            f"({len(strength_w90)} тренировок за 90 дн, {len(months_with_data)} месяцев подряд) — "
            f"ключевой фактор сохранения мышц после 45"
        )
    elif has_regular_strength:
        works.append(
            f"Силовые {strength_per_week}/нед ({len(strength_w90)} за 90 дн) — ключевой фактор сохранения мышц после 45"
        )
    elif workouts_per_week >= 2.5:
        # Fallback: общая регулярность если нет именно силовых
        works.append(f"Стабильный ритм: {workouts_per_week} тренировок/нед в среднем за 90 дней")

    # 2. Качество силовых: средний Anaerobic TE — реальный стимул для роста
    anaer_te = [w.get("anaerobic_te") for w in strength_w90 if w.get("anaerobic_te")]
    if anaer_te:
        avg_anaer = round(sum(anaer_te) / len(anaer_te), 1)
        n_improving = sum(1 for v in anaer_te if v >= 2.5)
        if avg_anaer >= 2.5 or n_improving >= len(anaer_te) * 0.4:
            works.append(
                f"Силовые с реальным анаболическим стимулом: средний Anaerobic TE {avg_anaer}, "
                f"в {n_improving}/{len(anaer_te)} тренировок попадаешь в «improving» (TE≥2.5)"
            )
    # Detect well-tagged Z2 sessions (running/cycling with >70% in Z2)
    z2_quality = [
        w for w in w90 if w.get("type") in ("running", "cycling") and w.get("hr_zones", {}).get("z2_min", 0) > 0
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
            # Динамическая подпись: только реально присутствующие типы (бег / велик / оба)
            types_present = {w.get("type") for w in good_z2}
            type_label_map = {"running": "Беговые", "cycling": "Велосипедные"}
            type_str = " / ".join(type_label_map.get(t, t) for t in sorted(types_present)) or "Кардио"
            avg_min = round(sum(w.get("duration_min", 0) for w in good_z2) / len(good_z2))
            # Свежесть: если последняя такая сессия >30 дней назад — это уже не «работает»,
            # а исторический факт. Переносим в «что менять».
            try:
                last_z2_date = max(date.fromisoformat(w["date"]) for w in good_z2)
                days_since = (today - last_z2_date).days
            except Exception:
                days_since = 0
            if days_since <= 30:
                works.append(f"{type_str} в правильной Z2: {len(good_z2)} сессий, средне {avg_min} мин")
            else:
                # Не «работает», а «работало». Переносим в рекомендации (recs)
                # с конкретным планом и цифрами дефицита.
                _z2_deficit = max(0, 150 - z2_per_week)
                recs.insert(
                    0,
                    f"Возобновить Z2-кардио: последняя качественная Z2-сессия была {days_since} дней назад "
                    f"({last_z2_date.isoformat()}). Сейчас {z2_per_week} мин/нед при цели 150 — дефицит {_z2_deficit} мин/нед. "
                    f"План: 2 пробежки/велик по 30-45 мин на пульсе {_z2_bottom}-{_z2_top} в неделю. "
                    f"Раньше получалось — в среднем {avg_min} мин по {len(good_z2)} тренировкам.",
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
        "months": months,
        "polarized": {
            "easy_pct": _normalize_to_100(round(easy_pct), round(mid_pct), round(hard_pct))[0],
            "mid_pct": _normalize_to_100(round(easy_pct), round(mid_pct), round(hard_pct))[1],
            "hard_pct": _normalize_to_100(round(easy_pct), round(mid_pct), round(hard_pct))[2],
            # Все 5 зон отдельно — для подробного дисплея
            "z1_pct": round(total90_z["z1"] / total90_sum * 100),
            "z2_pct": round(total90_z["z2"] / total90_sum * 100),
            "z3_pct": round(total90_z["z3"] / total90_sum * 100),
            "z4_pct": round(total90_z["z4"] / total90_sum * 100),
            "z5_pct": round(total90_z["z5"] / total90_sum * 100),
            "verdict": verdict,
            "verdict_label": verdict_label,
            "ideal": {"easy": 80, "mid": 5, "hard": 15},
            "total_min": round(total90_sum),
        },
        "workouts": workout_list,
        "misnamed_count": misnamed_count,
        "works": works,
        "recommendations": recs,
        "window_days": WINDOW_DAYS,
        "window_workouts": len(w90),
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
    alco_kcal: dict[str, int] = {}  # calories from alcohol per day
    # Полный плоский список продуктов с датами — для MEDAS-калькулятора (LE8 диета)
    nutrition_items_flat: list[dict] = []

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
                if not isinstance(item, dict):
                    continue
                name_lower = str(item.get("food", "")).lower()
                is_alco = any(kw in name_lower for kw in _alco_kw_substr) or bool(_alco_kw_word_re.search(name_lower))
                if is_alco:
                    if d not in alco_days:
                        alco_days.append(d)
                    item_kcal = int(item.get("calories") or 0)
                    if item_kcal > 0:
                        alco_kcal[d] = alco_kcal.get(d, 0) + item_kcal
                # Накапливаем для MEDAS — с датой, чтобы скоринг работал по rolling window
                food_name = (item.get("food") or item.get("name") or "").strip()
                grams = float(item.get("amount") or item.get("weight") or 0)
                if food_name and grams > 0:
                    nutrition_items_flat.append({"date": d, "food": food_name, "amount": grams})

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
    # Названия как в русском Garmin Connect.
    _WORKOUT_LABELS = {
        "hiit": "ВИИТ",
        "yoga": "Йога",
        "running": "Бег",
        "walking": "Ходьба",
        "cycling": "Велосипед",
        "swimming": "Плавание",
        "open_water_swimming": "Плавание",
        "indoor_running": "Бег",
        "treadmill_running": "Бег",
        "strength": "Силовая",
        "strength_training": "Силовая",
        "cardio": "Кардио",
        "fitness_equipment": "Тренажёр",
        "other": "Прочее",
    }
    # Only running/walking/cycling/swimming have meaningful distance
    _DISTANCE_TYPES = {
        "running",
        "walking",
        "cycling",
        "swimming",
        "open_water_swimming",
        "indoor_running",
        "treadmill_running",
    }
    _breakdown: dict = {}
    for a in activities:
        # Нормализуем тип в человеческий лейбл, чтобы 'strength' и 'strength_training'
        # схлопывались в одну строку «Силовая».
        t_raw = a["type"]
        label = _WORKOUT_LABELS.get(t_raw, t_raw.replace("_", " ").capitalize())
        if label not in _breakdown:
            _breakdown[label] = {"n": 0, "km": 0.0, "is_dist": t_raw in _DISTANCE_TYPES}
        _breakdown[label]["n"] += 1
        if t_raw in _DISTANCE_TYPES and a.get("distance_km"):
            _breakdown[label]["km"] += a["distance_km"]
    # Сортируем по частоте
    sorted_breakdown = sorted(
        [
            {
                "label": label,
                "n": v["n"],
                "km": round(v["km"], 1) if v["km"] > 0 else 0,
            }
            for label, v in _breakdown.items()
        ],
        key=lambda x: -x["n"],
    )
    # Топ-3 + «Остальное» (агрегат всего что не вошло)
    if len(sorted_breakdown) <= 4:
        activity_breakdown = sorted_breakdown
    else:
        top3 = sorted_breakdown[:3]
        rest = sorted_breakdown[3:]
        rest_n = sum(item["n"] for item in rest)
        rest_km = round(sum(item["km"] for item in rest), 1)
        activity_breakdown = top3 + [{"label": "Остальное", "n": rest_n, "km": rest_km if rest_km > 0 else 0}]

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
        "prot_target": {"bariatric": 140, "cardiac": 100, "female-cycle": 75, "generic": 80}.get(
            user.pack_name or "generic", 80
        ),  # g/day, pack-specific
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
        "AST": {"val": bv("AST"), "date": bd("AST"), "unit": "Ед/л", "ok": 40},
        "GGT": {"val": bv("GGT"), "date": bd("GGT"), "unit": "Ед/л", "ok": 35},
        "TSH": {"val": bv("TSH"), "date": bd("TSH"), "unit": "мМЕ/л", "ok": 4.0},
        "creatinine": {"val": bv("creatinine"), "date": bd("creatinine"), "unit": "мкмоль/л", "ok": 110},
        "uric_acid": {"val": bv("uric_acid"), "date": bd("uric_acid"), "unit": "мкмоль/л", "ok": 420},
        "hs_CRP": {"val": bv("hs_CRP"), "date": bd("hs_CRP"), "unit": "мг/л", "ok": 1.0},
        "NT_proBNP": {"val": bv("NT_proBNP"), "date": bd("NT_proBNP"), "unit": "пг/мл", "ok": 125},
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
                "note": (
                    f"{bv('ApoB')} → выше цели. Снижение через диету и при необходимости статины."
                    if bv("ApoB") and bv("ApoB") > 0.9
                    else None
                ),
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
                "note": (
                    f"{_homa} → погранично. Цель: <1.5 через ↓ простые углеводы."
                    if _homa and 1.5 <= _homa < 2.5
                    else (f"{_homa} → выше нормы. Риск инсулинорезистентности." if _homa and _homa >= 2.5 else None)
                ),
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
                "note": (
                    f"= {_testo_nmol} нмоль/л. Целевой диапазон Attia: >500 нг/дл (~17.3 нмоль/л)."
                    if _testo_nmol is not None
                    else None
                ),
            },
            {
                "name": "IGF-1",
                "category": "Гормон роста · долголетие",
                "val": None,
                "unit": "нг/мл",
                "target": "100–250 нг/мл",
                "status": "missing",
                "date": None,
                "note": None,
            },
            {
                "name": "DHEA-S",
                "category": "Гормоны надпочечников",
                "val": None,
                "unit": "мкмоль/л",
                "target": "5–13 мкмоль/л",
                "status": "missing",
                "date": None,
                "note": None,
            },
        ],
    }

    # --- Panel 2: Metabolic Syndrome (NCEP ATP III) ---
    _bp_avg_sys = round(sum(bp_sys.values()) / len(bp_sys)) if bp_sys else None
    _bp_avg_dia = round(sum(bp_dia.values()) / len(bp_dia)) if bp_dia else None
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
                "note": ("NCEP ✓ / IDF ⚠ (>94 см)" if _waist is not None and _waist > 94 else None),
            },
            {
                "name": "Триглицериды",
                "val": _tg,
                "unit": "ммоль/л",
                "threshold": "<1.7 ммоль/л",
                "pass": _tg is not None and _tg < 1.7,
                "note": ("Отличный уровень" if _tg is not None else None),
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
                "val": f"{_bp_avg_sys}/{_bp_avg_dia}" if _bp_avg_sys is not None else None,
                "unit": "мм рт.ст.",
                "threshold": "<130/85 мм рт.ст.",
                "pass": bool(_bp_avg_sys and _bp_avg_dia and _bp_avg_sys < 130 and _bp_avg_dia < 85),
                "note": "Среднее за период наблюдения" if _bp_avg_sys is not None else None,
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

    # 1. Diet — настоящий MEDAS (Mediterranean Diet Adherence Screener, PREDIMED 2011).
    #    Считаем по последним 30 дням rolling window — отражает текущие пищевые привычки.
    #    Для users с малым логом (<7 дней) — fallback на старую заглушку (kcal+protein%).
    from core.health.medas import compute_medas

    _prot_avg_le8 = round(sum(prot.values()) / len(prot), 1) if prot else 0
    _kcal_avg_le8 = round(sum(kcal.values()) / len(kcal)) if kcal else 0
    _prot_pct_le8 = round((_prot_avg_le8 * 4) / max(_kcal_avg_le8, 1) * 100, 1)

    # Окно MEDAS: последние 30 дней (или меньше если данных меньше)
    _medas_window_days = 30
    _medas_cutoff = today - timedelta(days=_medas_window_days)
    _medas_items = [it for it in nutrition_items_flat if it["date"] >= _medas_cutoff.isoformat()]
    _medas_unique_dates = len({it["date"] for it in _medas_items})

    _diet_score: int | None
    _medas_result: dict | None = None
    if _medas_unique_dates >= 7:
        # Достаточно данных для MEDAS
        _medas_result = compute_medas(_medas_items, n_days=_medas_window_days, skip_wine_rule=True)
        _diet_score = _medas_result["score_100"]
    elif _kcal_avg_le8 > 0:
        # Fallback на старую упрощённую формулу (мало данных в логе)
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
    #    AHA LE8: vigorous активность считается ×2 от moderate.
    #    Считаем тренировку как vigorous, если средний пульс ≥70% MaxHR (≈120 bpm для 49yo)
    #    или явно vigorous-тип (HIIT, бег, силовая с заходом в Z3+).
    _act_moderate_min = 0.0  # минут × 1
    _act_vigorous_min = 0.0  # минут × 1 (потом удвоим в финальной сумме MET-эквивалента)
    for a in activities:
        dur = a.get("duration_min", 0) or 0
        avg_hr = a.get("avg_hr") or a.get("averageHR") or 0
        atype = (a.get("type") or a.get("activity_type") or "").lower()
        # Жёсткий критерий vigorous: либо тип-маркер, либо HR ≥120 bpm в среднем
        is_vigorous = avg_hr >= 120 or any(k in atype for k in ("hiit", "running", "виит", "бег", "interval"))
        if is_vigorous:
            _act_vigorous_min += dur
        else:
            _act_moderate_min += dur
    # AHA эквивалент: vigorous-минуты ×2 для MET-target.
    _act_equiv_week = (_act_moderate_min + _act_vigorous_min * 2) / _total_weeks
    _act_min_week = (_act_moderate_min + _act_vigorous_min) / _total_weeks  # для дисплея сырая сумма
    if _act_equiv_week >= 300:
        _pa_score = 100
    elif _act_equiv_week >= 150:
        _pa_score = round(80 + 20 * (_act_equiv_week - 150) / 150)
    elif _act_equiv_week >= 1:
        _pa_score = max(20, round(80 * _act_equiv_week / 150))
    else:
        _pa_score = 0

    # 3. Nicotine — читаем User.smoking_status (мульти-юзер).
    # AHA LE8 шкала: never→100, former_5plus→75, former_1to5→50, former_lt1→25, current→0.
    _smoking_status = getattr(user, "smoking_status", None)
    _smoking_score_map = {
        "never": 100,
        "former_5plus": 75,
        "former_1to5": 50,
        "former_lt1": 25,
        "current": 0,
    }
    _smoking_score: int | None = _smoking_score_map.get(_smoking_status)
    _smoking_label_map = {
        "never": "Никогда не курил",
        "former_5plus": "Бросил ≥5 лет назад",
        "former_1to5": "Бросил 1-5 лет назад",
        "former_lt1": "Бросил <1 года назад",
        "current": "Курит сейчас",
    }
    _smoking_val = _smoking_label_map.get(_smoking_status, "нет данных")

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
    # AHA LE8 (2022) точная шкала по 5 категориям:
    #   <120/<80 optimal → 100
    #   120-129/<80 elevated → 75
    #   130-139/80-89 Stage 1 → 50
    #   140-159/90-99 Stage 2 → 25
    #   ≥160/≥100 severe → 0
    # Берём ХУДШУЮ из систолы/диастолы (как и AHA — категория определяется по самой плохой).
    _sbp_le8 = _bp_avg_sys
    _dbp_le8 = _bp_avg_dia
    if _sbp_le8 is None or _dbp_le8 is None:
        _bp_score_le8 = None
    else:
        # Категория по систоле
        if _sbp_le8 < 120:
            _sbp_cat = 100
        elif _sbp_le8 < 130:
            _sbp_cat = 75
        elif _sbp_le8 < 140:
            _sbp_cat = 50
        elif _sbp_le8 < 160:
            _sbp_cat = 25
        else:
            _sbp_cat = 0
        # Категория по диастоле
        if _dbp_le8 < 80:
            _dbp_cat = 100
        elif _dbp_le8 < 90:
            # 80-89 → ловушка: пограничная elevated/Stage 1
            # AHA: при DBP 80-89 идёт уже Stage 1 если SBP тоже ≥130, иначе elevated
            _dbp_cat = 50 if _sbp_le8 >= 130 else 75
        elif _dbp_le8 < 100:
            _dbp_cat = 25
        else:
            _dbp_cat = 0
        # Берём минимум (худшую категорию)
        _bp_score_le8 = min(_sbp_cat, _dbp_cat)

    # Сборка детализации диеты для UI
    if _medas_result is not None:
        _diet_val = (
            f"MEDAS {_medas_result['points']}/{_medas_result['max_points']} правил · "
            f"{_kcal_avg_le8} ккал/д · белка {_prot_pct_le8}%"
        )
        # Что не выполнено — топ-3 для подсказки
        _failed = [(label, detail) for (label, ok, detail) in _medas_result["items_for_score"] if not ok][:3]
        _failed_str = "; ".join(label for label, _ in _failed) if _failed else "всё выполнено 🎉"
        _diet_note = f"Mediterranean Diet Score (PREDIMED). Не дотягивает: {_failed_str}"
    else:
        _diet_val = f"~{_prot_pct_le8}% белка, {_kcal_avg_le8} ккал/д"
        _diet_note = (
            "приблизительно — мало данных в логе (нужно ≥7 дней для MEDAS)"
            if _medas_unique_dates < 7
            else "приблизительно — нет разбора по продуктам"
        )

    _le8_components = {
        "diet": {
            "score": _diet_score,
            "val": _diet_val,
            "target": "Средиземноморский тип: овощи, фрукты, рыба, орехи, оливковое масло",
            "note": _diet_note,
            "medas_details": _medas_result,  # для возможного развёрнутого тултипа
            "date": None,
        },
        "activity": {
            "score": _pa_score,
            "val": f"~{round(_act_min_week)} мин/нед (эквивалент {round(_act_equiv_week)} с учётом vigorous ×2)",
            "target": "≥150 мин умеренной / ≥75 мин интенсивной",
            "note": f"{len(activities)} тренировок за период · vigorous: ~{round(_act_vigorous_min / _total_weeks)} мин/нед",
            "date": None,
        },
        "smoking": {
            "score": _smoking_score,
            "val": _smoking_val,
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
            "target": f"ИМТ <25{('  (≈' + str(round(25 * (user.height_cm / 100) ** 2)) + ' кг при росте ' + str(user.height_cm) + ' см)') if user.height_cm else ''}",
            "note": None,
            "date": bd("ApoB"),  # use latest blood-draw date as proxy
        },
        "glucose": {
            "score": _glc_score,
            "val": f"HbA1c {_hba1c_le8}%" if _hba1c_le8 is not None else None,
            "target": "HbA1c <5.7%",
            "note": None,
            "date": bd("HbA1c"),
        },
        "lipids": {
            "score": _lip_score,
            "val": f"non-HDL {_non_hdl_le8} ммоль/л" if _non_hdl_le8 is not None else None,
            "target": "non-HDL <2.6 ммоль/л  (ApoB <0.9 — приоритет)",
            "note": None,
            "date": bd("cholesterol_total"),
        },
        "bp": {
            "score": _bp_score_le8,
            "val": f"{_sbp_le8}/{_dbp_le8} мм рт.ст." if _sbp_le8 is not None else None,
            "target": "<120/80 мм рт.ст.",
            "note": "среднее за период наблюдения" if _sbp_le8 is not None else None,
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
    # 9 biomarkers; direction vs NHANES median for age ~48 male.
    # Каждый маркер хранит value + date — дата нужна для проверки свежести.
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

    # Даты каждого из 9 маркеров — для отображения и проверки свежести
    _pheno_dates = {
        "albumin": bd("albumin_g_l"),
        "creatinine": bd("creatinine"),
        "glucose": bd("glucose"),
        "hs_CRP": bd("hs_CRP"),
        "lymphocytes": bd("lymphocytes"),
        "MCV": bd("MCV"),
        "RDW": bd("RDW_CV"),
        "ALP": bd("ALP"),
        "WBC": bd("WBC"),
    }

    # Сколько дней назад был сделан замер (для алертов «> 24 мес»)
    def _days_ago(date_str: str | None) -> int | None:
        if not date_str or date_str == "—":
            return None
        try:
            return (today - date.fromisoformat(date_str)).days
        except Exception:
            return None

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

    def _stale_label(days: int | None) -> str | None:
        """Метка устаревания: если ≤ 12 мес — None, иначе подпись."""
        if days is None or days <= 365:
            return None
        if days <= 730:
            return f"⚠ {days // 30} мес назад"
        return f"🚨 {round(days / 365, 1)} года назад"

    _pheno_markers = [
        {
            "name": "Альбумин",
            "val": _alb_gdl,
            "unit": "г/дл",
            "direction": _pheno_dir(_alb_gdl, 4.2, higher_is_younger=True),
            "date": _pheno_dates["albumin"],
            "stale_note": _stale_label(_days_ago(_pheno_dates["albumin"])),
            "note": None,
        },
        {
            "name": "Креатинин",
            "val": _creat_mgdl,
            "unit": "мг/дл",
            "direction": _pheno_dir(_creat_mgdl, 1.05),
            "date": _pheno_dates["creatinine"],
            "stale_note": _stale_label(_days_ago(_pheno_dates["creatinine"])),
        },
        {
            "name": "Глюкоза",
            "val": _glc_mgdl,
            "unit": "мг/дл",
            "direction": _pheno_dir(_glc_mgdl, 95),
            "date": _pheno_dates["glucose"],
            "stale_note": _stale_label(_days_ago(_pheno_dates["glucose"])),
        },
        {
            "name": "ln(CRP)",
            "val": _crp_ln,
            "unit": "",
            "direction": _pheno_dir(_crp_ln, 0.0),
            "date": _pheno_dates["hs_CRP"],
            "stale_note": _stale_label(_days_ago(_pheno_dates["hs_CRP"])),
        },
        {
            "name": "Лимфоциты",
            "val": _lymph_pct,
            "unit": "%",
            "direction": _pheno_dir(_lymph_pct, 28, higher_is_younger=True),
            "date": _pheno_dates["lymphocytes"],
            "stale_note": _stale_label(_days_ago(_pheno_dates["lymphocytes"])),
        },
        {
            "name": "MCV",
            "val": _mcv,
            "unit": "фл",
            "direction": _pheno_dir(_mcv, 90),
            "date": _pheno_dates["MCV"],
            "stale_note": _stale_label(_days_ago(_pheno_dates["MCV"])),
        },
        {
            "name": "RDW",
            "val": _rdw,
            "unit": "%",
            "direction": _pheno_dir(_rdw, 13.8),
            "date": _pheno_dates["RDW"],
            "stale_note": _stale_label(_days_ago(_pheno_dates["RDW"])),
        },
        {
            "name": "ALP",
            "val": _alp,
            "unit": "Ед/л",
            "direction": _pheno_dir(_alp, 68),
            "date": _pheno_dates["ALP"],
            "stale_note": _stale_label(_days_ago(_pheno_dates["ALP"])),
        },
        {
            "name": "Лейкоциты",
            "val": _wbc,
            "unit": "×10³/мкл",
            "direction": _pheno_dir(_wbc, 6.7),
            "date": _pheno_dates["WBC"],
            "stale_note": _stale_label(_days_ago(_pheno_dates["WBC"])),
        },
    ]
    _younger_count = sum(1 for m in _pheno_markers if m["direction"] == "younger")
    # Список устаревших маркеров (для пометки расчёта как ненадёжного)
    _stale_markers = [m for m in _pheno_markers if m.get("stale_note")]

    # Расчёт биовозраста по формуле Levine 2018 (Aging Cell).
    # Требуются ВСЕ 9 маркеров + возраст. Если хоть один отсутствует — биовозраст None.
    _bio_age = None
    _bio_age_note_extra = ""
    _crp_raw_mgL = bv("hs_CRP")
    _all_markers_present = all(
        v is not None
        for v in [_alb_gdl, _creat_mgdl, _glc_mgdl, _crp_raw_mgL, _lymph_pct, _mcv, _rdw, _alp, _wbc, _age_score]
    )
    if _all_markers_present and _crp_raw_mgL > 0:
        try:
            # Конверсия в единицы формулы (g/L, µmol/L, mmol/L)
            _alb_gL = _alb_gdl * 10
            _creat_umolL = _creat_mgdl * 88.4
            _gluc_mmolL = _glc_mgdl / 18.0182
            # Levine использует ln(CRP в mg/dL) = ln(CRP_mgL × 0.1)
            _lncrp = math.log(_crp_raw_mgL * 0.1)

            _xb = (
                -19.907
                + 0.0804 * _age_score
                + (-0.0336) * _alb_gL
                + 0.0095 * _creat_umolL
                + 0.1953 * _gluc_mmolL
                + 0.0954 * _lncrp
                + (-0.0120) * _lymph_pct
                + 0.0268 * _mcv
                + 0.3306 * _rdw
                + (-0.00188) * _alp
                + 0.0554 * _wbc
            )
            _mort = 1 - math.exp(-math.exp(_xb) * (math.exp(0.0076927 * 120) - 1) / 0.0076927)
            # Защита от ln(0) если M очень близко к 0
            if 0 < _mort < 1:
                _bio_age = round(141.50225 + math.log(-0.00553 * math.log(1 - _mort)) / 0.090165, 1)
        except (ValueError, OverflowError) as e:
            _bio_age_note_extra = f" [расчёт не удался: {e}]"

    # Сборка ноты с явной информацией о свежести данных
    if _stale_markers:
        _stale_list = ", ".join(f"{m['name']} ({m['date']})" for m in _stale_markers)
        if _bio_age is not None:
            _pheno_note = (
                f"⚠ Расчёт неточный — устаревшие маркеры: {_stale_list}. "
                f"Сейчас: ~{_bio_age} лет (паспорт {_age_score}), {_younger_count}/9 «моложе» медианы. "
                f"Для надёжного результата сдай заново эти маркеры."
            )
            _bio_age_quality = "stale"
        else:
            _pheno_note = (
                f"⚠ Часть маркеров устарела ({_stale_list}). Сейчас: {_younger_count}/9 «моложе» медианы. "
                f"Для расчёта биовозраста сдай свежие маркеры."
            )
            _bio_age_quality = "no_data"
    elif _bio_age is not None:
        _pheno_note = (
            f"Биологический возраст по 9-маркерной формуле Levine 2018: ~{_bio_age} лет "
            f"(паспорт {_age_score}). {_younger_count}/9 маркеров «моложе» медианы NHANES."
        )
        _bio_age_quality = "fresh"
    else:
        _pheno_note = (
            f"Направленная оценка: {_younger_count}/9 маркеров «моложе» медианы NHANES. "
            f"Для расчёта биовозраста нужны все 9 маркеров.{_bio_age_note_extra}"
        )
        _bio_age_quality = "no_data"

    panels_phenoage = {
        "source": "Levine et al. 2018, Aging Cell",
        "source_url": "https://doi.org/10.18632/aging.101414",
        "chrono_age": _age_score,
        "bio_age_est": _bio_age,
        "bio_age_quality": _bio_age_quality,  # "fresh" | "stale" | "no_data"
        "bio_age_range": None,
        "younger_count": _younger_count,
        "markers": _pheno_markers,
        "stale_markers": [m["name"] for m in _stale_markers],
        "note": _pheno_note,
    }

    # --- Panel 5: SCORE2 (ESC 2021) — 10-летний риск ССЗ ---
    # Мульти-юзерно: пол из user.sex, возраст из user.birth_date, курение из user.smoking_status
    from core.health.cv_risk import calc_score2, calc_ascvd_lifetime

    panels_score2: dict | None = None
    panels_ascvd: dict | None = None
    if _age_score and user.sex and bv("cholesterol_total") and bv("HDL") and _bp_avg_sys is not None:
        _is_smoker = user.smoking_status == "current"
        _score2 = calc_score2(
            age=_age_score,
            sex=user.sex,
            smoking=_is_smoker,
            sbp_mmhg=_bp_avg_sys,
            tchol_mmolL=bv("cholesterol_total"),
            hdl_mmolL=bv("HDL"),
            region="high",  # Россия = high-risk регион ESC. TODO: настраивать по user.country
        )
        if _score2:
            panels_score2 = {
                "available": True,
                **_score2,
                "no_data_reason": None,
            }
        # ASCVD Lifetime — также мульти-юзерно
        # Diabetes: HbA1c >=6.5 ИЛИ глюкоза >=7.0 как proxy
        _diabetes = bool((bv("HbA1c") and bv("HbA1c") >= 6.5) or (bv("glucose") and bv("glucose") >= 7.0))
        _ascvd = calc_ascvd_lifetime(
            age=_age_score,
            sex=user.sex,
            smoking=_is_smoker,
            sbp_mmhg=_bp_avg_sys,
            tchol_mmolL=bv("cholesterol_total"),
            hdl_mmolL=bv("HDL"),
            diabetes=_diabetes,
            on_bp_meds=False,  # TODO: брать из user.medications когда поле появится
        )
        if _ascvd:
            panels_ascvd = {
                "available": True,
                **_ascvd,
                "no_data_reason": None,
            }
    if panels_score2 is None:
        panels_score2 = {
            "available": False,
            "no_data_reason": "Нужны: возраст, пол, давление, общий холестерин, ЛПВП. "
            "Возрастной диапазон SCORE2: 40-69 лет.",
        }
    if panels_ascvd is None:
        panels_ascvd = {
            "available": False,
            "no_data_reason": "Нужны: возраст, пол, давление, общий холестерин, ЛПВП.",
        }

    # Свежая мышечная масса для шапки дашборда (не дублирует панели —
    # просто дополняет плашку «% Жира» в hero-grid). Берём последний замер
    # из weights table где muscle_mass не null.
    muscle_last_kg: float | None = None
    if stats_weight and stats_weight.get("last") is not None:
        _muscle_row = _rows(
            db,
            """
            SELECT muscle_mass FROM weights
            WHERE user_id=:uid AND muscle_mass IS NOT NULL
            ORDER BY measured_at DESC LIMIT 1
            """,
            uid=user_id,
        )
        if _muscle_row:
            muscle_last_kg = float(_muscle_row[0].muscle_mass)

    # ── HERO PRIORITY: динамический выбор ключевого маркера для шапки ────
    # Логика: первое попадание выигрывает. Critical (красный) > Watch (жёлтый) > Win (зелёный).
    # Мульти-юзерно: если у пользователя нет данных по конкретному маркеру — пропускаем.
    # Идея: показывать в шапке ТО, что сейчас требует работы / является главным риском.
    hero_priority: dict = {
        "title": "Биомаркеры",
        "value": "—",
        "unit": "",
        "sub": "сдай анализы для приоритизации",
        "color": "muted",
        "marker_type": "no_data",
    }

    _hba1c = bv("HbA1c")
    _apob = bv("ApoB")
    _ldl = bv("LDL")
    _homa = bv("HOMA_index")
    _visc_last = list(visceral.values())[-1] if visceral else None
    # _bio_age и _bio_age_quality уже вычислены выше в Panel 4 (PhenoAge)

    def _set_hero(title, value, unit, sub, color, mtype):
        hero_priority.update(
            {
                "title": title,
                "value": value,
                "unit": unit,
                "sub": sub,
                "color": color,
                "marker_type": mtype,
            }
        )

    # ── 1. КРИТИЧЕСКИЕ (red) — требуют срочного внимания ──
    if _hba1c is not None and _hba1c >= 6.5:
        _set_hero("HbA1c · Диабет 2 типа", f"{_hba1c}", "%", "цель <5.7 · обсудить с врачом метформин", "r", "hba1c_dm")
    elif _apob is not None and _apob >= 1.3:
        _set_hero("ApoB · Высокий", f"{_apob}", "г/л", "цель <0.9 · обсудить статины с кардиологом", "r", "apob_high")
    elif _ldl is not None and _ldl >= 4.0 and _apob is None:
        _set_hero("LDL · Высокий", f"{_ldl}", "ммоль/л", "цель <3.0 · сдать ApoB и обсудить статины", "r", "ldl_high")
    elif _bp_avg_sys is not None and _bp_avg_sys >= 140:
        _set_hero(
            "АД · Гипертония 2 ст.",
            f"{round(_bp_avg_sys)}/{round(_bp_avg_dia)}",
            "мм рт.ст.",
            "обсудить с врачом, цель <130/80",
            "r",
            "bp_high",
        )
    elif _homa is not None and _homa >= 2.5:
        _set_hero(
            "HOMA-IR · Резистентность", f"{_homa}", "", "цель <1.5 · убрать сладкое + Z2-кардио", "r", "homa_high"
        )
    # ── 2. ПОГРАНИЧНЫЕ (yellow) — главное в работе ──
    elif _hba1c is not None and _hba1c >= 5.7:
        _set_hero("HbA1c · Преддиабет", f"{_hba1c}", "%", "цель <5.7 · сладкое ↓, кардио ↑", "y", "hba1c_pre")
    elif _apob is not None and _apob >= 0.9:
        _set_hero(
            "ApoB · Атерогенные частицы",
            f"{_apob}",
            "г/л",
            f"выше цели <0.9 · LDL {_ldl or '?'} · приоритет",
            "y",
            "apob_borderline",
        )
    elif _ldl is not None and _ldl >= 3.0 and _apob is None:
        _set_hero("LDL · Выше цели", f"{_ldl}", "ммоль/л", "цель <3.0 · диета + Plant Sterols", "y", "ldl_borderline")
    elif _bp_avg_sys is not None and _bp_avg_sys >= 130:
        _set_hero(
            "АД · Гипертония 1 ст.",
            f"{round(_bp_avg_sys)}/{round(_bp_avg_dia)}",
            "мм рт.ст.",
            "цель <120/80 · вес ↓, кардио ↑",
            "y",
            "bp_borderline",
        )
    elif _homa is not None and _homa >= 1.5:
        _set_hero(
            "HOMA-IR · Пограничное",
            f"{_homa}",
            "",
            "цель <1.5 · сладкое ↓, не есть после 20:00",
            "y",
            "homa_borderline",
        )
    elif _visc_last is not None and _visc_last >= 10:
        _set_hero("Висцеральный жир", f"{_visc_last}", "ед.", "цель <10 · похудение работает", "y", "visceral_high")
    # ── 3. POSITIVE (green) — мотивация ──
    elif _bio_age is not None and _bio_age < _age_score:
        diff = round(_age_score - _bio_age, 1)
        diff_str = f"−{diff}"
        sub_quality = " (черновик)" if _bio_age_quality == "stale" else ""
        _set_hero(
            f"Биовозраст · PhenoAge{sub_quality}",
            f"{_bio_age}",
            "лет",
            f"{diff_str} от паспорта · 9 биомаркеров",
            "g",
            "phenoage_younger",
        )
    elif _hba1c is not None:
        _set_hero(
            "HbA1c · Глик. гемоглобин", f"{_hba1c}", "%", "норма <5.7 · метаболизм в порядке", "g", "hba1c_normal"
        )
    # else — fallback "no data" уже задан выше

    panels_data = {
        "attia": panels_attia,
        "metabolic": panels_metabolic,
        "le8": panels_le8,
        "phenoage": panels_phenoage,
        "score2": panels_score2,
        "ascvd": panels_ascvd,
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

    # ── ДОПОЛНИТЕЛЬНЫЕ ОСИ RADAR: образ жизни (не биомаркеры) ────────────────
    # Каждая ось 0-100, добавляется только если есть данные. Мульти-юзерно:
    # если у пользователя нет лога питания / Garmin / тренировок — ось не покажется.

    # Питание: используем уже посчитанный _diet_score из LE8 (там MEDAS встроен)
    if _diet_score is not None:
        radar["Питание"] = _diet_score

    # Активность: используем _pa_score из LE8 (vigorous ×2 эквивалент)
    if _pa_score:
        radar["Активность"] = _pa_score

    # Сон: используем _sleep_score из LE8
    if _sleep_score is not None:
        radar["Сон"] = _sleep_score

    # Для систем без данных — None → убираем из подсчёта overall
    radar_vals = [v for v in radar.values() if v > 0]
    overall_score = round(sum(radar_vals) / len(radar_vals)) if radar_vals else 0

    # ── chronic-conditions cap: lower ceiling based on pack ─────────────────
    # Biomarker scores reflect current lab values but can't capture structural
    # diagnoses (AFib, post-surgical anatomy, chronic metabolic disorders).
    # We apply a conservative cap so the score doesn't mislead.
    _chronic_caps = {
        "cardiac": 75,  # POAF/AFib history, ICM implant, structural cardiac risk
        "bariatric": 85,  # Post-bariatric metabolism, malabsorption risk
        "female-cycle": 95,  # Mild cycle-related variance, generally healthy
        "generic": 95,
    }
    _cap = _chronic_caps.get(user.pack_name or "generic", 95)
    if overall_score > _cap:
        overall_score = _cap

    # ── achievements: collected in priority tiers, capped at 8 (2 rows × 4) ──
    # Tuples: (emoji, title, subtitle) or (emoji, title, subtitle, is_warn)
    # Warnings (is_warn=True) are amber cards and always shown first.

    # Tier 0 — warnings (shown before any positive achievements)
    _ach_warn: list[tuple] = []

    # Protein: 7-day average vs target (~140g = lean_mass * 2.5)
    if prot:
        _recent_prot = [v for k, v in sorted(prot.items())[-7:]]
        _prot_avg_7d = round(sum(_recent_prot) / len(_recent_prot)) if _recent_prot else 0
        _prot_target = {"bariatric": 140, "cardiac": 100, "female-cycle": 75, "generic": 80}.get(
            user.pack_name or "generic", 80
        )  # pack-specific
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
    # Helper: формирует подзаголовок с прогрессом «было X (год) → стало Y», если в истории есть peak.
    # Мульти-юзерно: если у юзера только 1 замер — показываем только текущее значение.
    def _ach_subtitle_with_history(
        key: str, current: float, unit: str, threshold: float, threshold_label: str, lower_is_better: bool = True
    ) -> str:
        """Возвращает подзаголовок достижения с историей если она есть и значимая."""
        record = biomarkers.get(key) or {}
        peak = record.get("peak_max" if lower_is_better else "peak_min")
        if peak and peak.get("value") and peak.get("date"):
            peak_v = peak["value"]
            peak_year = peak["date"][:4]
            # Показываем историю только если есть значимый прогресс (≥10% или пересечение порога)
            if lower_is_better and peak_v > current * 1.05:
                if peak_v >= threshold > current:
                    return f"было {peak_v}{unit} в {peak_year} ({threshold_label}) → стало {current}{unit}"
                return f"было {peak_v}{unit} в {peak_year} → стало {current}{unit}"
            elif (not lower_is_better) and peak_v < current * 0.95:
                return f"было {peak_v}{unit} в {peak_year} → стало {current}{unit}"
        return f"{current}{unit} — ниже порога {threshold}{unit}" if lower_is_better else f"{current}{unit}"

    _ach_t1: list[tuple] = []
    hba1c = bv("HbA1c")
    if hba1c and hba1c < 5.7:
        sub = _ach_subtitle_with_history("HbA1c", hba1c, "%", 5.7, "преддиабет", lower_is_better=True)
        _ach_t1.append(("🎯", "Нет преддиабета", sub))
    vd = bv("vitamin_D")
    if vd and vd >= 50:
        _ach_t1.append(("☀️", "Витамин D в оптимуме", f"{vd} нг/мл — цель достигнута"))
    elif vd and vd >= 30:
        _ach_t1.append(("🌤️", "Витамин D почти в норме", f"{vd} нг/мл — цель 50+ нг/мл"))
    ldl = bv("LDL")
    if ldl and ldl <= 3.1:
        # Показать прогресс: было 3.9 в 2025-01 → стало 3.1
        ldl_record = biomarkers.get("LDL") or {}
        peak = ldl_record.get("peak_max")
        if peak and peak.get("value", 0) > ldl * 1.05:
            sub = f"было {peak['value']} ммоль/л в {peak['date'][:4]} → стало {ldl} ({bd('LDL')})"
        else:
            sub = f"{ldl} ммоль/л ({bd('LDL')})"
        _ach_t1.append(("❤️", "ЛПНП — исторический минимум", sub))

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

    # Helper: склонения русских числительных (1 тренировка / 2 тренировки / 5 тренировок).
    # Используется в достижениях и других местах где не хочется вводить отдельные русские пакеты.
    def _ru_plural(n: int, forms: tuple[str, str, str]) -> str:
        """forms = (one, few, many) — например ('тренировка', 'тренировки', 'тренировок')."""
        n_abs = abs(n) % 100
        if 11 <= n_abs <= 14:
            return forms[2]
        n_mod10 = n_abs % 10
        if n_mod10 == 1:
            return forms[0]
        if 2 <= n_mod10 <= 4:
            return forms[1]
        return forms[2]

    # Tier 3 — activity volume
    _ach_t3: list[tuple] = []
    if activities:
        n_act = len(activities)
        for milestone in [100, 70, 50, 25, 10]:
            if n_act >= milestone:
                _w = _ru_plural(n_act, ("тренировка", "тренировки", "тренировок"))
                _ach_t3.append(("🏋️", f"{n_act} {_w}", "с начала трекинга"))
                break

    # Tier 4 — supplements consistency
    _ach_t4: list[tuple] = []
    if len(supp_days) >= 60:
        _w_days = _ru_plural(len(supp_days), ("день", "дня", "дней"))
        _ach_t4.append(("💊", f"{len(supp_days)} {_w_days} добавок", "Стабильный приём витаминов"))

    # Tier 5 — nutrition quantity + quality
    _ach_t5: list[tuple] = []
    if kcal:
        n_kcal = len(kcal)
        for milestone in [108, 100, 90, 60, 30, 21, 14, 7]:
            if n_kcal >= milestone:
                _w_d = _ru_plural(n_kcal, ("день", "дня", "дней"))
                _ach_t5.append(("🍽️", f"{n_kcal} {_w_d} питания", "Каждый приём в NutriLogBot"))
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
            _w_s = _ru_plural(streak, ("день", "дня", "дней"))
            _ach_t6.append(("🔥", f"{streak} {_w_s} подряд", "Трекинг питания без пропусков"))

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
    sport_block = _build_sport_block(user_id, user_age=_age_score)

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
    # Display: years if ≥1, months otherwise (Russian declension: 1 год, 2-4 года, 5+ лет)
    if _history_years >= 1:
        _y = _history_years
        if 11 <= (_y % 100) <= 14:
            _year_word = "лет"
        elif _y % 10 == 1:
            _year_word = "год"
        elif 2 <= _y % 10 <= 4:
            _year_word = "года"
        else:
            _year_word = "лет"
        _history_label = str(_y) + " " + _year_word
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
            # ── ЧСС-зоны: считаем границы от user.age (формула 220-age) ──
            # Мульти-юзерно: у каждого юзера свои bpm-границы (у 30-летнего max~190, у 60-летнего max~160).
            # Используется в спорт-блоке, легенде зон, KPI карточках, текстах рекомендаций.
            "hr_zones": (
                {
                    "max_hr": (220 - _age_score) if _age_score else None,
                    # Границы: Z1 <60% maxHR, Z2 60-70%, Z3 70-80%, Z4 80-90%, Z5 ≥90%
                    "z1_top": round((220 - _age_score) * 0.60) if _age_score else None,
                    "z2_top": round((220 - _age_score) * 0.70) if _age_score else None,
                    "z3_top": round((220 - _age_score) * 0.80) if _age_score else None,
                    "z4_top": round((220 - _age_score) * 0.90) if _age_score else None,
                }
                if _age_score
                else {"max_hr": None, "z1_top": None, "z2_top": None, "z3_top": None, "z4_top": None}
            ),
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
        "muscle_last": muscle_last_kg,  # для плашки «% Жира» в hero-grid
        "hero_priority": hero_priority,  # динамический выбор главного маркера для шапки
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
        "alco_kcal": alco_kcal,
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
    """Главная точка входа: данные из БД → HTML-строка (шаблон Mission Control).

    Adaptive blocks: uses get_available_blocks() to skip sections that have
    no data at all for this user (important for new cohort users).  The
    capabilities dict already drives show/hide in the template — we augment
    it with lifetime DB checks so new users with an empty date-range window
    still get correct False values for every empty section.
    """
    from dashboard_blocks import get_available_blocks
    from database.models import User

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    payload = _build_payload(db, user_id)

    # Augment capabilities with lifetime block availability checks.
    # _build_payload derives capabilities only from the current date window;
    # get_available_blocks checks lifetime rows so new users get correct Falses.
    user = db.query(User).filter_by(telegram_id=user_id).first()
    if user:
        available = get_available_blocks(db, user)
        caps = payload["meta"]["capabilities"]
        # OR-merge: show a block if EITHER the window data check OR the
        # lifetime check is True — this preserves correct True values for
        # existing users even when the current window has no data.
        caps["has_weight"] = caps["has_weight"] or available["body"]
        caps["has_garmin"] = caps["has_garmin"] or available["sport"]
        caps["has_activity"] = caps["has_activity"] or available["sport"]
        caps["has_netatmo"] = caps["has_netatmo"] or available["air"]
        caps["has_bp"] = caps["has_bp"] or available["blood_pressure"]
        caps["has_medical"] = caps["has_medical"] or available["blood_tests"]
        caps["has_nutrition"] = caps["has_nutrition"] or available["nutrition"]
        # New capability keys used directly from available blocks
        caps["has_sleep"] = caps["has_garmin"]
        caps["has_heart"] = caps["has_garmin"] or caps["has_bp"]

    payload_json = json.dumps(payload, ensure_ascii=False)
    return template.replace("{{PAYLOAD}}", payload_json)
