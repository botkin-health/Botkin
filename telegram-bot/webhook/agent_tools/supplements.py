"""Agent tools: supplement logging and history."""

from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from webhook.jwt_auth import get_agent_user, get_db, require_agent_scope
from .common import _parse_date

router = APIRouter(prefix="/api/agent", tags=["agent-tools-supplements"])


class LogSupplementRequest(BaseModel):
    supplement_name: str
    dosage: Optional[str] = None
    date: Optional[str] = None  # YYYY-MM-DD; defaults to today
    time: Optional[str] = None  # HH:MM
    force: bool = False  # True — записать даже если та же добавка уже логировалась в этот день


def _parse_time(time_str: Optional[str]):
    """Parse HH:MM string or return None."""
    if not time_str:
        return None
    from datetime import time as time_cls

    try:
        h, m = time_str.split(":")
        return time_cls(int(h), int(m))
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid time format: {time_str!r}. Use HH:MM.")


@router.post("/log_supplement")
async def log_supplement(
    req: LogSupplementRequest,
    user=Depends(require_agent_scope("rw")),
    db: Session = Depends(get_db),
):
    """Save a supplement entry to supplements_log."""
    from sqlalchemy import text as _text

    from database.crud import create_supplement_log

    record_date = _parse_date(req.date, user)
    sup_time = _parse_time(req.time)

    # Дедуп-guard (F-002, 02.07.2026): та же добавка уже логировалась в этот день →
    # не пишем молча дубль, а возвращаем warning; агент уточнит у пользователя
    # и при подтверждении повторит вызов с force=true.
    if not req.force:
        existing = db.execute(
            _text(
                "SELECT id, time FROM supplements_log "
                "WHERE user_id = :uid AND date = :d "
                "AND LOWER(REPLACE(supplement_name, '-', ' ')) = LOWER(REPLACE(:name, '-', ' ')) "
                "LIMIT 1"
            ),
            {"uid": user.telegram_id, "d": record_date, "name": req.supplement_name},
        ).first()
        if existing:
            return {
                "status": "duplicate_warning",
                "existing_id": existing.id,
                "existing_time": str(existing.time) if existing.time else None,
                "date": record_date.isoformat(),
                "supplement_name": req.supplement_name,
                "hint": (
                    "Эта добавка уже залогирована в этот день. Запись НЕ создана. "
                    "Спроси пользователя, действительно ли это повторный приём; "
                    "если да — повтори вызов с force=true."
                ),
            }

    log = create_supplement_log(
        db=db,
        user_id=user.telegram_id,
        date=record_date,
        time=sup_time,
        supplement_name=req.supplement_name,
        dosage=req.dosage,
    )

    return {
        "status": "ok",
        "supplement_id": log.id,
        "date": record_date.isoformat(),
        "supplement_name": req.supplement_name,
        "dosage": req.dosage,
    }


