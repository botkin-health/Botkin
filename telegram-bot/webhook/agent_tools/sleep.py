"""Agent tools: recent sleep summary."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from webhook.jwt_auth import get_agent_user, get_db

router = APIRouter(prefix="/api/agent", tags=["agent-tools-sleep"])


@router.get("/recent_sleep")
async def recent_sleep(
    days: int = 14,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Recent sleep — из колонки activity_log.sleep_hours (надёжный источник).

    ВАЖНО (фикс 06.06.2026): раньше читали `raw_data->>'sleepingSeconds'`, которое
    заполняется лишь иногда (из daily-summary) → агент НЕ видел сон, который реально
    есть в БД (последние ночи имели пустой sleepingSeconds, но заполненный
    sleep_hours). Теперь читаем колонку `sleep_hours`, которую надёжно пишет
    `scripts/util/server_backfill_postgres.py::sync_sleep` из файлов Garmin sleep/.
    sleep_score/deep_h/rem_h остаются в raw_data (пишет тот же sync_sleep).

    Date semantics: `date` — календарный день; сон относится к ночи, ЗАКАНЧИВАЮЩЕЙСЯ
    в этот день (конвенция Garmin).
    """
    from sqlalchemy import text as sql_text

    days = max(1, min(days, 90))
    sql = sql_text(
        """
        SELECT date,
               sleep_hours                          AS duration_hours,
               (raw_data->>'sleep_score')::int      AS quality_score,
               (raw_data->>'deep_h')::numeric * 60  AS deep_min,
               (raw_data->>'rem_h')::numeric * 60   AS rem_min,
               source
        FROM activity_log
        WHERE user_id = :uid
          AND sleep_hours IS NOT NULL
          AND sleep_hours > 0
          AND date >= CURRENT_DATE - (:days || ' days')::interval
        ORDER BY date DESC
        """
    )
    rows = db.execute(sql, {"uid": user.telegram_id, "days": days}).fetchall()
    items = [
        {
            "date": r.date.isoformat(),
            "duration_hours": round(float(r.duration_hours), 2) if r.duration_hours is not None else None,
            "quality_score": r.quality_score,
            "deep_min": int(r.deep_min) if r.deep_min is not None else None,
            "rem_min": int(r.rem_min) if r.rem_min is not None else None,
            "source": r.source,
        }
        for r in rows
    ]

    # Свежесть: последняя НОЧЬ с данными, независимо от окна `days`. Чтобы агент
    # при пустом окне честно сказал «последний сон за DATE», а не «данных нет»
    # (данные Garmin приходят с задержкой; авто-синк идёт периодически).
    latest = db.execute(
        sql_text(
            "SELECT MAX(date) FROM activity_log WHERE user_id = :uid AND sleep_hours IS NOT NULL AND sleep_hours > 0"
        ),
        {"uid": user.telegram_id},
    ).scalar()
    latest_iso = latest.isoformat() if latest else None

    if not items:
        return {
            "status": "ok",
            "period_days": days,
            "count": 0,
            "items": [],
            "latest_available_date": latest_iso,
        }

    dur = [i["duration_hours"] for i in items if i["duration_hours"]]
    qual = [i["quality_score"] for i in items if i["quality_score"]]
    # Sleep quality flags by duration vs 7h adequate / 6h marginal.
    below_6h = sum(1 for d in dur if d < 6)
    return {
        "status": "ok",
        "period_days": days,
        "count": len(items),
        "stats": {
            "avg_duration_h": round(sum(dur) / len(dur), 2) if dur else None,
            "min_duration_h": round(min(dur), 2) if dur else None,
            "max_duration_h": round(max(dur), 2) if dur else None,
            "avg_quality": round(sum(qual) / len(qual), 1) if qual else None,
            "nights_below_6h": below_6h,
            "nights_below_6h_pct": round(100 * below_6h / len(dur), 1) if dur else None,
        },
        "items": items[:14],
        "latest_available_date": latest_iso,
    }
