"""Agent tools: CGM glucose readings and stats (LibreLinkUp)."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database.models import GlucoseReading
from webhook.jwt_auth import get_agent_user, get_db
from core.health.glucose_stats import compute_glucose_stats, glucose_staleness
from core.health.glucose_runtime import refresh_glucose_for_telegram as _refresh_glucose, LoginOnCooldownError
from .common import _get_user_tz, _dt_isoformat_local

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent", tags=["agent-tools-glucose"])


@router.get("/recent_glucose")
async def recent_glucose(
    hours: int = 24,
    date: Optional[str] = None,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Точки глюкозы CGM + сводка (TIR, avg, min/max).

    Окно: либо `hours` (последние N часов, по умолчанию 24), либо `date`
    (конкретный календарный день YYYY-MM-DD в локальной TZ юзера; приоритетнее `hours`).

    Статистика — по ВСЕМ точкам окна. Точки для отображения прорежены РАВНОМЕРНО по
    всему окну (децимация), а не обрезаны до последних N — иначе при широком окне агент
    видел бы только последнюю ночь и не мог сопоставить еду с дневной кривой (#163).
    """
    # ── Определяем окно: конкретный день (date) или последние N часов (hours) ──
    if date is not None:
        try:
            day = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
        tz = _get_user_tz(user)
        start_local = datetime(day.year, day.month, day.day, tzinfo=tz)
        since = start_local.astimezone(timezone.utc)
        until = (start_local + timedelta(days=1)).astimezone(timezone.utc)
        window_desc = {"date": date}
    else:
        if hours < 1 or hours > 168:
            raise HTTPException(status_code=400, detail="hours must be between 1 and 168")
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        until = None
        window_desc = {"hours": hours}

    # On-demand: подтянуть свежую глюкозу для этого юзера прямо сейчас (#129).
    # Сетевой sync-вызов — в threadpool с таймаутом (зависший LLU не должен держать воркер);
    # любая ошибка/таймаут не валит ответ — fallback на данные из БД.
    refresh_skipped = False
    try:
        await asyncio.wait_for(
            asyncio.to_thread(_refresh_glucose, user.telegram_id),
            timeout=10.0,
        )
    except LoginOnCooldownError as e:
        refresh_skipped = True
        logger.info(
            "recent_glucose: логин на cooldown для %s, %.0fс до следующей попытки", user.telegram_id, e.retry_in
        )
    except Exception as e:
        logger.warning("recent_glucose: on-demand refresh не удался для %s: %s", user.telegram_id, e)

    max_points = 96

    # Все точки окна в хронологическом порядке (одним запросом — и для статистики, и для прореживания).
    q = db.query(GlucoseReading.ts, GlucoseReading.value, GlucoseReading.trend).filter(
        GlucoseReading.user_id == user.telegram_id, GlucoseReading.ts >= since
    )
    if until is not None:
        q = q.filter(GlucoseReading.ts < until)
    rows = q.order_by(GlucoseReading.ts.asc()).all()

    if not rows:
        return {
            "status": "ok",
            **window_desc,
            "total_count": 0,
            "stats": {"count": 0},
            "downsampled": False,
            "points": [],
            "refresh_skipped": refresh_skipped,
            **glucose_staleness(None, datetime.now(timezone.utc), refresh_skipped),
        }

    values = [float(val) for _, val, _ in rows]

    # Прореживание: равномерно выбрать max_points точек по всему окну (сохраняет форму
    # кривой). Глобальные min/max в stats считаются по ВСЕМ точкам, не по выборке.
    total = len(rows)
    if total > max_points:
        step = total / max_points
        idxs = sorted({min(int(i * step), total - 1) for i in range(max_points)})
        sampled = [rows[i] for i in idxs]
        downsampled = True
    else:
        sampled = rows
        downsampled = False

    points = [{"ts": _dt_isoformat_local(ts, user), "value": float(val), "trend": tr} for ts, val, tr in sampled]

    last_ts = rows[-1][0]  # хронологический порядок → последняя точка окна
    return {
        "status": "ok",
        **window_desc,
        "total_count": total,
        "returned_count": len(points),
        "stats": compute_glucose_stats(values),
        "downsampled": downsampled,
        "points": points,
        "refresh_skipped": refresh_skipped,
        "last_point_local": _dt_isoformat_local(last_ts, user),
        **glucose_staleness(last_ts, datetime.now(timezone.utc), refresh_skipped),
    }


@router.get("/glucose_stats")
async def glucose_stats(
    days: int = 7,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Сводная статистика глюкозы за N дней: TIR%, среднее, разброс + границы периода."""
    if days < 1 or days > 90:
        raise HTTPException(status_code=400, detail="days must be between 1 and 90")

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    values = [
        float(v)
        for (v,) in db.query(GlucoseReading.value)
        .filter(GlucoseReading.user_id == user.telegram_id, GlucoseReading.ts >= since)
        .all()
    ]
    return {
        "status": "ok",
        "days": days,
        "since": since.date().isoformat(),
        "until": now.date().isoformat(),
        "stats": compute_glucose_stats(values),
    }
