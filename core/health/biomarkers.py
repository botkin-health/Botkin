# core/health/biomarkers.py
"""Агрегация канонических биомаркеров из списка анализов.

Воспроизводит формат, который ранее строил scripts/generate_biomarkers_json.py
(build_biomarkers), но ключи нормализуются через core.health.kb_schema.to_canonical.
Используется и дашбордом (рантайм, из Postgres), и (переходно) скриптом-генератором.
"""

from __future__ import annotations

from core.health.kb_schema import to_canonical


def aggregate_biomarkers(tests: list[dict]) -> dict:
    """tests=[{date, values}] (сырые KB values) →
    {canon_key: {value, date[, earliest, peak_max, peak_min, n_history]}} + _meta.
    """
    # Свежие сверху — для seen берём первое попавшееся (самое свежее) значение.
    tests_sorted = sorted(tests, key=lambda t: t.get("date", ""), reverse=True)

    seen: dict[str, dict] = {}
    history: dict[str, list[dict]] = {}
    for t in tests_sorted:
        date = t.get("date", "")
        canon, _warnings = to_canonical(t.get("values") or {})
        for k, v in canon.items():
            if k not in seen:
                seen[k] = {"value": v, "date": date}
            history.setdefault(k, []).append({"value": v, "date": date})

    bio: dict = {}
    for k, record in seen.items():
        rec = dict(record)
        pts = sorted(history[k], key=lambda x: x["date"])
        if len(pts) >= 2:
            rec["earliest"] = pts[0]
            rec["peak_max"] = max(pts, key=lambda x: x["value"])
            rec["peak_min"] = min(pts, key=lambda x: x["value"])
            rec["n_history"] = len(pts)
        bio[k] = rec

    all_dates = sorted(t.get("date", "") for t in tests if t.get("date"))
    bio["_meta"] = {
        "earliest_test_date": all_dates[0] if all_dates else None,
        "total_tests": len(tests),
        "total_markers": len(bio),
    }
    return bio