@router.get("/recent_supplements")
async def recent_supplements(
    days: int = 30,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Recent supplement intake log with per-supplement aggregation.

    Reads from `supplements_log` (filled by aiogram bot when user logs
    "выпил магний" etc). Returns:
      - per-supplement: days_taken in period, total_intakes (multi-dose/day OK),
        last_taken_date, last_dosage seen
      - period stats: total log lines

    Default 30 days — typical regimen feedback window.
    """
    from sqlalchemy import text as sql_text

    days = max(1, min(days, 180))
    sql = sql_text(
        """
        SELECT supplement_name,
               COUNT(*)                          AS total_intakes,
               COUNT(DISTINCT date)              AS days_taken,
               MAX(date)                         AS last_date,
               (ARRAY_AGG(dosage ORDER BY date DESC, time DESC NULLS LAST))[1] AS last_dosage
        FROM supplements_log
        WHERE user_id = :uid
          AND date >= CURRENT_DATE - (:days || ' days')::interval
        GROUP BY supplement_name
        ORDER BY days_taken DESC, supplement_name
        """
    )
    rows = db.execute(sql, {"uid": user.telegram_id, "days": days}).fetchall()
    items = [
        {
            "supplement": r.supplement_name,
            "days_taken": r.days_taken,
            "total_intakes": r.total_intakes,
            "intakes_per_day_avg": round(r.total_intakes / r.days_taken, 2) if r.days_taken else 0,
            "adherence_pct": round(100 * r.days_taken / days, 1),
            "last_date": r.last_date.isoformat() if r.last_date else None,
            "last_dosage": r.last_dosage,
        }
        for r in rows
    ]
    return {
        "status": "ok",
        "period_days": days,
        "unique_supplements": len(items),
        "total_log_entries": sum(i["total_intakes"] for i in items),
        "items": items,
    }


@router.get("/supplement_daily_log")
async def supplement_daily_log(
    days: int = 30,
    supplement: Optional[str] = None,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Per-day supplement intake log for correlation analysis.

    В отличие от /recent_supplements (только агрегаты), возвращает для каждой
    добавки СПИСОК ДАТ приёма за окно + границы окна — чтобы сопоставлять факт
    приёма по дням с данными сна/HRV/активности (напр. магний ↔ качество сна).

    supplements_log хранит строку на каждый приём; «не принимал» = отсутствие
    строки. Отдаём разреженно: taken_dates + [start_date, end_date] полностью
    определяют taken/not-taken для любого дня без плотной сетки N×дни.

    Параметры:
      days: окно, 1..180 (дефолт 30).
      supplement: опц. подстрока имени (регистронезависимо) — один препарат.
    """
    from datetime import time as _dtime

    from database.models import SupplementLog

    days = max(1, min(days, 180))
    # «Сегодня» в tz пользователя — иначе поздние вечерние записи уедут за окно
    # (та же логика, что в других эндпоинтах агента).
    tz_name = getattr(user, "timezone", None) or "Europe/Moscow"
    try:
        user_tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        user_tz = ZoneInfo("Europe/Moscow")
    today = datetime.now(user_tz).date()
    start_date = today - timedelta(days=days - 1)

    rows = (
        db.query(
            SupplementLog.supplement_name,
            SupplementLog.date,
            SupplementLog.time,
            SupplementLog.dosage,
        )
        .filter(
            SupplementLog.user_id == user.telegram_id,
            SupplementLog.date >= start_date,
        )
        .order_by(SupplementLog.supplement_name, SupplementLog.date)
        .all()
    )

    name_filter = supplement.strip().lower() if supplement else None

    # Группируем по имени добавки, копим множество дат приёма + последнюю дозу.
    groups: dict = {}
    for r in rows:
        name = r.supplement_name or ""
        if name_filter and name_filter not in name.lower():
            continue
        g = groups.setdefault(name, {"dates": set(), "last_key": None, "last_dosage": None})
        g["dates"].add(r.date)
        key = (r.date, r.time or _dtime.min)
        if g["last_key"] is None or key > g["last_key"]:
            g["last_key"] = key
            g["last_dosage"] = r.dosage

    supplements = []
    for name, g in groups.items():
        dates_sorted = sorted(g["dates"])
        supplements.append(
            {
                "supplement": name,
                "days_taken": len(dates_sorted),
                "adherence_pct": round(100 * len(dates_sorted) / days, 1),
                "taken_dates": [d.isoformat() for d in dates_sorted],
                "last_dosage": g["last_dosage"],
            }
        )
    # По убыванию частоты, затем по имени — как в /recent_supplements.
    supplements.sort(key=lambda s: (-s["days_taken"], s["supplement"]))

    return {
        "status": "ok",
        "period_days": days,
        "start_date": start_date.isoformat(),
        "end_date": today.isoformat(),
        "unique_supplements": len(supplements),
        "supplements": supplements,
    }
