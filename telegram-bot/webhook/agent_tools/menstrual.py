"""Agent tools: menstrual cycle log."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from webhook.jwt_auth import get_agent_user, get_db

router = APIRouter(prefix="/api/agent", tags=["agent-tools-menstrual"])


@router.get("/menstrual_data")
async def menstrual_data(
    months: int = 6,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Menstrual cycle data from Apple Health (menstrual_log table).

    Returns individual flow records and computed cycle lengths.
    Use for questions about cycle regularity, length, flow intensity.
    """
    from sqlalchemy import text as sql_text

    months = max(1, min(months, 24))
    sql = sql_text(
        """
        SELECT date, flow, source
        FROM menstrual_log
        WHERE user_id = :uid
          AND date >= CURRENT_DATE - (:months * 30)
        ORDER BY date ASC
        """
    )
    rows = db.execute(sql, {"uid": user.telegram_id, "months": months}).fetchall()

    if not rows:
        all_rows = db.execute(
            sql_text("SELECT date, flow, source FROM menstrual_log WHERE user_id=:uid ORDER BY date ASC"),
            {"uid": user.telegram_id},
        ).fetchall()
        if not all_rows:
            return {"status": "ok", "count": 0, "items": [], "cycles": [], "stats": {}}
        rows = all_rows

    items = [{"date": str(r.date), "flow": r.flow} for r in rows]

    # Вычислить начала циклов: первый день после перерыва >2 дней
    from datetime import date as date_type

    period_starts = []
    prev_date = None
    for item in items:
        if item["flow"] == "none":
            prev_date = None
            continue
        d = date_type.fromisoformat(item["date"])
        if prev_date is None or (d - prev_date).days > 2:
            period_starts.append(item["date"])
        prev_date = d

    cycles = []
    for i in range(1, len(period_starts)):
        d1 = date_type.fromisoformat(period_starts[i - 1])
        d2 = date_type.fromisoformat(period_starts[i])
        length = (d2 - d1).days
        if 15 < length < 60:
            cycles.append({"start": period_starts[i - 1], "length_days": length})

    cycle_lengths = [c["length_days"] for c in cycles]
    avg_cycle = round(sum(cycle_lengths) / len(cycle_lengths), 1) if cycle_lengths else None
    variation = round(max(cycle_lengths) - min(cycle_lengths), 0) if len(cycle_lengths) > 1 else 0

    return {
        "status": "ok",
        "count": len(items),
        "period_starts": period_starts,
        "cycles": cycles[-12:],
        "stats": {
            "avg_cycle_days": avg_cycle,
            "variation_days": variation,
            "total_periods": len(period_starts),
        },
        "items": items,
    }
