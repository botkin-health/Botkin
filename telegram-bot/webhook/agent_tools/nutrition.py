"""Agent tools: meal logging, editing, and meal-context for the LLM."""

import logging
import math
from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from webhook.jwt_auth import get_agent_user, get_db, require_agent_scope
from .common import _today_in_user_tz, _as_dict, _resolve_user_kb_path, _parse_date

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent", tags=["agent-tools-nutrition"])


class LogMealTextRequest(BaseModel):
    text: str
    date: Optional[str] = None  # YYYY-MM-DD; defaults to today
    slot: Optional[str] = None  # breakfast | lunch | dinner | snack; auto-detected if None
    as_plan: bool = False  # #407 план→факт: True — записать со status='plan' (еда внесена авансом)


class EditMealRequest(BaseModel):
    meal_id: int
    new_date: Optional[str] = None  # YYYY-MM-DD — перенести на другой день
    new_slot: Optional[str] = None  # breakfast | lunch | dinner | snack — сменить слот/время
    new_name: Optional[str] = None  # переименовать


class DeleteMealRequest(BaseModel):
    meal_id: int


class AdjustChange(BaseModel):
    idx: int
    new_weight: Optional[float] = None
    remove: bool = False

    @field_validator("new_weight")
    @classmethod
    def _weight_finite_non_negative(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v
        if not math.isfinite(v) or v < 0:
            raise ValueError("new_weight must be a finite number >= 0")
        return v


class AdjustMealItemsRequest(BaseModel):
    meal_id: int
    changes: List[AdjustChange] = []
    leftover_to_slot: Optional[str] = None  # breakfast/lunch/dinner/snack → остаток новой записью-планом
    leftover_to_date: Optional[str] = None  # YYYY-MM-DD, по умолчанию сегодня
    close_plan: bool = False
    dry_run: bool = True  # безопасный дефолт: без явного dry_run=false ничего не меняем


def _slot_to_meal_time(slot: Optional[str]):
    """Map slot name to a default meal time."""
    from datetime import time as time_cls

    mapping = {
        "breakfast": time_cls(8, 0),
        "lunch": time_cls(13, 0),
        "dinner": time_cls(19, 0),
        "snack": time_cls(16, 0),
    }
    if slot is None:
        return time_cls(12, 0), "Приём пищи"
    slot = slot.lower()
    if slot not in mapping:
        raise HTTPException(status_code=400, detail=f"Invalid slot {slot!r}. Use: breakfast, lunch, dinner, snack.")
    name_map = {
        "breakfast": "Завтрак",
        "lunch": "Обед",
        "dinner": "Ужин",
        "snack": "Перекус",
    }
    return mapping[slot], name_map[slot]


@router.post("/log_meal_text")
async def log_meal_text(
    req: LogMealTextRequest,
    user=Depends(require_agent_scope("rw")),
    db: Session = Depends(get_db),
):
    """Parse free-text meal description and save to nutrition_log.

    Attempts to use the existing food parsing pipeline. Falls back to a stub
    that stores the raw text when the parser is not available / tightly coupled.
    """
    from database.crud import create_nutrition_log
    from core.llm.router import analyze_message
    from core.food.nutrition import process_llm_food_data

    record_date = _parse_date(req.date, user)
    meal_time, meal_name = _slot_to_meal_time(req.slot)

    # Use the real food parser (Claude vision/text via core.llm.router).
    # Returns dict like {"type": "food", "data": {...}} which the photo/text
    # handlers feed into process_llm_food_data() to get (items, totals).
    items: list = []
    totals: dict = {}
    parse_error: Optional[str] = None

    try:
        llm_result = analyze_message(text=req.text, user_id=user.telegram_id)
        if not llm_result or llm_result.get("type") != "food":
            parse_error = (
                "LLM не распознал это как еду "
                f"(type={llm_result.get('type') if llm_result else 'None'}). "
                "Опиши конкретнее: что, сколько, как приготовлено."
            )
        else:
            items, totals = process_llm_food_data(llm_result, req.text)
    except Exception as e:
        logger.exception("log_meal_text: parser failed")
        parse_error = f"парсер упал: {e}"

    # Refuse to write a row if we got no KБЖУ — empty rows break the
    # Mini App dashboard (None aggregations) and are useless to the user.
    if not items or not (totals.get("calories") or 0):
        return {
            "status": "rejected",
            "reason": parse_error or "не удалось распарсить КБЖУ для этого описания",
            "hint": "опиши подробнее: продукт + примерный вес/количество, например 'куриная грудка 200г и рис 150г'",
        }

    # Normalize fiber default so JSONB stores 0, not null
    if totals.get("fiber") is None:
        totals["fiber"] = 0

    log_status = "plan" if req.as_plan else "eaten"
    log = create_nutrition_log(
        db=db,
        user_id=user.telegram_id,
        date=record_date,
        meal_time=meal_time,
        meal_name=meal_name,
        items=items,
        totals=totals,
        status=log_status,
    )

    return {
        "status": "ok",
        "meal_id": log.id,
        "date": record_date.isoformat(),
        "slot": req.slot or "auto",
        "meal_name": meal_name,
        "items_count": len(items),
        "totals": totals,
        "meal": {"id": log.id, "status": log_status},
    }


@router.post("/edit_meal")
async def edit_meal(
    req: EditMealRequest,
    user=Depends(require_agent_scope("rw")),
    db: Session = Depends(get_db),
):
    """Изменить уже залогированный приём пищи: перенести на дату (new_date),
    сменить слот/время (new_slot), переименовать (new_name). meal_id — из recent_meals."""
    from database.crud import update_nutrition_meal_fields

    meal_name = req.new_name
    meal_time = None
    if req.new_slot:
        meal_time, _slot_default_name = _slot_to_meal_time(req.new_slot)
    new_date = _parse_date(req.new_date, user) if req.new_date else None

    if meal_name is None and meal_time is None and new_date is None:
        raise HTTPException(status_code=400, detail="Nothing to change: pass new_date, new_slot or new_name.")

    try:
        row = update_nutrition_meal_fields(
            db,
            meal_id=req.meal_id,
            user_id=user.telegram_id,
            meal_name=meal_name,
            meal_time=meal_time,
            new_date=new_date,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail=f"meal {req.meal_id} not found")

    return {
        "status": "ok",
        "meal_id": row.id,
        "date": row.date.isoformat(),
        "meal_time": row.meal_time.strftime("%H:%M") if row.meal_time else None,
        "meal_name": row.meal_name,
    }


@router.post("/delete_meal")
async def delete_meal(
    req: DeleteMealRequest,
    user=Depends(require_agent_scope("rw")),
    db: Session = Depends(get_db),
):
    """Удалить залогированный приём пищи по meal_id (из recent_meals)."""
    from database.crud import delete_nutrition_log

    ok = delete_nutrition_log(db, log_id=req.meal_id, user_id=user.telegram_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"meal {req.meal_id} not found")
    return {"status": "ok", "deleted_meal_id": req.meal_id}


@router.post("/adjust_meal_items")
async def adjust_meal_items_ep(
    req: AdjustMealItemsRequest,
    user=Depends(require_agent_scope("rw")),
    db: Session = Depends(get_db),
):
    """#407 план→факт: изменить вес/убрать items внутри записи, вынести остаток планом, закрыть план.
    dry_run=true — только посчитать (превью перед подтверждением)."""
    from database.crud import adjust_meal_items

    if not req.changes and not req.close_plan:
        raise HTTPException(status_code=400, detail="changes is empty and close_plan=false — nothing to do")

    leftover_to = None
    if req.leftover_to_slot:
        mt, default_name = _slot_to_meal_time(req.leftover_to_slot)  # raises 400 on unknown slot
        leftover_to = {
            "date": _parse_date(req.leftover_to_date, user),
            "meal_time": mt,
            "meal_name": f"{default_name} (план)",
        }

    try:
        res = adjust_meal_items(
            db,
            meal_id=req.meal_id,
            user_id=user.telegram_id,
            changes=[c.model_dump() for c in req.changes],
            leftover_to=leftover_to,
            close_plan=req.close_plan,
            dry_run=req.dry_run,
        )
    except (IndexError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except LookupError:
        raise HTTPException(status_code=404, detail=f"meal {req.meal_id} not found")

    return {"status": "ok", "dry_run": req.dry_run, **res}


@router.get("/recent_meals")
async def recent_meals(
    days: int = 7,
    compact: bool = False,
    only_open_plans: bool = False,
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """Return nutrition_log rows for the last N days.

    compact=True — лёгкий формат для поиска по длинному периоду («ел ли я X за
    3 месяца»): `items` становится списком имён продуктов (строки), `totals`
    сводится к калориям. Режет payload в ~5-10 раз (один такой запрос на 90 дней
    раньше стоил ~120k токенов / $2). Авто-включается при days > 14, чтобы один
    вызов не раздувал контекст.

    only_open_plans=True — #407 план→факт: только записи со status='plan' за
    сегодня (открытые планы, ещё не сведённые к факту).
    """
    from database.crud import get_nutrition_logs_by_period

    if days < 1 or days > 90:
        raise HTTPException(status_code=400, detail="days must be between 1 and 90")

    # Длинные окна по умолчанию компактны (защита от token-blowup).
    if days > 14:
        compact = True

    end_date = _today_in_user_tz(user)
    start_date = end_date - timedelta(days=days - 1)

    logs = get_nutrition_logs_by_period(db, user.telegram_id, start_date, end_date)
    if only_open_plans:
        logs = [log for log in logs if log.status == "plan" and log.date == end_date]

    result = []
    for log in logs:
        if compact:
            names = [
                (it.get("food") or it.get("product") or it.get("name") or "").strip()
                for it in (log.items or [])
                if (it.get("food") or it.get("product") or it.get("name"))
            ]
            items_out = names
            totals_out = {"calories": (log.totals or {}).get("calories")}
        else:
            items_out = log.items
            totals_out = log.totals
        result.append(
            {
                "id": log.id,
                "date": log.date.isoformat(),
                "meal_time": log.meal_time.strftime("%H:%M") if log.meal_time else None,
                "meal_name": log.meal_name,
                "items": items_out,
                "totals": totals_out,
                "status": log.status,
            }
        )

    return {
        "status": "ok",
        "days": days,
        "compact": compact,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "meals": result,
    }


@router.get("/meal_context")
async def meal_context(
    user=Depends(get_agent_user),
    db: Session = Depends(get_db),
):
    """P-002: всё нужное для «что мне съесть сейчас» ОДНИМ вызовом —
    остаток КБЖУ на сегодня + ограничения (диагнозы) + аллергии + любимые продукты.

    Зачем тул, а не три вызова: гарантирует, что ограничения-диагнозы (подагра,
    демпинг-синдром и т.п.) ВСЕГДА в контексте, и экономит токены/реплики.

    Источники ограничений по приоритету: KB-файл юзера → `users.onboarding_data`
    (#340; у самозарегистрированного юзера KB нет вовсе). Фактический источник —
    в поле `constraints_source` ∈ {kb, onboarding, none}.
    """
    import json

    from core.health.caloric_budget import get_daily_budget
    from database.crud import get_nutrition_totals_by_date, get_recent_product_names

    today = _today_in_user_tz(user)

    # Бюджет (consumed/target/remaining) — self-contained хелпер со своей сессией.
    try:
        budget = get_daily_budget(user.telegram_id, for_date=today)
    except Exception:
        logger.exception("meal_context: get_daily_budget failed")
        budget = {}

    totals = get_nutrition_totals_by_date(db, user.telegram_id, today) or {}

    try:
        products = get_recent_product_names(db, user.telegram_id, limit=15, lookback_days=60)
    except Exception:
        products = []

    # Ограничения из KB (диагнозы) — чтобы советы были безопасны под состояние.
    constraints = []
    constraints_source = "none"
    kb_path, _src = _resolve_user_kb_path(user)
    if kb_path:
        try:
            kb = _as_dict(json.loads(kb_path.read_text(encoding="utf-8")))
            for key in ("chronic_diagnoses", "diagnoses", "conditions"):
                v = kb.get(key)
                if v:
                    constraints = v if isinstance(v, list) else [v]
                    constraints_source = "kb"
                    break
        except Exception:
            logger.exception("meal_context: KB read failed")

    # #340: у самозарегистрированного юзера KB-файла нет вовсе — диагнозы лежат
    # в users.onboarding_data (пишет /doc через merge_onboarding_lists). Без этого
    # fallback тул отдавал constraints=[] и советы шли как здоровому.
    # Аллергии для «что съесть» критичнее диагнозов — отдаём отдельным полем.
    from core.health.onboarding_lists import ALLERGY_KEYS, CONDITION_KEYS, onboarding_list

    onboarding = user.onboarding_data or {}
    if not constraints:
        constraints = onboarding_list(onboarding, CONDITION_KEYS)
        if constraints:
            constraints_source = "onboarding"
    allergies = onboarding_list(onboarding, ALLERGY_KEYS)

    return {
        "status": "ok",
        "date": today.isoformat(),
        "budget": {
            "target_kcal": budget.get("target"),
            "consumed_kcal": budget.get("consumed"),
            "remaining_kcal": budget.get("remaining"),
        },
        "eaten_today": {
            "calories": totals.get("calories"),
            "protein": totals.get("protein"),
            "fats": totals.get("fats"),
            "carbs": totals.get("carbs"),
            "fiber": totals.get("fiber"),
        },
        "constraints": constraints,
        "constraints_source": constraints_source,
        "allergies": allergies,
        "frequent_products": products[:15],
    }
