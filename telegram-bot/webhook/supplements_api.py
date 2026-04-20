"""FastAPI router for supplements daily tracking in the mini-app.

Endpoints:
  GET    /api/supplements/day?date=YYYY-MM-DD
           Returns planned list from user settings grouped by slot, with per-item
           taken_at time (null if not taken today). Includes aggregate progress.

  POST   /api/supplements/take
           Body: {"date": "YYYY-MM-DD", "name": "Витамин D3"}
           Creates a supplements_log row with current MSK time.

  DELETE /api/supplements/take
           Body: {"date": "YYYY-MM-DD", "name": "Витамин D3"}
           Deletes the most recent supplements_log row for that (date, name).

All endpoints require a valid Telegram WebApp initData via `get_tg_user`.
"""

from datetime import date as date_type, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from database import SessionLocal
from database.crud import (
    create_supplement_log,
    get_supplements_by_date,
    get_user_settings,
)
from database.models import SupplementLog
from webhook.tg_auth import get_tg_user

router = APIRouter()

MSK = timezone(timedelta(hours=3))

# Mirror the slot order used in the mini-app UI.
SLOTS = ("morning_before", "morning_with", "evening")
SLOT_LABELS = {
    "morning_before": "☀️ Утро (до еды)",
    "morning_with": "🌅 Утро (с завтраком)",
    "evening": "🌙 Вечер",
}


class SupplementTakePayload(BaseModel):
    date: str = Field(..., description="YYYY-MM-DD")
    name: str = Field(..., min_length=1, max_length=255)


def _parse_date(date_str: str) -> date_type:
    try:
        return date_type.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date {date_str!r}, use YYYY-MM-DD")


@router.get("/api/supplements/day")
async def get_supplements_day(
    date: str,
    tg_user: dict = Depends(get_tg_user),
):
    """Return planned supplements for the day, grouped by slot, with taken_at times."""
    for_date = _parse_date(date)
    user_id = tg_user.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="No user id in initData")

    db = SessionLocal()
    try:
        s = get_user_settings(db, user_id=user_id)
        planned = (s.supplements or []) if s else []
        taken_logs = get_supplements_by_date(db, user_id=user_id, date=for_date)

        # Build a map of name (case-insensitive) → earliest taken_at time string
        # so duplicates in log (if any) collapse to the first recorded time.
        taken_map: dict[str, tuple[str, int]] = {}
        for log in taken_logs:
            key = log.supplement_name.lower().strip()
            tstr = log.time.strftime("%H:%M") if log.time else ""
            # Keep the earliest time per name
            if key not in taken_map or tstr < taken_map[key][0]:
                taken_map[key] = (tstr, log.id)

        slots: dict[str, list[dict]] = {k: [] for k in SLOTS}
        total = 0
        taken_count = 0
        for item in planned:
            name = (item.get("name") or "").strip()
            slot = item.get("slot") or "morning_with"
            if slot not in slots:
                slot = "morning_with"
            key = name.lower()
            taken = taken_map.get(key)
            slots[slot].append(
                {
                    "name": name,
                    "taken_at": taken[0] if taken else None,
                    "log_id": taken[1] if taken else None,
                }
            )
            total += 1
            if taken:
                taken_count += 1

        return {
            "date": for_date.isoformat(),
            "slots": [{"slot": k, "label": SLOT_LABELS[k], "items": slots[k]} for k in SLOTS],
            "progress": {"taken": taken_count, "total": total},
        }
    finally:
        db.close()


@router.post("/api/supplements/take", status_code=201)
async def take_supplement(
    payload: SupplementTakePayload,
    tg_user: dict = Depends(get_tg_user),
):
    """Log a supplement as taken now. Idempotent guard: if the same name is
    already logged for this date, return existing log without creating a dupe.
    """
    for_date = _parse_date(payload.date)
    user_id = tg_user.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="No user id in initData")

    db = SessionLocal()
    try:
        # Idempotency check — avoid dupes if user double-taps
        existing = (
            db.query(SupplementLog)
            .filter(
                SupplementLog.user_id == user_id,
                SupplementLog.date == for_date,
                SupplementLog.supplement_name.ilike(payload.name.strip()),
            )
            .order_by(SupplementLog.time.desc())
            .first()
        )
        if existing:
            return {
                "status": "already_taken",
                "log_id": existing.id,
                "taken_at": existing.time.strftime("%H:%M") if existing.time else None,
            }

        now_msk = datetime.now(MSK).time().replace(microsecond=0)
        log = create_supplement_log(
            db,
            user_id=user_id,
            date=for_date,
            time=now_msk,
            supplement_name=payload.name.strip(),
        )
        return {
            "status": "created",
            "log_id": log.id,
            "taken_at": log.time.strftime("%H:%M") if log.time else None,
        }
    finally:
        db.close()


@router.delete("/api/supplements/take")
async def untake_supplement(
    payload: SupplementTakePayload,
    tg_user: dict = Depends(get_tg_user),
):
    """Remove the most recent log entry for a given (date, name)."""
    for_date = _parse_date(payload.date)
    user_id = tg_user.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="No user id in initData")

    db = SessionLocal()
    try:
        row = (
            db.query(SupplementLog)
            .filter(
                SupplementLog.user_id == user_id,
                SupplementLog.date == for_date,
                SupplementLog.supplement_name.ilike(payload.name.strip()),
            )
            .order_by(SupplementLog.time.desc())
            .first()
        )
        if not row:
            return {"status": "not_found"}
        db.delete(row)
        db.commit()
        return {"status": "deleted", "log_id": row.id}
    finally:
        db.close()
