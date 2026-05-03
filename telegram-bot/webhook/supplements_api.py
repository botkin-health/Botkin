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

from collections import defaultdict, deque
from datetime import date as date_type, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from database import SessionLocal
from database.crud import (
    create_supplement_log,
    get_supplements_by_date,
    get_user_settings,
    upsert_user_settings,
)
from database.models import SupplementLog
from core.health.supplements import (
    DEFAULT_SUPPLEMENTS,
    default_dose_for,
    delete_mirror_nutrition_for,
    mirror_supplement_to_nutrition,
    needs_legacy_migration,
    normalize_supplement_name,
)
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
        if needs_legacy_migration(planned):
            upsert_user_settings(db, user_id, supplements=DEFAULT_SUPPLEMENTS)
            planned = DEFAULT_SUPPLEMENTS
        taken_logs = get_supplements_by_date(db, user_id=user_id, date=for_date)

        # Build a map: name → deque of (time_str, log_id) sorted ascending by time.
        # Each scheduled occurrence consumes one log entry (FIFO), so a supplement
        # scheduled twice (morning + evening) requires two log entries to show both
        # as taken — one log entry only marks the first scheduled occurrence.
        taken_by_name: dict[str, deque] = defaultdict(deque)
        for log in sorted(taken_logs, key=lambda l: l.time or datetime.min.time()):
            key = normalize_supplement_name(log.supplement_name)
            tstr = log.time.strftime("%H:%M") if log.time else ""
            taken_by_name[key].append((tstr, log.id))

        slots: dict[str, list[dict]] = {k: [] for k in SLOTS}
        total = 0
        taken_count = 0
        for item in planned:
            name = (item.get("name") or "").strip()
            slot = item.get("slot") or "morning_with"
            if slot not in slots:
                slot = "morning_with"
            key = normalize_supplement_name(name)
            # Consume one log entry per scheduled occurrence (FIFO by time).
            entry = taken_by_name[key].popleft() if taken_by_name[key] else None
            # Prefer per-item dose from user settings; fall back to canonical default.
            dose = item.get("dose") or default_dose_for(name)
            slots[slot].append(
                {
                    "name": name,
                    "dose": dose,
                    "taken_at": entry[0] if entry else None,
                    "log_id": entry[1] if entry else None,
                }
            )
            total += 1
            if entry:
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
        s = get_user_settings(db, user_id=user_id)
        planned = (s.supplements or []) if s else []

        # How many times is this supplement scheduled today?
        name_lower = payload.name.strip().lower()
        scheduled_count = sum(1 for item in planned if (item.get("name") or "").strip().lower() == name_lower)
        scheduled_count = max(scheduled_count, 1)  # at least 1 even if not in settings

        # How many times already logged today?
        logged_rows = (
            db.query(SupplementLog)
            .filter(
                SupplementLog.user_id == user_id,
                SupplementLog.date == for_date,
                SupplementLog.supplement_name.ilike(payload.name.strip()),
            )
            .order_by(SupplementLog.time.asc())
            .all()
        )
        # Idempotency: if already logged as many times as scheduled, don't add more
        if len(logged_rows) >= scheduled_count:
            last = logged_rows[-1]
            return {
                "status": "already_taken",
                "log_id": last.id,
                "taken_at": last.time.strftime("%H:%M") if last.time else None,
            }

        now_msk = datetime.now(MSK).time().replace(microsecond=0)
        # Look up dose: per-item from settings if present, else canonical default.
        target_key = normalize_supplement_name(payload.name)
        dose = None
        for it in planned:
            if normalize_supplement_name(it.get("name") or "") == target_key:
                dose = it.get("dose")
                if dose:
                    break
        if not dose:
            dose = default_dose_for(payload.name)
        log = create_supplement_log(
            db,
            user_id=user_id,
            date=for_date,
            time=now_msk,
            supplement_name=payload.name.strip(),
            dosage=dose,
        )
        # Auto-log nutritional supplements (psyllium → fiber, whey → protein, etc.)
        # so they show up in the daily food budget. Paired by (date, time).
        mirror_supplement_to_nutrition(db, user_id, for_date, now_msk, payload.name)
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
        # Capture before delete — needed for paired nutrition_log cleanup.
        log_id, supp_time, supp_name = row.id, row.time, row.supplement_name
        db.delete(row)
        db.commit()
        # Remove the mirrored nutrition_log entry, if any.
        delete_mirror_nutrition_for(db, user_id, for_date, supp_time, supp_name)
        return {"status": "deleted", "log_id": log_id}
    finally:
        db.close()
