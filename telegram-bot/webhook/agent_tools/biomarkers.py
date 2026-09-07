"""Agent tools: blood biomarkers (canonicalized) and PhenoAge."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from webhook.jwt_auth import get_agent_user, get_db
from .common import _as_dict

router = APIRouter(prefix="/api/agent", tags=["agent-tools-biomarkers"])


@router.get("/recent_biomarkers")
async def recent_biomarkers(
    limit: int = 20,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Most recent blood tests (latest `limit`).

    Each row has test_date + test_type + values (jsonb dict of marker → value).
    Default raised to 20 so questions like "как менялся холестерин" cover
    ~1 year of history without follow-up calls.
    """
    from sqlalchemy import text as sql_text

    limit = max(1, min(limit, 100))
    sql = sql_text(
        """
        SELECT test_date, test_type, "values"
        FROM blood_tests
        WHERE user_id = :uid
        ORDER BY test_date DESC
        LIMIT :lim
        """
    )
    rows = db.execute(sql, {"uid": user.telegram_id, "lim": limit}).fetchall()
    from core.health.kb_schema import to_canonical

    tests = []
    for r in rows:
        canon, _w = to_canonical(_as_dict(r.values), passthrough_unmapped=True)
        # test_date — date на Postgres, str через SQLite (raw text query); поддержим оба.
        d = r.test_date.isoformat() if hasattr(r.test_date, "isoformat") else str(r.test_date)
        tests.append({"date": d, "type": r.test_type, "values": canon})
    return {"status": "ok", "count": len(tests), "tests": tests}


