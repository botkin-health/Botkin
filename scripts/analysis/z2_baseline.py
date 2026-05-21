#!/usr/bin/env python3
"""Z2 / Maffetone aerobic baseline — расчёт ключевых метрик пробежки.

Цель: один раз в неделю-две (или после каждой Z2-пробежки) считать прогресс
аэробной базы. Главный KPI — pace при HR на потолке зоны (132 уд/мин для
формулы Maffetone 180-возраст у Александра, 48 лет в 2026).

Логика записи: append-only `data/z2_baseline.json`. Не перезаписывать старое.

Запуск:
    ./venv/bin/python scripts/analysis/z2_baseline.py <activity_id>
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from statistics import mean

BASE = Path(__file__).resolve().parents[2]
STORE = BASE / "data" / "z2_baseline.json"

# Конфиг — для Александра. Если будут другие пользователи — расширим в users.py.
USER_AGE_AT_2026 = 48
MAFFETONE_CAP = 180 - USER_AGE_AT_2026  # 132
ZONE_LO = MAFFETONE_CAP - 12  # 120
ZONE_HI = MAFFETONE_CAP  # 132


def _pace_min_per_km(speed_m_s: float) -> float:
    if not speed_m_s or speed_m_s < 0.3:
        return 0.0
    return 1000 / speed_m_s / 60


def _format_pace(p: float) -> str:
    if p <= 0:
        return "—"
    m = int(p)
    s = int(round((p - m) * 60))
    return f"{m}:{s:02d}"


def analyze_activity(activity_id: int) -> dict:
    import sys as _s

    _s.path.insert(0, str(BASE / "scripts" / "garmin"))
    from download_garmin_data import login_garmin  # noqa: E402

    client = login_garmin()
    details = client.get_activity_details(activity_id)
    metrics = details.get("metricDescriptors", [])
    mvals = details.get("activityDetailMetrics", [])

    idx = {m.get("key"): i for i, m in enumerate(metrics)}
    hr_i = idx.get("directHeartRate")
    spd_i = idx.get("directSpeed")
    t_i = idx.get("sumElapsedDuration")

    if hr_i is None or spd_i is None or t_i is None:
        raise ValueError("Нет одного из обязательных полей (HR/speed/time) в activity details")

    samples = []
    for s in mvals:
        m = s.get("metrics") or []
        if len(m) <= max(hr_i, spd_i, t_i):
            continue
        hr, spd, t = m[hr_i], m[spd_i], m[t_i]
        if hr is None or spd is None or t is None:
            continue
        samples.append((t, hr, spd))

    if not samples:
        raise ValueError("Сэмплы пустые")

    # Метаданные активности
    summary = client.get_activity(activity_id)
    activity_date = (summary.get("summaryDTO") or summary).get("startTimeLocal", "")[
        :10
    ] or datetime.now().date().isoformat()

    # === Главный KPI: pace при HR в верхней трети зоны (target_hr ± 3) ===
    # Берём минуты где HR попал в [target-3, target+3] и считаем avg pace
    target = MAFFETONE_CAP
    near_target = [(t, hr, spd) for t, hr, spd in samples if abs(hr - target) <= 3 and spd > 0.5]
    pace_at_target = _pace_min_per_km(mean(s[2] for s in near_target)) if near_target else 0.0

    # avg pace в коридоре Z2 (для понимания общей картины)
    in_zone = [(t, hr, spd) for t, hr, spd in samples if ZONE_LO <= hr <= ZONE_HI and spd > 0.5]
    pace_in_zone = _pace_min_per_km(mean(s[2] for s in in_zone)) if in_zone else 0.0
    avg_hr_in_zone = mean(s[1] for s in in_zone) if in_zone else 0

    # Время до стабилизации (первая 3-минутная серия HR <= ZONE_HI + 3)
    buckets: dict[int, dict[str, list]] = {}
    for t, hr, spd in samples:
        m = int(t // 60)
        buckets.setdefault(m, {"hr": [], "spd": []})
        buckets[m]["hr"].append(hr)
        buckets[m]["spd"].append(spd)
    streak = 0
    time_to_stable_min = None
    for m in sorted(buckets):
        if not buckets[m]["hr"]:
            continue
        avg = mean(buckets[m]["hr"])
        if avg <= ZONE_HI + 3:
            streak += 1
            if streak >= 3 and time_to_stable_min is None:
                time_to_stable_min = m - 2
                break
        else:
            streak = 0

    # Доля времени в зоне (по сэмплам, не по Garmin-зонам)
    pct_in_zone = len(in_zone) / len(samples) * 100 if samples else 0

    # Общие
    total_time_sec = samples[-1][0] - samples[0][0]
    total_dist_m = (summary.get("summaryDTO") or summary).get("distance") or summary.get("distance", 0)
    avg_hr_all = mean(s[1] for s in samples)
    avg_pace_all = _pace_min_per_km(total_dist_m / total_time_sec) if total_time_sec else 0

    record = {
        "date": activity_date,
        "activity_id": activity_id,
        "activity_name": summary.get("activityName"),
        "duration_min": round(total_time_sec / 60, 1),
        "distance_km": round(total_dist_m / 1000, 2),
        "avg_hr_full": round(avg_hr_all, 1),
        "avg_pace_full_min_per_km": round(avg_pace_all, 2),
        "pace_in_zone_min_per_km": round(pace_in_zone, 2),
        "avg_hr_in_zone": round(avg_hr_in_zone, 1),
        "pace_at_target_hr_min_per_km": round(pace_at_target, 2),
        "target_hr": target,
        "zone_range": [ZONE_LO, ZONE_HI],
        "pct_time_in_zone": round(pct_in_zone, 1),
        "time_to_stable_min": time_to_stable_min,
        "samples_count": len(samples),
        "added_at": datetime.now().isoformat(timespec="seconds"),
    }
    return record


def append_record(record: dict) -> None:
    store = []
    if STORE.exists():
        try:
            store = json.loads(STORE.read_text())
        except Exception:
            store = []
    # дедуп по activity_id
    existing = {r.get("activity_id") for r in store}
    if record["activity_id"] in existing:
        store = [r for r in store if r.get("activity_id") != record["activity_id"]]
    store.append(record)
    store.sort(key=lambda r: r.get("date", ""))
    STORE.write_text(json.dumps(store, ensure_ascii=False, indent=2))


def print_report(record: dict, history: list) -> None:
    print(f"\n=== Z2 baseline: {record['date']} — {record['activity_name']} ===")
    print(f"  Дистанция: {record['distance_km']} км за {record['duration_min']} мин")
    print(
        f"  Средний HR: {record['avg_hr_full']} | средний pace: {_format_pace(record['avg_pace_full_min_per_km'])}/км"
    )
    print()
    print(
        f"  📌 Pace в коридоре Z2 ({record['zone_range'][0]}-{record['zone_range'][1]}): "
        f"{_format_pace(record['pace_in_zone_min_per_km'])}/км "
        f"при avg HR {record['avg_hr_in_zone']}"
    )
    print(
        f"  📌 Pace при HR ~{record['target_hr']} (Maffetone-cap): "
        f"{_format_pace(record['pace_at_target_hr_min_per_km'])}/км ← главный KPI"
    )
    print(f"  Время в зоне: {record['pct_time_in_zone']}% сэмплов")
    print(f"  Стабилизация HR в зоне: с {record['time_to_stable_min']}-й минуты")

    z2_history = [r for r in history if r.get("pace_at_target_hr_min_per_km") and r["pace_at_target_hr_min_per_km"] > 0]
    if len(z2_history) > 1:
        print(f"\n=== Прогресс aerobic baseline ({len(z2_history)} тренировок) ===")
        for r in z2_history[-5:]:
            print(
                f"  {r['date']}: pace@{r['target_hr']} = {_format_pace(r['pace_at_target_hr_min_per_km'])}/км "
                f"(дистанция {r['distance_km']} км, средн HR {r['avg_hr_full']})"
            )
        # Дельта
        first = z2_history[0]
        last = z2_history[-1]
        delta = first["pace_at_target_hr_min_per_km"] - last["pace_at_target_hr_min_per_km"]
        sign = "быстрее" if delta > 0 else "медленнее"
        print(f"\n  Δ {first['date']} → {last['date']}: pace стал на {abs(delta):.2f} мин/км {sign}")
    print()


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Использование: z2_baseline.py <activity_id>", file=sys.stderr)
        return 2
    activity_id = int(argv[1])
    record = analyze_activity(activity_id)
    append_record(record)
    history = json.loads(STORE.read_text()) if STORE.exists() else []
    print_report(record, history)
    print(f"Записано в {STORE.relative_to(BASE)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
