"""FastAPI router for the nutrition day editor.

All endpoints require a valid Telegram WebApp initData in `Authorization: tma <initData>`.
User scope is enforced by extracting user_id from verified initData.
"""

from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Query

from database import SessionLocal
from database.crud import (
    get_nutrition_logs_by_date,
    get_nutrition_totals_by_date,
)
from webhook.apple_health import get_tg_user
from webhook.nutrition_slots import slot_from_meal
from webhook.nutrition_goals import compute_goals

router = APIRouter()


def _item_to_wire(idx: int, it: dict) -> dict:
    return {
        "idx": idx,
        "name": it.get("product") or it.get("name") or "",
        "weight": round(float(it.get("weight_g") or 0), 1),
        "kcal": round(float(it.get("calories") or 0), 1),
        "p": round(float(it.get("protein") or 0), 1),
        "f": round(float(it.get("fats") or 0), 1),
        "c": round(float(it.get("carbs") or 0), 1),
        "fib": round(float(it.get("fiber") or 0), 1),
    }


def _totals_to_wire(t: dict) -> dict:
    return {
        "kcal": round(float(t.get("calories") or 0), 1),
        "p": round(float(t.get("protein") or 0), 1),
        "f": round(float(t.get("fats") or 0), 1),
        "c": round(float(t.get("carbs") or 0), 1),
        "fib": round(float(t.get("fiber") or 0), 1),
    }


@router.get("/api/day")
async def get_day(
    date: str = Query(..., description="YYYY-MM-DD"),
    tg_user: dict = Depends(get_tg_user),
):
    try:
        for_date = date_type.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date {date!r}, use YYYY-MM-DD")

    user_id = tg_user.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="No user id in initData")

    db = SessionLocal()
    try:
        rows = get_nutrition_logs_by_date(db, user_id=user_id, date=for_date)
        meals = []
        for r in rows:
            slot = slot_from_meal(r.meal_name, r.meal_time)
            meals.append(
                {
                    "id": r.id,
                    "meal_name": r.meal_name,
                    "meal_time": r.meal_time.strftime("%H:%M") if r.meal_time else None,
                    "slot": slot,
                    "items": [_item_to_wire(i, it) for i, it in enumerate(r.items or [])],
                    "totals": _totals_to_wire(r.totals or {}),
                }
            )
        totals_day = _totals_to_wire(get_nutrition_totals_by_date(db, user_id=user_id, date=for_date))
        goals = compute_goals(user_id=user_id, for_date=for_date)
    finally:
        db.close()

    return {
        "date": for_date.isoformat(),
        "meals": meals,
        "totals_day": totals_day,
        "goals": goals,
    }