@router.get("/latest_biomarkers")
async def latest_biomarkers(
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Latest value per canonical biomarker with staleness info.

    Unlike /recent_biomarkers (raw test rows, useful for trends),
    this returns ONE entry per canonical key — the most recent value
    and its staleness status.

    Use this when the user asks about a specific marker or their overall
    biomarker state. Use /recent_biomarkers for historical trends.
    """
    from datetime import date as _date

    from sqlalchemy import text as sql_text

    from core.health.biomarkers import aggregate_biomarkers
    from core.health.kb_schema import CANONICAL
    from core.health.staleness import stale_label

    rows = db.execute(
        sql_text('SELECT test_date, "values" FROM blood_tests WHERE user_id = :uid ORDER BY test_date DESC'),
        {"uid": user.telegram_id},
    ).fetchall()

    # test_date is a date on Postgres but a str via SQLite (raw text query) — handle both.
    tests = [
        {
            "date": r.test_date.isoformat() if hasattr(r.test_date, "isoformat") else str(r.test_date),
            "values": _as_dict(r.values),
        }
        for r in rows
    ]
    bio = aggregate_biomarkers(tests)

    result: dict[str, dict] = {}
    stale_keys: list[str] = []

    for key, entry in bio.items():
        if key.startswith("_"):
            continue
        marker = CANONICAL.get(key)
        unit = marker.unit if marker is not None else ""
        sl = stale_label(entry.get("days_ago"), entry.get("staleness_threshold_days"))
        if entry.get("is_stale"):
            stale_keys.append(key)
        result[key] = {
            "value": entry["value"],
            "unit": unit,
            "date": entry["date"],
            "days_ago": entry.get("days_ago"),
            "threshold_days": entry.get("staleness_threshold_days"),
            "is_stale": entry.get("is_stale", False),
            "stale_label": sl,
        }

    return {
        "status": "ok",
        "as_of": _date.today().isoformat(),
        "count": len(result),
        "biomarkers": result,
        "stale_count": len(stale_keys),
        "stale_keys": stale_keys,
    }


@router.get("/phenoage")
async def phenoage(
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Biological age via Levine 2018 (Aging Cell) PhenoAge formula.

    Requires 9 markers from blood_tests.values (latest available value per
    marker, scanning all of user's history). Plus chronological age from
    users.birth_date.

    Returns: bio_age, chronological_age, delta, markers with direction
    ('younger'/'older' vs NHANES median for ~48yo male) and freshness.
    """
    from sqlalchemy import text as sql_text

    # Required markers — keys in blood_tests.values JSONB.
    markers = ["albumin_g_l", "creatinine", "glucose", "hs_CRP", "lymphocytes", "MCV", "RDW_CV", "ALP", "WBC"]

    # Забираем все строки юзера и канонизируем в Python — формат-агностично
    # (работает для CamelCase Александра и snake_case_with_units Димы).
    from core.health.kb_schema import to_canonical

    rows = db.execute(
        sql_text('SELECT test_date, "values" FROM blood_tests WHERE user_id = :uid ORDER BY test_date DESC'),
        {"uid": user.telegram_id},
    ).fetchall()

    latest: dict[str, dict] = {}
    for r in rows:
        canon, _w = to_canonical(_as_dict(r.values))
        # test_date — date на Postgres, str через SQLite (raw text query); поддержим оба.
        d = r.test_date.isoformat() if hasattr(r.test_date, "isoformat") else str(r.test_date)
        for key in markers:
            if key in canon and key not in latest:
                latest[key] = {"value": float(canon[key]), "date": d}

    # Chronological age
    chrono_age = None
    if user.birth_date:
        today = date.today()
        chrono_age = (
            today.year
            - user.birth_date.year
            - ((today.month, today.day) < (user.birth_date.month, user.birth_date.day))
        )

    # NHANES median for ~48yo male, plus direction (higher_is_younger)
    nhanes = {
        "albumin_g_l": (42.0, True),  # g/L (4.2 g/dL)
        "creatinine": (92.8, False),  # µmol/L (1.05 mg/dL)
        "glucose": (5.3, False),  # mmol/L (95 mg/dL)
        "hs_CRP": (1.0, False),  # mg/L (ln(0.1) → 0)
        "lymphocytes": (28.0, True),  # %
        "MCV": (90.0, False),  # fL
        "RDW_CV": (13.8, False),  # %
        "ALP": (68.0, False),  # U/L
        "WBC": (6.7, False),  # ×10³/µL
    }

    today_date = date.today()
    marker_list: list[dict] = []
    younger_count = 0
    stale_markers: list[str] = []
    for key in markers:
        info = latest.get(key)
        if not info:
            marker_list.append({"name": key, "value": None, "direction": "unknown", "date": None})
            continue
        med, higher_younger = nhanes[key]
        v = info["value"]
        is_younger = (v > med) if higher_younger else (v < med)
        if is_younger:
            younger_count += 1
        days_ago = (today_date - date.fromisoformat(info["date"])).days
        stale = days_ago > 365
        if stale:
            stale_markers.append(f"{key} ({info['date']})")
        marker_list.append(
            {
                "name": key,
                "value": round(v, 3),
                "direction": "younger" if is_younger else "older",
                "date": info["date"],
                "days_ago": days_ago,
                "stale_over_year": stale,
            }
        )

    bio_age: Optional[float] = None
    error: Optional[str] = None
    if chrono_age is None:
        error = "users.birth_date not set"
    elif None in [latest.get(k, {}).get("value") for k in markers]:
        missing = [k for k in markers if k not in latest]
        error = f"missing markers: {missing}"
    elif latest["hs_CRP"]["value"] <= 0:
        error = "hs_CRP must be > 0 for ln()"
    else:
        # Levine 2018 formula — чистая функция (core.health.phenoage),
        # биомаркеры уже в канонических единицах. Импорт вне try, чтобы
        # ImportError не маскировался под "calculation error".
        from core.health.phenoage import phenoage_from_markers

        try:
            bio_age = round(
                phenoage_from_markers(
                    chrono_age,
                    {k: latest[k]["value"] for k in markers},
                ),
                1,
            )
        except (ValueError, OverflowError, KeyError) as e:
            error = f"calculation error: {e}"

    return {
        "status": "ok" if bio_age is not None else "incomplete",
        "bio_age": bio_age,
        "chronological_age": chrono_age,
        "delta_years": round(bio_age - chrono_age, 1) if bio_age and chrono_age else None,
        "interpretation": (
            "моложе паспорта"
            if bio_age and chrono_age and bio_age < chrono_age
            else "старше паспорта"
            if bio_age and chrono_age and bio_age > chrono_age
            else None
        ),
        "younger_markers_count": f"{younger_count}/9",
        "stale_markers": stale_markers,
        "error": error,
        "formula": "Levine 2018 (Aging Cell) — 9 biomarkers + chronological age",
        "markers": marker_list,
    }
