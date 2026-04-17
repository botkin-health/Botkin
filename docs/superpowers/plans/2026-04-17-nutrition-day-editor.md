# Nutrition Day Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second Telegram Mini App screen ("Дневник") that lets the user view and edit all meals on any day: browse by date, see meals grouped into 4 fixed slots, expand to see products with macros, edit weight (with proportional KBJU scaling), delete with undo, add new products via favorites or manual entry (LLM-resolved). Sticky progress bars in footer against daily goals.

**Architecture:** New FastAPI `APIRouter` in `telegram-bot/webhook/nutrition_api.py`, mounted into the existing Apple Health webhook app (same uvicorn process on port 8081). Reuses `get_tg_user` auth dep. Pure-function slot-mapping module for testability. Vanilla JS extension of `telegram-bot/webapp/index.html` — day editor becomes the default section, existing settings move behind a ⚙️ header button. No build step, no React.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, PostgreSQL (prod) / SQLite (tests), vanilla HTML/CSS/JS, Telegram WebApp SDK (`telegram-web-app.js`).

**Spec:** `docs/superpowers/specs/2026-04-17-nutrition-day-editor-design.md`

---

## File Structure

### New files

| Path | Responsibility |
|---|---|
| `telegram-bot/webhook/nutrition_slots.py` | Pure functions: `slot_from_meal(name, time) → "breakfast"…"dinner"`, `slot_center_time(slot) → time`, `slot_label_ru(slot) → str`. No DB, no IO. Easy to unit-test. |
| `telegram-bot/webhook/nutrition_api.py` | FastAPI `APIRouter` with 7 endpoints. Auth via reused `get_tg_user`. Calls CRUD + `core.food.nutrition.process_meal_description`. |
| `telegram-bot/webhook/nutrition_goals.py` | `compute_goals(user_id, for_date) → {kcal, protein, fats, carbs, fiber}`. Uses `core.health.caloric_budget.get_daily_budget` for kcal; splits 30/30/40 for P/F/C; fixed 30g fiber. |
| `telegram-bot/webapp/day.js` | Day editor logic: day state, fetch, render slots, handle tap/swipe, open sheets, optimistic updates. |
| `telegram-bot/webapp/day.css` | Styles for day editor, slots, bottom sheet, progress bars, snackbar. |
| `tests/test_nutrition_slots.py` | Unit tests for slot mapping. |
| `tests/test_nutrition_goals.py` | Unit tests for goal derivation. |
| `tests/test_nutrition_api.py` | Integration tests for API endpoints using FastAPI `TestClient` and in-memory SQLite. |

### Modified files

| Path | Change |
|---|---|
| `database/crud.py` | Add: `update_nutrition_item_weight`, `delete_nutrition_item`, `update_nutrition_meal_fields`, `get_nutrition_log`, `find_meal_for_slot`, `touch_user_product_usage` (no-op for now, stub for future `last_used_at`), `get_recent_product_names`. |
| `telegram-bot/webhook/apple_health.py` | `app.include_router(nutrition_api.router)` after existing settings endpoints. |
| `telegram-bot/webapp/index.html` | Day editor markup becomes the default section. Settings go behind a `⚙️` button in the header. Load `day.js` + `day.css`. |

### Naming and types — consistent across all tasks

- JSON field names on the wire: `kcal`, `p`, `f`, `c`, `fib` (short, spec-§API). **DB storage uses `calories`, `protein`, `fats`, `carbs`, `fiber`** (existing schema). The API layer is responsible for renaming in both directions.
- Slot identifiers (lowercase English, stable): `"breakfast"`, `"lunch"`, `"snack"`, `"dinner"`.
- Slot Russian labels (for `meal_name` when creating new rows): `"Завтрак"`, `"Обед"`, `"Перекус"`, `"Ужин"`.
- Slot center times: `09:00`, `13:00`, `16:00`, `19:00` (`datetime.time`).
- Slot classification from time (used when `meal_name` doesn't match any known label):
  - `06:00 ≤ t < 11:00` → breakfast
  - `11:00 ≤ t < 15:00` → lunch
  - `15:00 ≤ t < 18:00` → snack
  - everything else → dinner

---

## Task 1: Slot mapping module

**Files:**
- Create: `telegram-bot/webhook/nutrition_slots.py`
- Test: `tests/test_nutrition_slots.py`

- [ ] **Step 1: Write failing test for slot_from_time**

`tests/test_nutrition_slots.py`:
```python
from datetime import time
from telegram_bot.webhook.nutrition_slots import (
    slot_from_time, slot_from_meal, slot_center_time, slot_label_ru,
    SLOTS,
)


def test_slot_from_time_boundaries():
    assert slot_from_time(time(6, 0)) == "breakfast"
    assert slot_from_time(time(10, 59)) == "breakfast"
    assert slot_from_time(time(11, 0)) == "lunch"
    assert slot_from_time(time(14, 59)) == "lunch"
    assert slot_from_time(time(15, 0)) == "snack"
    assert slot_from_time(time(17, 59)) == "snack"
    assert slot_from_time(time(18, 0)) == "dinner"
    assert slot_from_time(time(23, 59)) == "dinner"
    assert slot_from_time(time(0, 0)) == "dinner"
    assert slot_from_time(time(5, 59)) == "dinner"


def test_slot_from_meal_name_priority():
    # Name match wins over time
    assert slot_from_meal("Завтрак", time(14, 0)) == "breakfast"
    assert slot_from_meal("breakfast", time(14, 0)) == "breakfast"
    assert slot_from_meal("🌅 Завтрак дома", time(14, 0)) == "breakfast"
    assert slot_from_meal("Обед", time(8, 0)) == "lunch"
    assert slot_from_meal("Перекус", time(21, 0)) == "snack"
    assert slot_from_meal("Ужин", time(8, 0)) == "dinner"


def test_slot_from_meal_falls_back_to_time():
    assert slot_from_meal("", time(13, 0)) == "lunch"
    assert slot_from_meal(None, time(13, 0)) == "lunch"
    assert slot_from_meal("12:30", time(12, 30)) == "lunch"
    assert slot_from_meal("Что-то непонятное", time(10, 0)) == "breakfast"


def test_slot_from_meal_no_time():
    # When time is None, default to a deterministic slot (breakfast)
    assert slot_from_meal(None, None) == "breakfast"
    assert slot_from_meal("", None) == "breakfast"


def test_slot_center_time():
    assert slot_center_time("breakfast") == time(9, 0)
    assert slot_center_time("lunch") == time(13, 0)
    assert slot_center_time("snack") == time(16, 0)
    assert slot_center_time("dinner") == time(19, 0)


def test_slot_label_ru():
    assert slot_label_ru("breakfast") == "Завтрак"
    assert slot_label_ru("lunch") == "Обед"
    assert slot_label_ru("snack") == "Перекус"
    assert slot_label_ru("dinner") == "Ужин"


def test_slots_order():
    assert SLOTS == ("breakfast", "lunch", "snack", "dinner")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_nutrition_slots.py -v`
Expected: FAIL — ModuleNotFoundError `telegram_bot.webhook.nutrition_slots`.

> Note: the top-level package for tests resolves to `telegram-bot` via a `conftest.py` path hack in existing tests. If import errors occur, use `sys.path` prepend or a relative-path import matching the pattern in `tests/conftest.py`. If needed, add to `tests/conftest.py`:
> ```python
> import sys; from pathlib import Path
> sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))
> ```
> Then import as `from webhook.nutrition_slots import ...` in tests. Use whichever import path the rest of the repo uses for sibling tests on `telegram-bot/`. Check `tests/test_cmd_day_no_crash.py` for precedent.

- [ ] **Step 3: Implement the module**

`telegram-bot/webhook/nutrition_slots.py`:
```python
"""Pure slot mapping for the nutrition day editor.

A "slot" is one of the 4 fixed meal buckets used by the UI:
breakfast / lunch / snack / dinner. DB stores free-form meal_name + meal_time;
this module resolves each meal into exactly one slot.
"""

from datetime import time
from typing import Optional

SLOTS = ("breakfast", "lunch", "snack", "dinner")

_RU_LABELS = {
    "breakfast": "Завтрак",
    "lunch": "Обед",
    "snack": "Перекус",
    "dinner": "Ужин",
}

_CENTER_TIMES = {
    "breakfast": time(9, 0),
    "lunch": time(13, 0),
    "snack": time(16, 0),
    "dinner": time(19, 0),
}

# Tokens that identify each slot when found as substring (case-insensitive).
_NAME_TOKENS = {
    "breakfast": ("завтрак", "breakfast"),
    "lunch": ("обед", "lunch"),
    "snack": ("перекус", "snack", "snacks"),
    "dinner": ("ужин", "dinner", "supper"),
}


def slot_from_time(t: time) -> str:
    h = t.hour
    if 6 <= h < 11:
        return "breakfast"
    if 11 <= h < 15:
        return "lunch"
    if 15 <= h < 18:
        return "snack"
    return "dinner"


def slot_from_meal(name: Optional[str], t: Optional[time]) -> str:
    if name:
        lowered = name.lower()
        for slot, tokens in _NAME_TOKENS.items():
            if any(tok in lowered for tok in tokens):
                return slot
    if t is not None:
        return slot_from_time(t)
    return "breakfast"


def slot_center_time(slot: str) -> time:
    return _CENTER_TIMES[slot]


def slot_label_ru(slot: str) -> str:
    return _RU_LABELS[slot]
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `pytest tests/test_nutrition_slots.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add telegram-bot/webhook/nutrition_slots.py tests/test_nutrition_slots.py
git commit -m "feat(nutrition): add slot mapping module for day editor"
```

---

## Task 2: Goals derivation

**Files:**
- Create: `telegram-bot/webhook/nutrition_goals.py`
- Test: `tests/test_nutrition_goals.py`

Spec note: existing `UserSettings` table has no per-macro goals. For MVP we compute goals server-side from the existing caloric budget (kcal) + a fixed macro split: 30% protein / 30% fats / 40% carbs (typical balanced split, matches what `HEALTH.md` implies), fiber = 30g fixed (WHO recommendation). These are defaults until explicit per-macro goals are added to settings — out of scope here.

- [ ] **Step 1: Write failing test**

`tests/test_nutrition_goals.py`:
```python
from datetime import date
from unittest.mock import patch
from telegram_bot.webhook.nutrition_goals import compute_goals


def test_compute_goals_full_budget():
    fake_budget = {"target": 2000, "consumed": 0, "remaining": 2000, "pct": 0, "warn": False, "has_garmin": True}
    with patch("telegram_bot.webhook.nutrition_goals.get_daily_budget", return_value=fake_budget):
        g = compute_goals(user_id=895655, for_date=date(2026, 4, 17))
    assert g == {
        "kcal": 2000,
        "protein": 150,  # 2000 * 0.30 / 4
        "fats": 67,      # round(2000 * 0.30 / 9) == 67
        "carbs": 200,    # 2000 * 0.40 / 4
        "fiber": 30,
    }


def test_compute_goals_missing_target_returns_none_kcal():
    fake_budget = {"target": None, "consumed": 0, "remaining": 0, "pct": 0, "warn": False, "has_garmin": False}
    with patch("telegram_bot.webhook.nutrition_goals.get_daily_budget", return_value=fake_budget):
        g = compute_goals(user_id=895655, for_date=date(2026, 4, 17))
    # Fallback: all Nones except fiber (fixed). UI will render values without bars.
    assert g == {"kcal": None, "protein": None, "fats": None, "carbs": None, "fiber": 30}
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `pytest tests/test_nutrition_goals.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

`telegram-bot/webhook/nutrition_goals.py`:
```python
"""Derive daily macro goals from caloric budget + fixed split.

Used by GET /api/day to populate progress bars.
"""

from datetime import date as date_type
from typing import Optional

from core.health.caloric_budget import get_daily_budget

PROTEIN_SHARE = 0.30
FATS_SHARE = 0.30
CARBS_SHARE = 0.40
FIBER_GOAL_G = 30  # WHO recommendation, fixed until per-user override is added


def compute_goals(user_id: int, for_date: Optional[date_type] = None) -> dict:
    budget = get_daily_budget(user_id=user_id, for_date=for_date)
    kcal = budget.get("target")
    if not kcal:
        return {"kcal": None, "protein": None, "fats": None, "carbs": None, "fiber": FIBER_GOAL_G}
    return {
        "kcal": int(kcal),
        "protein": round(kcal * PROTEIN_SHARE / 4),
        "fats": round(kcal * FATS_SHARE / 9),
        "carbs": round(kcal * CARBS_SHARE / 4),
        "fiber": FIBER_GOAL_G,
    }
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `pytest tests/test_nutrition_goals.py -v`

- [ ] **Step 5: Commit**

```bash
git add telegram-bot/webhook/nutrition_goals.py tests/test_nutrition_goals.py
git commit -m "feat(nutrition): add goals derivation from caloric budget"
```

---

## Task 3: CRUD helpers for item-level edits

**Files:**
- Modify: `database/crud.py`
- Test: add tests to `tests/test_nutrition_api.py` (created in Task 5) OR inline in existing `tests/test_nutrition_service.py`. Use new `tests/test_nutrition_crud.py`.
- Create: `tests/test_nutrition_crud.py`

Spec requires proportional scaling on weight change, item-level delete (with automatic meal deletion when last item is removed), and recent-products aggregation (since there's no `last_used_at` column — we derive from `nutrition_log.items` history).

- [ ] **Step 1: Write failing tests**

`tests/test_nutrition_crud.py`:
```python
import pytest
from datetime import date, time, timedelta

from database.crud import (
    create_nutrition_log,
    get_nutrition_log,
    update_nutrition_item_weight,
    delete_nutrition_item,
    update_nutrition_meal_fields,
    find_meal_for_slot,
    get_recent_product_names,
)


@pytest.fixture
def sample_meal(test_db):
    return create_nutrition_log(
        db=test_db,
        user_id=895655,
        date=date(2026, 4, 17),
        meal_time=time(13, 0),
        meal_name="Обед",
        items=[
            {"product": "Курица", "weight_g": 100, "calories": 165, "protein": 31, "fats": 3.6, "carbs": 0, "fiber": 0},
            {"product": "Рис", "weight_g": 150, "calories": 195, "protein": 4.5, "fats": 1.5, "carbs": 42, "fiber": 2},
        ],
        totals={"calories": 360, "protein": 35.5, "fats": 5.1, "carbs": 42, "fiber": 2},
    )


def test_get_nutrition_log_returns_row(test_db, sample_meal):
    row = get_nutrition_log(test_db, meal_id=sample_meal.id, user_id=895655)
    assert row is not None
    assert len(row.items) == 2
    assert row.totals["calories"] == 360


def test_get_nutrition_log_enforces_user_scope(test_db, sample_meal):
    assert get_nutrition_log(test_db, meal_id=sample_meal.id, user_id=111) is None


def test_update_nutrition_item_weight_scales_proportionally(test_db, sample_meal):
    updated_item, new_totals = update_nutrition_item_weight(
        db=test_db, meal_id=sample_meal.id, user_id=895655, idx=0, new_weight=200
    )
    # Курица: 100 → 200, KBJU doubles
    assert updated_item["weight_g"] == 200
    assert updated_item["calories"] == pytest.approx(330, abs=1)
    assert updated_item["protein"] == pytest.approx(62, abs=0.1)
    # Totals recomputed: (330 + 195) kcal
    assert new_totals["calories"] == pytest.approx(525, abs=1)


def test_update_item_weight_bad_idx(test_db, sample_meal):
    with pytest.raises(IndexError):
        update_nutrition_item_weight(
            db=test_db, meal_id=sample_meal.id, user_id=895655, idx=9, new_weight=100
        )


def test_update_item_weight_wrong_user_raises(test_db, sample_meal):
    with pytest.raises(LookupError):
        update_nutrition_item_weight(
            db=test_db, meal_id=sample_meal.id, user_id=111, idx=0, new_weight=200
        )


def test_delete_nutrition_item_keeps_meal_if_others_remain(test_db, sample_meal):
    removed, new_totals = delete_nutrition_item(
        db=test_db, meal_id=sample_meal.id, user_id=895655, idx=0
    )
    assert removed["product"] == "Курица"
    row = get_nutrition_log(test_db, meal_id=sample_meal.id, user_id=895655)
    assert row is not None
    assert len(row.items) == 1
    assert row.items[0]["product"] == "Рис"
    assert new_totals["calories"] == pytest.approx(195, abs=1)


def test_delete_last_item_removes_meal(test_db, sample_meal):
    delete_nutrition_item(db=test_db, meal_id=sample_meal.id, user_id=895655, idx=0)
    delete_nutrition_item(db=test_db, meal_id=sample_meal.id, user_id=895655, idx=0)
    assert get_nutrition_log(test_db, meal_id=sample_meal.id, user_id=895655) is None


def test_update_meal_fields(test_db, sample_meal):
    updated = update_nutrition_meal_fields(
        db=test_db, meal_id=sample_meal.id, user_id=895655,
        meal_name="Поздний обед", meal_time=time(15, 30),
    )
    assert updated.meal_name == "Поздний обед"
    assert updated.meal_time == time(15, 30)


def test_update_meal_fields_partial(test_db, sample_meal):
    updated = update_nutrition_meal_fields(
        db=test_db, meal_id=sample_meal.id, user_id=895655,
        meal_name=None, meal_time=time(14, 0),
    )
    assert updated.meal_name == "Обед"  # unchanged
    assert updated.meal_time == time(14, 0)


def test_find_meal_for_slot_matches_by_name(test_db, sample_meal):
    row = find_meal_for_slot(test_db, user_id=895655, for_date=date(2026, 4, 17), slot="lunch")
    assert row is not None
    assert row.id == sample_meal.id


def test_find_meal_for_slot_none_if_missing(test_db, sample_meal):
    row = find_meal_for_slot(test_db, user_id=895655, for_date=date(2026, 4, 17), slot="dinner")
    assert row is None


def test_get_recent_product_names_aggregates(test_db):
    d1 = date(2026, 4, 10)
    d2 = date(2026, 4, 17)
    create_nutrition_log(test_db, user_id=895655, date=d1, meal_time=time(9, 0), meal_name="Завтрак",
                         items=[{"product": "Кофе", "weight_g": 200, "calories": 10, "protein": 0, "fats": 0, "carbs": 2, "fiber": 0}],
                         totals={"calories": 10, "protein": 0, "fats": 0, "carbs": 2, "fiber": 0})
    create_nutrition_log(test_db, user_id=895655, date=d2, meal_time=time(9, 0), meal_name="Завтрак",
                         items=[
                             {"product": "Кофе", "weight_g": 200, "calories": 10, "protein": 0, "fats": 0, "carbs": 2, "fiber": 0},
                             {"product": "Овсянка", "weight_g": 60, "calories": 240, "protein": 8, "fats": 5, "carbs": 42, "fiber": 6},
                         ],
                         totals={"calories": 250, "protein": 8, "fats": 5, "carbs": 44, "fiber": 6})
    # Different user shouldn't leak
    create_nutrition_log(test_db, user_id=111, date=d2, meal_time=time(9, 0), meal_name="Завтрак",
                         items=[{"product": "Чай", "weight_g": 200, "calories": 0, "protein": 0, "fats": 0, "carbs": 0, "fiber": 0}],
                         totals={"calories": 0, "protein": 0, "fats": 0, "carbs": 0, "fiber": 0})

    recents = get_recent_product_names(test_db, user_id=895655, limit=15, lookback_days=90)
    names = [r["name"] for r in recents]
    # Most recent usage first: Овсянка (2026-04-17), then Кофе (also 2026-04-17 latest) — both same date
    assert "Овсянка" in names
    assert "Кофе" in names
    assert "Чай" not in names
    # Each record has last_used date and per_100 nutrients
    for r in recents:
        assert "last_used" in r
        assert "per_100" in r
        for k in ("kcal", "p", "f", "c", "fib"):
            assert k in r["per_100"]
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `pytest tests/test_nutrition_crud.py -v`
Expected: FAIL — helpers don't exist.

- [ ] **Step 3: Add helpers to `database/crud.py`**

Append to end of `database/crud.py`:
```python
def get_nutrition_log(db: Session, meal_id: int, user_id: int) -> Optional[NutritionLog]:
    """Fetch single nutrition log row, scoped by user."""
    return (
        db.query(NutritionLog)
        .filter(NutritionLog.id == meal_id, NutritionLog.user_id == user_id)
        .first()
    )


def _recalc_totals(items: list) -> dict:
    totals = {"calories": 0.0, "protein": 0.0, "fats": 0.0, "carbs": 0.0, "fiber": 0.0}
    for it in items:
        for src, dst in (("calories", "calories"), ("protein", "protein"),
                         ("fats", "fats"), ("carbs", "carbs"), ("fiber", "fiber")):
            totals[dst] += float(it.get(src, 0) or 0)
    # Round to keep JSON small and display-friendly
    return {k: round(v, 1) for k, v in totals.items()}


def update_nutrition_item_weight(
    db: Session, meal_id: int, user_id: int, idx: int, new_weight: float
) -> tuple[dict, dict]:
    """Scale item KBJU proportionally to new weight. Returns (item, totals)."""
    row = get_nutrition_log(db, meal_id=meal_id, user_id=user_id)
    if row is None:
        raise LookupError(f"meal {meal_id} not found for user {user_id}")
    items = list(row.items or [])
    if idx < 0 or idx >= len(items):
        raise IndexError(f"idx {idx} out of range (have {len(items)} items)")

    old = dict(items[idx])
    old_w = float(old.get("weight_g") or 0)
    if old_w <= 0:
        # Without original weight we can't scale — just set weight, leave macros.
        old["weight_g"] = new_weight
    else:
        factor = new_weight / old_w
        old["weight_g"] = new_weight
        for k in ("calories", "protein", "fats", "carbs", "fiber"):
            if old.get(k) is not None:
                old[k] = round(float(old[k]) * factor, 1)

    items[idx] = old
    row.items = items
    row.totals = _recalc_totals(items)
    # SQLAlchemy JSON fields: must flag_modified to persist in-place edits on some backends
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(row, "items")
    flag_modified(row, "totals")
    db.commit()
    db.refresh(row)
    return old, row.totals


def delete_nutrition_item(
    db: Session, meal_id: int, user_id: int, idx: int
) -> tuple[dict, Optional[dict]]:
    """Remove item. Deletes meal row if it was the last item. Returns (removed, new_totals_or_None)."""
    row = get_nutrition_log(db, meal_id=meal_id, user_id=user_id)
    if row is None:
        raise LookupError(f"meal {meal_id} not found for user {user_id}")
    items = list(row.items or [])
    if idx < 0 or idx >= len(items):
        raise IndexError(f"idx {idx} out of range")
    removed = items.pop(idx)
    if not items:
        db.delete(row)
        db.commit()
        return removed, None
    row.items = items
    row.totals = _recalc_totals(items)
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(row, "items")
    flag_modified(row, "totals")
    db.commit()
    db.refresh(row)
    return removed, row.totals


def update_nutrition_meal_fields(
    db: Session, meal_id: int, user_id: int,
    meal_name: Optional[str] = None, meal_time: Optional[time] = None,
) -> NutritionLog:
    row = get_nutrition_log(db, meal_id=meal_id, user_id=user_id)
    if row is None:
        raise LookupError(f"meal {meal_id} not found for user {user_id}")
    if meal_name is not None:
        row.meal_name = meal_name
    if meal_time is not None:
        row.meal_time = meal_time
    db.commit()
    db.refresh(row)
    return row


def find_meal_for_slot(
    db: Session, user_id: int, for_date: date, slot: str
) -> Optional[NutritionLog]:
    """Find first nutrition_log on that date whose (name,time) maps to `slot`."""
    import sys as _sys, pathlib as _pl
    _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent / "telegram-bot"))
    from webhook.nutrition_slots import slot_from_meal
    rows = get_nutrition_logs_by_date(db, user_id=user_id, date=for_date)
    for r in rows:
        if slot_from_meal(r.meal_name, r.meal_time) == slot:
            return r
    return None


def get_recent_product_names(
    db: Session, user_id: int, limit: int = 15, lookback_days: int = 90
) -> list[dict]:
    """Aggregate recent product usage from nutrition_log.items[]. Sort by last_used DESC."""
    from collections import OrderedDict
    from datetime import date as date_type, timedelta
    end = date_type.today()
    start = end - timedelta(days=lookback_days)
    rows = get_nutrition_logs_by_period(db, user_id=user_id, start_date=start, end_date=end)
    # Most-recent wins: walk from latest to oldest, skip already-seen names.
    by_name: "OrderedDict[str, dict]" = OrderedDict()
    for r in sorted(rows, key=lambda x: (x.date, x.meal_time or time(0, 0)), reverse=True):
        for it in (r.items or []):
            name = (it.get("product") or "").strip()
            if not name or name in by_name:
                continue
            w = float(it.get("weight_g") or 0)
            if w <= 0:
                continue
            def per100(k):
                v = it.get(k)
                return round(float(v) * 100 / w, 1) if v is not None else 0
            by_name[name] = {
                "name": name,
                "default_weight": round(w, 0),
                "last_used": r.date.isoformat(),
                "per_100": {
                    "kcal": per100("calories"),
                    "p": per100("protein"),
                    "f": per100("fats"),
                    "c": per100("carbs"),
                    "fib": per100("fiber"),
                },
            }
            if len(by_name) >= limit:
                break
        if len(by_name) >= limit:
            break
    return list(by_name.values())
```

Notes for the engineer:
- `flag_modified` is required for SQLAlchemy JSON columns when mutating an existing dict/list in-place; the code above reassigns the whole list but we flag anyway for safety on SQLite + Postgres.
- The `find_meal_for_slot` helper imports the slot module via a `sys.path` insert — match whatever pattern the repo already uses (see `telegram-bot/webhook/apple_health.py:150–155`).

- [ ] **Step 4: Run tests — expect PASS**

Run: `pytest tests/test_nutrition_crud.py -v`

- [ ] **Step 5: Commit**

```bash
git add database/crud.py tests/test_nutrition_crud.py
git commit -m "feat(crud): add item-level edit helpers for nutrition_log"
```

---

## Task 4: API router skeleton + `GET /api/day`

**Files:**
- Create: `telegram-bot/webhook/nutrition_api.py`
- Create: `tests/test_nutrition_api.py`

The router is created in this task with just `GET /api/day` wired up. Subsequent tasks add mutations. Tests use FastAPI `TestClient` and stub `get_tg_user` to bypass HMAC (existing pattern from apple_health tests if any — otherwise use `app.dependency_overrides`).

- [ ] **Step 1: Write failing test for GET /api/day**

`tests/test_nutrition_api.py`:
```python
import pytest
from datetime import date, time
from fastapi.testclient import TestClient

from database.crud import create_nutrition_log


@pytest.fixture
def client(test_db, monkeypatch):
    """Build a FastAPI app with only the nutrition router, stub auth, stub SessionLocal."""
    from fastapi import FastAPI
    from webhook import nutrition_api
    # SessionLocal patch so endpoints read the in-memory DB
    monkeypatch.setattr(nutrition_api, "SessionLocal", lambda: test_db)
    # Stub get_tg_user to return our primary user
    nutrition_api.app_for_tests_get_tg_user_override = lambda: {"id": 895655}
    app = FastAPI()
    app.include_router(nutrition_api.router)
    from webhook.apple_health import get_tg_user
    app.dependency_overrides[get_tg_user] = lambda: {"id": 895655}
    return TestClient(app)


def test_get_day_empty(client):
    r = client.get("/api/day?date=2026-04-17")
    assert r.status_code == 200
    body = r.json()
    assert body["date"] == "2026-04-17"
    assert body["meals"] == []
    assert body["totals_day"] == {"kcal": 0, "p": 0, "f": 0, "c": 0, "fib": 0}
    # goals present (shape-check only — values depend on caloric_budget)
    assert set(body["goals"].keys()) == {"kcal", "protein", "fats", "carbs", "fiber"}


def test_get_day_with_meals(client, test_db):
    create_nutrition_log(
        db=test_db, user_id=895655, date=date(2026, 4, 17),
        meal_time=time(13, 0), meal_name="Обед",
        items=[{"product": "Курица", "weight_g": 100, "calories": 165,
                "protein": 31, "fats": 3.6, "carbs": 0, "fiber": 0}],
        totals={"calories": 165, "protein": 31, "fats": 3.6, "carbs": 0, "fiber": 0},
    )
    r = client.get("/api/day?date=2026-04-17")
    assert r.status_code == 200
    body = r.json()
    assert len(body["meals"]) == 1
    meal = body["meals"][0]
    assert meal["slot"] == "lunch"
    assert meal["meal_name"] == "Обед"
    assert meal["meal_time"] == "13:00"
    assert len(meal["items"]) == 1
    item = meal["items"][0]
    assert item == {"idx": 0, "name": "Курица", "weight": 100,
                    "kcal": 165, "p": 31, "f": 3.6, "c": 0, "fib": 0}
    assert body["totals_day"]["kcal"] == 165


def test_get_day_invalid_date(client):
    r = client.get("/api/day?date=not-a-date")
    assert r.status_code == 400


def test_get_day_user_scoped(client, test_db):
    # Other user's meal must not leak
    create_nutrition_log(
        db=test_db, user_id=111, date=date(2026, 4, 17),
        meal_time=time(13, 0), meal_name="Обед",
        items=[{"product": "Пицца", "weight_g": 300, "calories": 800,
                "protein": 30, "fats": 30, "carbs": 90, "fiber": 4}],
        totals={"calories": 800, "protein": 30, "fats": 30, "carbs": 90, "fiber": 4},
    )
    r = client.get("/api/day?date=2026-04-17")
    assert r.json()["meals"] == []
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `pytest tests/test_nutrition_api.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement router skeleton + GET /api/day**

`telegram-bot/webhook/nutrition_api.py`:
```python
"""FastAPI router for the nutrition day editor.

All endpoints require a valid Telegram WebApp initData in `Authorization: tma <initData>`.
User scope is enforced by extracting user_id from verified initData.
"""

import sys
from datetime import date as date_type, time as time_type
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from database import SessionLocal
from database.crud import (
    get_nutrition_logs_by_date,
    get_nutrition_totals_by_date,
)
from webhook.apple_health import get_tg_user
from webhook.nutrition_slots import slot_from_meal, slot_label_ru, slot_center_time, SLOTS
from webhook.nutrition_goals import compute_goals

router = APIRouter()


# ── Serialization helpers ─────────────────────────────────────────────────────

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


# ── GET /api/day ──────────────────────────────────────────────────────────────

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
            meals.append({
                "id": r.id,
                "meal_name": r.meal_name,
                "meal_time": r.meal_time.strftime("%H:%M") if r.meal_time else None,
                "slot": slot,
                "items": [_item_to_wire(i, it) for i, it in enumerate(r.items or [])],
                "totals": _totals_to_wire(r.totals or {}),
            })
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
```

- [ ] **Step 4: Verify import of this module works**

Run:
```bash
python -c "import sys; sys.path.insert(0, 'telegram-bot'); from webhook import nutrition_api; print(nutrition_api.router)"
```
Expected: prints `<fastapi.routing.APIRouter object at ...>` with no ImportError.

- [ ] **Step 5: Run tests — expect PASS**

Run: `pytest tests/test_nutrition_api.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add telegram-bot/webhook/nutrition_api.py tests/test_nutrition_api.py
git commit -m "feat(api): add GET /api/day endpoint for nutrition day editor"
```

---

## Task 5: `POST /api/meal/item` — add product

Add a product into the slot-matching meal, creating a new meal row if needed.

**Files:**
- Modify: `telegram-bot/webhook/nutrition_api.py`
- Modify: `tests/test_nutrition_api.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_nutrition_api.py`:
```python
def test_post_item_creates_new_meal(client, test_db, monkeypatch):
    # Stub LLM pipeline
    def fake_process(description, **kwargs):
        return ([{"product": description, "weight_g": 180, "calories": 220,
                  "protein": 38, "fats": 6, "carbs": 0, "fiber": 0}],
                {"calories": 220, "protein": 38, "fats": 6, "carbs": 0, "fiber": 0})
    from webhook import nutrition_api
    monkeypatch.setattr(nutrition_api, "process_meal_description", fake_process)

    r = client.post("/api/meal/item", json={
        "date": "2026-04-17",
        "slot": "lunch",
        "name": "Курица грудка",
        "weight": 180,
        "source": "manual",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["item"]["name"] == "Курица грудка"
    assert body["item"]["weight"] == 180
    assert body["item"]["kcal"] == 220
    assert "meal_id" in body

    # GET returns it
    day = client.get("/api/day?date=2026-04-17").json()
    assert len(day["meals"]) == 1
    assert day["meals"][0]["slot"] == "lunch"
    assert day["meals"][0]["meal_name"] == "Обед"
    assert day["meals"][0]["meal_time"] == "13:00"


def test_post_item_appends_to_existing_slot(client, test_db, monkeypatch):
    from webhook import nutrition_api
    monkeypatch.setattr(nutrition_api, "process_meal_description",
        lambda desc, **_: ([{"product": desc, "weight_g": 100, "calories": 50,
                              "protein": 1, "fats": 0, "carbs": 12, "fiber": 0}],
                            {"calories": 50, "protein": 1, "fats": 0, "carbs": 12, "fiber": 0}))
    # Seed an existing lunch
    from datetime import date, time
    create_nutrition_log(
        db=test_db, user_id=895655, date=date(2026, 4, 17),
        meal_time=time(13, 0), meal_name="Обед",
        items=[{"product": "Рис", "weight_g": 150, "calories": 195,
                "protein": 4.5, "fats": 1.5, "carbs": 42, "fiber": 2}],
        totals={"calories": 195, "protein": 4.5, "fats": 1.5, "carbs": 42, "fiber": 2},
    )
    r = client.post("/api/meal/item", json={
        "date": "2026-04-17", "slot": "lunch", "name": "Яблоко",
        "weight": 100, "source": "manual",
    })
    assert r.status_code == 201
    day = client.get("/api/day?date=2026-04-17").json()
    assert len(day["meals"]) == 1  # Same meal row, not a second one
    assert len(day["meals"][0]["items"]) == 2
    # Totals summed
    assert day["meals"][0]["totals"]["kcal"] == 245


def test_post_item_bad_slot_400(client):
    r = client.post("/api/meal/item", json={
        "date": "2026-04-17", "slot": "brunch", "name": "x", "weight": 100, "source": "manual",
    })
    assert r.status_code == 400
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/test_nutrition_api.py -v`
Expected: 404 or AttributeError — endpoint not yet defined.

- [ ] **Step 3: Implement POST /api/meal/item**

Append to `telegram-bot/webhook/nutrition_api.py`:
```python
# LLM pipeline (module-level binding so tests can monkeypatch)
from core.food.nutrition import process_meal_description

from database.crud import (
    create_nutrition_log,
    find_meal_for_slot,
    get_nutrition_log,
)
from sqlalchemy.orm.attributes import flag_modified


class AddItemPayload(BaseModel):
    date: str
    slot: str
    name: str = Field(..., min_length=1, max_length=255)
    weight: float = Field(..., gt=0, le=5000)
    source: str = "manual"  # "manual" | "user_product" (reserved for future)


def _scale_to_weight(base: dict, base_w: float, target_w: float) -> dict:
    """Scale macros from `base` (at `base_w` g) to `target_w` g."""
    if base_w <= 0:
        factor = 1.0
    else:
        factor = target_w / base_w
    return {
        "product": base.get("product") or base.get("name") or "",
        "weight_g": round(target_w, 1),
        "calories": round(float(base.get("calories") or 0) * factor, 1),
        "protein": round(float(base.get("protein") or 0) * factor, 1),
        "fats": round(float(base.get("fats") or 0) * factor, 1),
        "carbs": round(float(base.get("carbs") or 0) * factor, 1),
        "fiber": round(float(base.get("fiber") or 0) * factor, 1),
    }


@router.post("/api/meal/item", status_code=201)
async def add_meal_item(
    payload: AddItemPayload,
    tg_user: dict = Depends(get_tg_user),
):
    if payload.slot not in SLOTS:
        raise HTTPException(status_code=400, detail=f"Invalid slot {payload.slot!r}. Must be one of {SLOTS}.")
    try:
        for_date = date_type.fromisoformat(payload.date)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date {payload.date!r}, use YYYY-MM-DD")

    user_id = tg_user.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="No user id in initData")

    # Resolve KBJU via LLM (manual source) — returns items list + totals
    # We only pass the name; weight is authoritative from payload.weight.
    try:
        items_parsed, _totals = process_meal_description(description=payload.name)
    except Exception as e:
        # Graceful degradation: store with zero macros, UI shows red indicator
        items_parsed = [{"product": payload.name, "weight_g": payload.weight,
                         "calories": 0, "protein": 0, "fats": 0, "carbs": 0, "fiber": 0}]

    if not items_parsed:
        items_parsed = [{"product": payload.name, "weight_g": payload.weight,
                         "calories": 0, "protein": 0, "fats": 0, "carbs": 0, "fiber": 0}]

    base = items_parsed[0]
    base_w = float(base.get("weight_g") or 0)
    new_item = _scale_to_weight(base, base_w or payload.weight, payload.weight)

    db = SessionLocal()
    try:
        existing = find_meal_for_slot(db, user_id=user_id, for_date=for_date, slot=payload.slot)
        if existing:
            items = list(existing.items or [])
            items.append(new_item)
            existing.items = items
            existing.totals = _recompute_totals(items)
            flag_modified(existing, "items")
            flag_modified(existing, "totals")
            db.commit()
            db.refresh(existing)
            meal_id = existing.id
            idx = len(items) - 1
        else:
            row = create_nutrition_log(
                db=db, user_id=user_id, date=for_date,
                meal_time=slot_center_time(payload.slot),
                meal_name=slot_label_ru(payload.slot),
                items=[new_item],
                totals=_recompute_totals([new_item]),
            )
            meal_id = row.id
            idx = 0
    finally:
        db.close()

    return {"meal_id": meal_id, "item": _item_to_wire(idx, new_item)}


def _recompute_totals(items: list) -> dict:
    out = {"calories": 0.0, "protein": 0.0, "fats": 0.0, "carbs": 0.0, "fiber": 0.0}
    for it in items:
        for k in out:
            out[k] += float(it.get(k) or 0)
    return {k: round(v, 1) for k, v in out.items()}
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/test_nutrition_api.py -v`

- [ ] **Step 5: Commit**

```bash
git add telegram-bot/webhook/nutrition_api.py tests/test_nutrition_api.py
git commit -m "feat(api): POST /api/meal/item — add product to slot"
```

---

## Task 6: `PATCH /api/meal/item` — change weight

**Files:**
- Modify: `telegram-bot/webhook/nutrition_api.py`
- Modify: `tests/test_nutrition_api.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_nutrition_api.py`:
```python
def test_patch_item_rescales(client, test_db):
    from datetime import date, time
    row = create_nutrition_log(
        db=test_db, user_id=895655, date=date(2026, 4, 17),
        meal_time=time(13, 0), meal_name="Обед",
        items=[{"product": "Курица", "weight_g": 100, "calories": 165,
                "protein": 31, "fats": 3.6, "carbs": 0, "fiber": 0}],
        totals={"calories": 165, "protein": 31, "fats": 3.6, "carbs": 0, "fiber": 0},
    )
    r = client.patch("/api/meal/item", json={"meal_id": row.id, "idx": 0, "weight": 200})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["item"]["weight"] == 200
    assert body["item"]["kcal"] == 330
    assert body["totals"]["kcal"] == 330


def test_patch_item_wrong_user_404(client, test_db):
    from datetime import date, time
    row = create_nutrition_log(
        db=test_db, user_id=111, date=date(2026, 4, 17),
        meal_time=time(13, 0), meal_name="Обед",
        items=[{"product": "X", "weight_g": 100, "calories": 100,
                "protein": 0, "fats": 0, "carbs": 0, "fiber": 0}],
        totals={"calories": 100, "protein": 0, "fats": 0, "carbs": 0, "fiber": 0},
    )
    r = client.patch("/api/meal/item", json={"meal_id": row.id, "idx": 0, "weight": 200})
    assert r.status_code == 404
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/test_nutrition_api.py::test_patch_item_rescales -v`

- [ ] **Step 3: Implement**

Append to `telegram-bot/webhook/nutrition_api.py`:
```python
from database.crud import update_nutrition_item_weight


class PatchItemPayload(BaseModel):
    meal_id: int
    idx: int = Field(..., ge=0)
    weight: float = Field(..., gt=0, le=5000)


@router.patch("/api/meal/item")
async def patch_meal_item(payload: PatchItemPayload, tg_user: dict = Depends(get_tg_user)):
    user_id = tg_user.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="No user id in initData")
    db = SessionLocal()
    try:
        try:
            item, totals = update_nutrition_item_weight(
                db=db, meal_id=payload.meal_id, user_id=user_id,
                idx=payload.idx, new_weight=payload.weight,
            )
        except LookupError:
            raise HTTPException(status_code=404, detail="meal not found")
        except IndexError:
            raise HTTPException(status_code=400, detail="item index out of range")
    finally:
        db.close()
    return {"item": _item_to_wire(payload.idx, item), "totals": _totals_to_wire(totals)}
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/test_nutrition_api.py -v`

- [ ] **Step 5: Commit**

```bash
git add telegram-bot/webhook/nutrition_api.py tests/test_nutrition_api.py
git commit -m "feat(api): PATCH /api/meal/item — proportional weight edit"
```

---

## Task 7: `PATCH /api/meal`, `DELETE /api/meal/item`, `DELETE /api/meal`

Bundle these three simple mutations.

**Files:**
- Modify: `telegram-bot/webhook/nutrition_api.py`
- Modify: `tests/test_nutrition_api.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_nutrition_api.py`:
```python
def test_patch_meal_fields(client, test_db):
    from datetime import date, time
    row = create_nutrition_log(
        db=test_db, user_id=895655, date=date(2026, 4, 17),
        meal_time=time(13, 0), meal_name="Обед",
        items=[{"product": "X", "weight_g": 100, "calories": 100,
                "protein": 1, "fats": 1, "carbs": 1, "fiber": 0}],
        totals={"calories": 100, "protein": 1, "fats": 1, "carbs": 1, "fiber": 0},
    )
    r = client.patch("/api/meal", json={
        "meal_id": row.id, "meal_name": "Поздний обед", "meal_time": "15:30"
    })
    assert r.status_code == 200
    day = client.get("/api/day?date=2026-04-17").json()
    assert day["meals"][0]["meal_name"] == "Поздний обед"
    assert day["meals"][0]["meal_time"] == "15:30"
    assert day["meals"][0]["slot"] == "snack"


def test_delete_meal_item(client, test_db):
    from datetime import date, time
    row = create_nutrition_log(
        db=test_db, user_id=895655, date=date(2026, 4, 17),
        meal_time=time(13, 0), meal_name="Обед",
        items=[
            {"product": "A", "weight_g": 100, "calories": 100, "protein": 1, "fats": 1, "carbs": 1, "fiber": 0},
            {"product": "B", "weight_g": 100, "calories": 50, "protein": 0, "fats": 0, "carbs": 10, "fiber": 0},
        ],
        totals={"calories": 150, "protein": 1, "fats": 1, "carbs": 11, "fiber": 0},
    )
    r = client.delete(f"/api/meal/item?meal_id={row.id}&idx=0")
    assert r.status_code == 200
    assert r.json()["removed"]["name"] == "A"
    day = client.get("/api/day?date=2026-04-17").json()
    assert len(day["meals"][0]["items"]) == 1


def test_delete_last_item_removes_meal(client, test_db):
    from datetime import date, time
    row = create_nutrition_log(
        db=test_db, user_id=895655, date=date(2026, 4, 17),
        meal_time=time(13, 0), meal_name="Обед",
        items=[{"product": "A", "weight_g": 100, "calories": 100, "protein": 1, "fats": 1, "carbs": 1, "fiber": 0}],
        totals={"calories": 100, "protein": 1, "fats": 1, "carbs": 1, "fiber": 0},
    )
    r = client.delete(f"/api/meal/item?meal_id={row.id}&idx=0")
    assert r.status_code == 200
    day = client.get("/api/day?date=2026-04-17").json()
    assert day["meals"] == []


def test_delete_meal_whole(client, test_db):
    from datetime import date, time
    row = create_nutrition_log(
        db=test_db, user_id=895655, date=date(2026, 4, 17),
        meal_time=time(13, 0), meal_name="Обед",
        items=[{"product": "A", "weight_g": 100, "calories": 100, "protein": 1, "fats": 1, "carbs": 1, "fiber": 0}],
        totals={"calories": 100, "protein": 1, "fats": 1, "carbs": 1, "fiber": 0},
    )
    r = client.delete(f"/api/meal?meal_id={row.id}")
    assert r.status_code == 204
    day = client.get("/api/day?date=2026-04-17").json()
    assert day["meals"] == []
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/test_nutrition_api.py -v`

- [ ] **Step 3: Implement endpoints**

Append to `telegram-bot/webhook/nutrition_api.py`:
```python
from fastapi import Response
from database.crud import (
    update_nutrition_meal_fields,
    delete_nutrition_item,
    delete_nutrition_log,
)


class PatchMealPayload(BaseModel):
    meal_id: int
    meal_name: Optional[str] = None
    meal_time: Optional[str] = None  # "HH:MM"


@router.patch("/api/meal")
async def patch_meal(payload: PatchMealPayload, tg_user: dict = Depends(get_tg_user)):
    user_id = tg_user.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="No user id in initData")
    mt: Optional[time_type] = None
    if payload.meal_time:
        try:
            h, m = payload.meal_time.split(":")
            mt = time_type(int(h), int(m))
        except Exception:
            raise HTTPException(status_code=400, detail="meal_time must be HH:MM")
    db = SessionLocal()
    try:
        try:
            row = update_nutrition_meal_fields(
                db=db, meal_id=payload.meal_id, user_id=user_id,
                meal_name=payload.meal_name, meal_time=mt,
            )
        except LookupError:
            raise HTTPException(status_code=404, detail="meal not found")
        result = {
            "meal_id": row.id,
            "meal_name": row.meal_name,
            "meal_time": row.meal_time.strftime("%H:%M") if row.meal_time else None,
        }
    finally:
        db.close()
    return result


@router.delete("/api/meal/item")
async def delete_item(
    meal_id: int = Query(...),
    idx: int = Query(..., ge=0),
    tg_user: dict = Depends(get_tg_user),
):
    user_id = tg_user.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="No user id in initData")
    db = SessionLocal()
    try:
        try:
            removed, new_totals = delete_nutrition_item(
                db=db, meal_id=meal_id, user_id=user_id, idx=idx,
            )
        except LookupError:
            raise HTTPException(status_code=404, detail="meal not found")
        except IndexError:
            raise HTTPException(status_code=400, detail="item index out of range")
    finally:
        db.close()
    return {
        "removed": _item_to_wire(idx, removed),
        "totals": _totals_to_wire(new_totals) if new_totals else None,
    }


@router.delete("/api/meal", status_code=204)
async def delete_meal(
    meal_id: int = Query(...),
    tg_user: dict = Depends(get_tg_user),
):
    user_id = tg_user.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="No user id in initData")
    db = SessionLocal()
    try:
        ok = delete_nutrition_log(db=db, log_id=meal_id, user_id=user_id)
        if not ok:
            raise HTTPException(status_code=404, detail="meal not found")
    finally:
        db.close()
    return Response(status_code=204)
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/test_nutrition_api.py -v`

- [ ] **Step 5: Commit**

```bash
git add telegram-bot/webhook/nutrition_api.py tests/test_nutrition_api.py
git commit -m "feat(api): PATCH meal fields + DELETE item/meal endpoints"
```

---

## Task 8: `GET /api/favorites`

**Files:**
- Modify: `telegram-bot/webhook/nutrition_api.py`
- Modify: `tests/test_nutrition_api.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_nutrition_api.py`:
```python
def test_get_favorites(client, test_db):
    from datetime import date, time, timedelta
    today = date.today()
    create_nutrition_log(
        db=test_db, user_id=895655, date=today - timedelta(days=1),
        meal_time=time(9, 0), meal_name="Завтрак",
        items=[
            {"product": "Кофе", "weight_g": 200, "calories": 10, "protein": 0,
             "fats": 0, "carbs": 2, "fiber": 0},
            {"product": "Овсянка", "weight_g": 60, "calories": 240, "protein": 8,
             "fats": 5, "carbs": 42, "fiber": 6},
        ],
        totals={"calories": 250, "protein": 8, "fats": 5, "carbs": 44, "fiber": 6},
    )
    r = client.get("/api/favorites?limit=15")
    assert r.status_code == 200
    body = r.json()
    names = [x["name"] for x in body]
    assert "Кофе" in names
    assert "Овсянка" in names
    # Shape
    for rec in body:
        assert set(rec.keys()) >= {"name", "default_weight", "last_used", "per_100"}
        assert set(rec["per_100"].keys()) == {"kcal", "p", "f", "c", "fib"}


def test_get_favorites_respects_limit(client, test_db):
    r = client.get("/api/favorites?limit=0")
    assert r.status_code == 422  # pydantic: limit must be >= 1
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/test_nutrition_api.py -v`

- [ ] **Step 3: Implement**

Append to `telegram-bot/webhook/nutrition_api.py`:
```python
from database.crud import get_recent_product_names


@router.get("/api/favorites")
async def get_favorites(
    limit: int = Query(15, ge=1, le=50),
    tg_user: dict = Depends(get_tg_user),
):
    user_id = tg_user.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="No user id in initData")
    db = SessionLocal()
    try:
        return get_recent_product_names(db, user_id=user_id, limit=limit, lookback_days=90)
    finally:
        db.close()
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/test_nutrition_api.py -v`

- [ ] **Step 5: Commit**

```bash
git add telegram-bot/webhook/nutrition_api.py tests/test_nutrition_api.py
git commit -m "feat(api): GET /api/favorites — recently used products"
```

---

## Task 9: Mount router on existing FastAPI app

**Files:**
- Modify: `telegram-bot/webhook/apple_health.py`

- [ ] **Step 1: Add include_router**

Edit `telegram-bot/webhook/apple_health.py`. Find the block right before the static webapp mount (search for `# ── Static webapp ──`). Add immediately above it:

```python
# ── Nutrition day editor API ─────────────────────────────────────────────────

from webhook.nutrition_api import router as nutrition_router
app.include_router(nutrition_router)
```

> If the local import path `webhook.nutrition_api` fails at runtime (depends on how the module is launched), use `from .nutrition_api import router as nutrition_router` (relative import) or prepend `sys.path` — whichever matches the convention used elsewhere in this file.

- [ ] **Step 2: Smoke-test the full app boots**

Run locally:
```bash
cd telegram-bot && python -c "from webhook.apple_health import app; print([r.path for r in app.routes if 'api' in r.path])"
```
Expected output contains: `/api/day`, `/api/meal/item`, `/api/meal`, `/api/favorites`, `/api/settings`.

- [ ] **Step 3: Commit**

```bash
git add telegram-bot/webhook/apple_health.py
git commit -m "feat(webhook): mount nutrition_api router on bot app"
```

---

## Task 10: Frontend — skeleton of day editor + existing settings moved behind ⚙️

**Files:**
- Modify: `telegram-bot/webapp/index.html`
- Create: `telegram-bot/webapp/day.css`
- Create: `telegram-bot/webapp/day.js`

No automated tests for this layer (vanilla JS in a mini-app — test manually). Use the visual-companion mockup at `.superpowers/brainstorm/12432-1776454628/content/layout-day.html` as the target pixel-reference.

- [ ] **Step 1: Read current index.html to understand its structure**

Look at `telegram-bot/webapp/index.html`. Note the `.section` class pattern, how it uses `section.active`, and where the existing tiles are. We will:
- Wrap existing content into a `<section id="settings-section">` (no longer active by default).
- Add new `<section id="day-section" class="active">` with day editor markup.
- Add header bar with title + ⚙️ button that toggles sections.

- [ ] **Step 2: Rewrite top of index.html**

Replace the current `<body>` content. Keep existing JS that handles settings working — it'll be reused when settings-section is visible.

In `<head>`, add:
```html
<link rel="stylesheet" href="day.css">
```

At the top of `<body>`:
```html
<div class="top-header">
  <span class="top-title" id="top-title">🍽 Дневник</span>
  <button class="header-btn" id="toggle-settings" aria-label="Настройки">⚙️</button>
</div>

<section id="day-section" class="section active">
  <div class="day-switcher">
    <button class="day-nav" id="prev-day" aria-label="Предыдущий день">‹</button>
    <div class="day-label-wrap">
      <div class="day-label" id="day-label">Сегодня</div>
      <div class="day-sub" id="day-sub"></div>
    </div>
    <button class="day-nav" id="next-day" aria-label="Следующий день">›</button>
  </div>
  <div class="calendar-row">
    <label class="calendar-btn">
      📅 Выбрать дату
      <input type="date" id="date-picker" hidden>
    </label>
  </div>

  <div id="slots-container"></div>

  <div id="snackbar" class="snackbar hidden">
    <span id="snackbar-text"></span>
    <button id="snackbar-undo">Отменить</button>
  </div>

  <div class="day-footer" id="day-footer">
    <div class="footer-title">Итого за день</div>
    <div id="bars"></div>
  </div>
</section>

<!-- Existing settings content goes below, wrapped: -->
<section id="settings-section" class="section">
  <!-- Leave the existing tiles + sub-sections as-is inside this wrapper -->
</section>
```

Add at the end of `<body>`, before the existing inline `<script>`:
```html
<script src="day.js"></script>
```

- [ ] **Step 3: Create `day.css`**

`telegram-bot/webapp/day.css`:
```css
/* ── Day editor styles ─────────────────────────────────────────────────── */
:root {
  --slot-bg: var(--tg-theme-secondary-bg-color, #f7f7fa);
  --border: var(--tg-theme-hint-color, #ececf0);
  --accent: var(--tg-theme-button-color, #2a7ae2);
  --muted: var(--tg-theme-hint-color, #8e8e93);
  --bar-kcal: #2a7ae2;
  --bar-p: #e0577c;
  --bar-f: #f5b02b;
  --bar-c: #4cb563;
  --bar-fib: #8e79d6;
  --danger: #ff3b30;
}

.top-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 16px; border-bottom: 1px solid var(--border);
  position: sticky; top: 0; background: var(--tg-theme-bg-color, #fff); z-index: 10;
}
.top-title { font-weight: 600; font-size: 15px; }
.header-btn {
  background: none; border: none; font-size: 20px; padding: 4px 8px; cursor: pointer;
  color: var(--accent);
}

.day-switcher {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 16px 4px;
}
.day-nav {
  background: none; border: none; font-size: 24px; color: var(--accent);
  padding: 4px 14px; cursor: pointer; min-width: 40px; min-height: 40px;
}
.day-nav:disabled { opacity: .3; cursor: not-allowed; }
.day-label { font-size: 17px; font-weight: 600; text-align: center; }
.day-sub { font-size: 12px; color: var(--muted); text-align: center; }
.calendar-row { text-align: center; padding: 2px 16px 10px; }
.calendar-btn { color: var(--accent); font-size: 13px; cursor: pointer; display: inline-block; padding: 4px 8px; }

#slots-container { padding: 0 16px 100px; }

.slot {
  background: var(--slot-bg); border-radius: 14px; padding: 12px 14px;
  margin-bottom: 10px;
}
.slot.dim .slot-title { color: var(--muted); font-weight: 500; }
.slot-header {
  display: flex; justify-content: space-between; align-items: center;
  min-height: 36px; cursor: pointer;
}
.slot-title { font-weight: 600; font-size: 15px; }
.slot-meta { font-size: 12px; color: var(--muted); }
.slot-empty { color: #c7c7cc; font-size: 13px; padding: 4px 0; }

.items { margin-top: 10px; border-top: 1px solid var(--border); padding-top: 6px; }
.item { position: relative; overflow: hidden; }
.item-row {
  display: grid; grid-template-columns: 1fr auto; gap: 4px 10px; padding: 10px 4px;
  border-bottom: 1px dashed var(--border); background: var(--slot-bg);
  transform: translateX(0); transition: transform .2s;
}
.item:last-child .item-row { border-bottom: none; }
.item-name { font-size: 14px; font-weight: 500; }
.item-weight { font-size: 13px; color: var(--muted); text-align: right; }
.item-macros { grid-column: 1 / 3; font-size: 11px; color: var(--muted); display: flex; gap: 10px; flex-wrap: wrap; }
.item-macros b { color: var(--tg-theme-text-color, #48484a); font-weight: 500; }
.item-warn { color: var(--danger); font-size: 11px; }

.item .delete-bg {
  position: absolute; inset: 0; background: var(--danger); color: white;
  display: flex; align-items: center; justify-content: flex-end;
  padding-right: 20px; font-size: 13px;
}
.item.swiped .item-row { transform: translateX(-80px); }

.swipe-hint { font-size: 10px; color: #c7c7cc; font-style: italic;
              text-align: right; padding: 4px 0 0; }

.add-in-slot { color: var(--accent); font-size: 13px; padding: 10px 0 2px;
               cursor: pointer; text-align: center; }

.day-footer {
  position: sticky; bottom: 0; background: var(--tg-theme-bg-color, #fff);
  border-top: 1px solid var(--border); padding: 10px 16px 14px;
}
.footer-title { font-size: 11px; color: var(--muted); text-transform: uppercase;
                letter-spacing: .5px; margin-bottom: 6px; }
.bar-row { display: grid; grid-template-columns: 70px 1fr 80px; align-items: center;
           gap: 8px; font-size: 12px; margin-bottom: 4px; }
.bar-track { background: var(--border); border-radius: 4px; height: 6px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 4px; transition: width .3s; }
.bar-fill.kcal { background: var(--bar-kcal); }
.bar-fill.p { background: var(--bar-p); }
.bar-fill.f { background: var(--bar-f); }
.bar-fill.c { background: var(--bar-c); }
.bar-fill.fib { background: var(--bar-fib); }
.bar-value { text-align: right; color: var(--tg-theme-text-color, #48484a); }
.bar-value span { color: var(--muted); font-size: 11px; }

/* Bottom sheet */
.sheet-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.4); z-index: 100;
                 display: none; align-items: flex-end; justify-content: center; }
.sheet-overlay.open { display: flex; }
.sheet {
  background: var(--tg-theme-bg-color, #fff); width: 100%; max-width: 480px;
  border-radius: 16px 16px 0 0; padding: 18px 16px 20px; max-height: 80vh;
  overflow-y: auto;
}
.sheet h3 { font-size: 16px; margin-bottom: 12px; }
.sheet-close { float: right; background: none; border: none; font-size: 18px; cursor: pointer; color: var(--muted); }

.fav-list { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 10px; margin-bottom: 14px; }
.fav-chip {
  flex: 0 0 auto; background: var(--slot-bg); border-radius: 10px; padding: 8px 12px;
  font-size: 13px; cursor: pointer; border: 1px solid var(--border);
}
.fav-chip .w { color: var(--muted); font-size: 11px; display: block; margin-top: 2px; }

.form-row { margin-bottom: 10px; }
.form-row label { display: block; font-size: 11px; color: var(--muted);
                  text-transform: uppercase; letter-spacing: .5px; margin-bottom: 4px; }
.form-row input { width: 100%; border: 1px solid var(--border); border-radius: 8px;
                  padding: 10px 12px; font-size: 14px; }
.primary-btn {
  background: var(--accent); color: white; border: none; border-radius: 10px;
  padding: 12px 16px; font-size: 15px; font-weight: 600; width: 100%; cursor: pointer;
}
.primary-btn:disabled { opacity: .5; cursor: wait; }

.snackbar {
  position: fixed; bottom: 70px; left: 16px; right: 16px; max-width: 480px; margin: 0 auto;
  background: #333; color: white; border-radius: 10px; padding: 12px 14px;
  display: flex; justify-content: space-between; align-items: center; z-index: 200;
}
.snackbar.hidden { display: none; }
.snackbar button {
  background: none; border: none; color: #6eb4ff; font-weight: 600; cursor: pointer;
}
```

- [ ] **Step 4: Create `day.js` skeleton (empty state + day-switcher)**

`telegram-bot/webapp/day.js`:
```javascript
(function () {
  const tg = window.Telegram?.WebApp;
  tg?.expand();
  tg?.ready();

  const state = {
    date: new Date(),  // local date
    data: null,        // last /api/day response
    lastDeleted: null, // for undo
  };

  const FMT = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', weekday: 'short' });
  const SLOT_LABEL = { breakfast: '🌅 Завтрак', lunch: '☀️ Обед', snack: '🍎 Перекус', dinner: '🌙 Ужин' };

  function toISO(d) {
    const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, '0'),
          dd = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${dd}`;
  }
  function sameDay(a, b) { return toISO(a) === toISO(b); }
  function daysDiff(a, b) {
    const ms = (new Date(toISO(b))) - (new Date(toISO(a)));
    return Math.round(ms / 86400000);
  }

  function dayLabelText(d) {
    const today = new Date();
    if (sameDay(d, today)) return 'Сегодня';
    const y = new Date(today); y.setDate(y.getDate() - 1);
    if (sameDay(d, y)) return 'Вчера';
    const t = new Date(today); t.setDate(t.getDate() + 1);
    if (sameDay(d, t)) return 'Завтра';
    return FMT.format(d);
  }

  async function api(path, options = {}) {
    const initData = tg?.initData || '';
    const headers = { 'Authorization': `tma ${initData}`, 'Content-Type': 'application/json', ...(options.headers || {}) };
    const r = await fetch(path, { ...options, headers });
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
    return r.status === 204 ? null : r.json();
  }

  async function loadDay() {
    try {
      state.data = await api(`/api/day?date=${toISO(state.date)}`);
      render();
    } catch (e) {
      console.error(e);
      document.getElementById('slots-container').innerHTML =
        `<div style="padding:20px;text-align:center;color:#999">Нет связи: ${e.message}</div>`;
    }
  }

  function setDate(d) {
    state.date = d;
    updateSwitcher();
    loadDay();
  }

  function updateSwitcher() {
    const d = state.date, today = new Date();
    document.getElementById('day-label').textContent = dayLabelText(d);
    document.getElementById('day-sub').textContent = FMT.format(d);
    // Disable next-day if more than +7 days ahead
    document.getElementById('next-day').disabled = daysDiff(today, d) >= 7;
    document.getElementById('date-picker').value = toISO(d);
  }

  // Wire up controls
  document.getElementById('prev-day').addEventListener('click', () => {
    const d = new Date(state.date); d.setDate(d.getDate() - 1); setDate(d);
  });
  document.getElementById('next-day').addEventListener('click', () => {
    if (document.getElementById('next-day').disabled) return;
    const d = new Date(state.date); d.setDate(d.getDate() + 1); setDate(d);
  });
  document.querySelector('.calendar-btn').addEventListener('click', (e) => {
    // Opens native date picker when clicking the hidden input
    document.getElementById('date-picker').showPicker?.();
  });
  document.getElementById('date-picker').addEventListener('change', (e) => {
    if (e.target.value) setDate(new Date(e.target.value + 'T00:00:00'));
  });

  // Settings toggle
  document.getElementById('toggle-settings').addEventListener('click', () => {
    const day = document.getElementById('day-section');
    const set = document.getElementById('settings-section');
    const isOnDay = day.classList.contains('active');
    day.classList.toggle('active', !isOnDay);
    set.classList.toggle('active', isOnDay);
    document.getElementById('top-title').textContent = isOnDay ? '⚙️ Настройки' : '🍽 Дневник';
    document.getElementById('toggle-settings').textContent = isOnDay ? '✕' : '⚙️';
  });

  // Render functions defined in Task 11 / 12.
  function render() { /* filled in Task 11 */ window.__dayRender?.(state); }

  // Expose for later tasks
  window.__nutri = { state, api, loadDay, render, setDate };

  // Init
  updateSwitcher();
  loadDay();
})();
```

- [ ] **Step 5: Smoke-check manually**

Run the bot locally (or restart container). Open Telegram mini-app. Verify:
- Opens on day editor section (not settings)
- Day-switcher buttons shift the label and trigger a `/api/day` request (check Network tab via `tg.version >= 6.1` or network inspector in TDesktop)
- Calendar button opens native date picker
- ⚙️ button swaps sections and shows existing settings tiles

- [ ] **Step 6: Commit**

```bash
git add telegram-bot/webapp/index.html telegram-bot/webapp/day.css telegram-bot/webapp/day.js
git commit -m "feat(webapp): day editor skeleton, settings behind gear button"
```

---

## Task 11: Frontend — render slots + items + footer

**Files:**
- Modify: `telegram-bot/webapp/day.js`

- [ ] **Step 1: Add render() body**

Replace the `function render() { /* filled in Task 11 */ }` line in `day.js` with:

```javascript
function render() {
  if (!state.data) return;
  renderSlots();
  renderFooter();
}

function renderSlots() {
  const container = document.getElementById('slots-container');
  const SLOTS = ['breakfast', 'lunch', 'snack', 'dinner'];
  // Group meals by slot
  const bySlot = { breakfast: [], lunch: [], snack: [], dinner: [] };
  for (const m of state.data.meals) bySlot[m.slot]?.push(m);

  container.innerHTML = SLOTS.map(slot => {
    const meals = bySlot[slot];
    if (meals.length === 0) {
      return `
        <div class="slot dim" data-slot="${slot}">
          <div class="slot-header">
            <div class="slot-title">${SLOT_LABEL[slot]}</div>
            <button class="header-btn add-in-slot-btn" data-slot="${slot}">+</button>
          </div>
          <div class="slot-empty">Пока ничего</div>
        </div>`;
    }
    // If 2+ meals fall into the same slot, render each as its own card inside the slot.
    return meals.map((m, mi) => {
      const expandedKey = `exp:${m.id}`;
      const isExpanded = sessionStorage.getItem(expandedKey) === '1' || (meals.length === 1);
      const hdrExtra = isExpanded ? '⌄' : '›';
      const itemsHtml = isExpanded ? renderItems(m) : '';
      return `
        <div class="slot" data-slot="${slot}" data-meal-id="${m.id}">
          <div class="slot-header" data-toggle="${m.id}">
            <div class="slot-title">${SLOT_LABEL[slot]}
              <span class="slot-meta">· ${m.meal_time || ''}</span>
            </div>
            <div class="slot-meta">${Math.round(m.totals.kcal)} ккал ${hdrExtra}</div>
          </div>
          ${itemsHtml}
        </div>`;
    }).join('');
  }).join('');

  container.querySelectorAll('.slot-header[data-toggle]').forEach(el => {
    el.addEventListener('click', () => {
      const id = el.dataset.toggle;
      const key = `exp:${id}`;
      sessionStorage.setItem(key, sessionStorage.getItem(key) === '1' ? '0' : '1');
      renderSlots();
    });
  });
  container.querySelectorAll('.add-in-slot-btn, .add-in-slot').forEach(el => {
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      openAddSheet(el.dataset.slot);
    });
  });
  // Swipe + tap: wired in Task 13.
  window.__wireItemGestures?.(container);
}

function renderItems(meal) {
  const hintShown = localStorage.getItem('swipeHintShown') === '1';
  const itemsHtml = meal.items.map(it => {
    const noMacros = it.kcal === 0 && it.p === 0 && it.f === 0 && it.c === 0;
    const warn = noMacros ? '<span class="item-warn">❗</span> ' : '';
    return `
      <div class="item" data-meal-id="${meal.id}" data-idx="${it.idx}">
        <div class="delete-bg">Удалить</div>
        <div class="item-row">
          <div class="item-name">${warn}${escapeHtml(it.name)}</div>
          <div class="item-weight">${Math.round(it.weight)} г</div>
          <div class="item-macros">
            <span>Б <b>${it.p}</b></span>
            <span>Ж <b>${it.f}</b></span>
            <span>У <b>${it.c}</b></span>
            <span>Кл <b>${it.fib}</b></span>
            <span>${Math.round(it.kcal)} ккал</span>
          </div>
        </div>
      </div>`;
  }).join('');
  const hint = hintShown ? '' : '<div class="swipe-hint">← свайп для удаления · тап для редактирования веса</div>';
  return `
    <div class="items">
      ${itemsHtml}
      ${hint}
      <div class="add-in-slot" data-slot="${meal.slot}">+ добавить в ${SLOT_LABEL[meal.slot].replace(/^\S+\s/, '').toLowerCase()}</div>
    </div>`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

function renderFooter() {
  const { totals_day: t, goals: g } = state.data;
  const bars = [
    { key: 'kcal',   label: 'Ккал',      cls: 'kcal', val: t.kcal,  goal: g.kcal,    unit: '' },
    { key: 'p',      label: 'Белки',     cls: 'p',    val: t.p,     goal: g.protein, unit: 'г' },
    { key: 'f',      label: 'Жиры',      cls: 'f',    val: t.f,     goal: g.fats,    unit: 'г' },
    { key: 'c',      label: 'Углеводы',  cls: 'c',    val: t.c,     goal: g.carbs,   unit: 'г' },
    { key: 'fib',    label: 'Клетчатка', cls: 'fib',  val: t.fib,   goal: g.fiber,   unit: 'г' },
  ];
  document.getElementById('bars').innerHTML = bars.map(b => {
    if (b.goal == null) {
      return `<div class="bar-row">
                <span>${b.label}</span>
                <div></div>
                <span class="bar-value">${Math.round(b.val)}${b.unit ? ' ' + b.unit : ''}</span>
              </div>`;
    }
    const pct = Math.min(100, Math.round((b.val / b.goal) * 100));
    return `<div class="bar-row">
              <span>${b.label}</span>
              <div class="bar-track"><div class="bar-fill ${b.cls}" style="width:${pct}%"></div></div>
              <span class="bar-value">${Math.round(b.val)} <span>/ ${b.goal}${b.unit ? ' ' + b.unit : ''}</span></span>
            </div>`;
  }).join('');
}
```

- [ ] **Step 2: Manual verification**

Open mini-app. On a day with existing nutrition_log entries:
- 4 slot cards render with Russian labels and emoji
- Empty slots show «Пока ничего»
- Filled slot collapsed by default shows `520 ккал ›`; clicking header expands it to show items and `⌄`
- Items show name, weight, and macros
- Footer shows 5 bars; if goal is null the bar is absent, only the number is shown

- [ ] **Step 3: Commit**

```bash
git add telegram-bot/webapp/day.js
git commit -m "feat(webapp): render slots, items, and daily totals footer"
```

---

## Task 12: Frontend — add product bottom sheet (favorites + manual)

**Files:**
- Modify: `telegram-bot/webapp/day.js`
- Modify: `telegram-bot/webapp/index.html` (add sheet container)

- [ ] **Step 1: Add sheet markup**

In `telegram-bot/webapp/index.html`, add right before the closing `</body>`:
```html
<div id="add-sheet" class="sheet-overlay">
  <div class="sheet">
    <button class="sheet-close" id="add-sheet-close" aria-label="Закрыть">✕</button>
    <h3 id="add-sheet-title">Добавить</h3>

    <label class="form-row">
      <span>Часто используемое</span>
    </label>
    <div id="fav-list" class="fav-list"><div style="color:#999;font-size:12px">Загружаем…</div></div>

    <div class="form-row">
      <label>Или ввести вручную</label>
      <input type="text" id="add-name" placeholder="Например: курица грудка">
    </div>
    <div class="form-row">
      <label>Вес, г</label>
      <input type="number" id="add-weight" inputmode="numeric" min="1" max="5000" placeholder="180">
    </div>

    <button class="primary-btn" id="add-submit">Добавить</button>
  </div>
</div>
```

- [ ] **Step 2: Add JS for add sheet**

Append to `telegram-bot/webapp/day.js` (inside the IIFE):
```javascript
let activeSlot = null;

async function openAddSheet(slot) {
  activeSlot = slot;
  document.getElementById('add-sheet-title').textContent =
    `Добавить в ${SLOT_LABEL[slot].replace(/^\S+\s/, '')}`;
  document.getElementById('add-sheet').classList.add('open');
  document.getElementById('add-name').value = '';
  document.getElementById('add-weight').value = '';
  document.getElementById('fav-list').innerHTML = '<div style="color:#999;font-size:12px">Загружаем…</div>';
  try {
    const favs = await api('/api/favorites?limit=15');
    document.getElementById('fav-list').innerHTML = favs.length
      ? favs.map(f => `
          <button class="fav-chip" data-name="${escapeHtml(f.name)}" data-weight="${f.default_weight}">
            ${escapeHtml(f.name)}
            <span class="w">${Math.round(f.default_weight)} г</span>
          </button>`).join('')
      : '<div style="color:#999;font-size:12px">Пока пусто</div>';
    document.querySelectorAll('.fav-chip').forEach(c => {
      c.addEventListener('click', () => {
        document.getElementById('add-name').value = c.dataset.name;
        document.getElementById('add-weight').value = c.dataset.weight;
      });
    });
  } catch (e) { console.error(e); }
}

function closeAddSheet() {
  document.getElementById('add-sheet').classList.remove('open');
  activeSlot = null;
}

document.getElementById('add-sheet-close').addEventListener('click', closeAddSheet);
document.getElementById('add-sheet').addEventListener('click', (e) => {
  if (e.target.id === 'add-sheet') closeAddSheet();
});

document.getElementById('add-submit').addEventListener('click', async () => {
  const name = document.getElementById('add-name').value.trim();
  const weight = parseFloat(document.getElementById('add-weight').value);
  if (!name || !weight || weight <= 0) {
    tg?.showAlert?.('Заполни название и вес') ?? alert('Заполни название и вес');
    return;
  }
  const btn = document.getElementById('add-submit');
  btn.disabled = true; btn.textContent = 'Добавляем…';
  try {
    await api('/api/meal/item', {
      method: 'POST',
      body: JSON.stringify({
        date: toISO(state.date), slot: activeSlot,
        name, weight, source: 'manual',
      }),
    });
    closeAddSheet();
    await loadDay();
    tg?.HapticFeedback?.notificationOccurred?.('success');
  } catch (e) {
    tg?.showAlert?.(`Ошибка: ${e.message}`) ?? alert(e.message);
  } finally {
    btn.disabled = false; btn.textContent = 'Добавить';
  }
});

window.__openAddSheet = openAddSheet;  // for Task 11 renderer
```

And change `openAddSheet(el.dataset.slot)` in `renderSlots()` (Task 11) to call this function — already wired since it's in the same IIFE scope.

- [ ] **Step 3: Manual verification**

- Tap `+ добавить в обед` → sheet slides up, shows favorites loaded, chips populate.
- Tap a chip → name and weight fill.
- Type new product, hit Добавить → sheet closes, day refreshes, new item visible.
- Add a product for a slot with no existing meal → new meal card appears.

- [ ] **Step 4: Commit**

```bash
git add telegram-bot/webapp/day.js telegram-bot/webapp/index.html
git commit -m "feat(webapp): add-product bottom sheet with favorites + manual entry"
```

---

## Task 13: Frontend — swipe-to-delete with undo + tap-to-edit-weight

**Files:**
- Modify: `telegram-bot/webapp/day.js`
- Modify: `telegram-bot/webapp/index.html` (edit sheet markup)

- [ ] **Step 1: Add edit sheet markup**

In `index.html`, before `</body>` (next to the add-sheet):
```html
<div id="edit-sheet" class="sheet-overlay">
  <div class="sheet">
    <button class="sheet-close" id="edit-sheet-close" aria-label="Закрыть">✕</button>
    <h3 id="edit-sheet-title">Изменить вес</h3>
    <div class="form-row">
      <label>Вес, г</label>
      <input type="number" id="edit-weight" inputmode="numeric" min="1" max="5000">
    </div>
    <div class="form-row" style="font-size:12px;color:#888;">
      КБЖУ пересчитаются пропорционально.
    </div>
    <button class="primary-btn" id="edit-submit">Сохранить</button>
  </div>
</div>
```

- [ ] **Step 2: Add swipe + edit JS**

Append to `day.js`:
```javascript
function showSnackbar(text, onUndo) {
  const bar = document.getElementById('snackbar');
  document.getElementById('snackbar-text').textContent = text;
  bar.classList.remove('hidden');
  const undoBtn = document.getElementById('snackbar-undo');
  const handler = async () => { undoBtn.removeEventListener('click', handler); bar.classList.add('hidden'); await onUndo(); };
  undoBtn.addEventListener('click', handler);
  setTimeout(() => { bar.classList.add('hidden'); undoBtn.removeEventListener('click', handler); }, 4000);
}

function wireItemGestures(root) {
  root.querySelectorAll('.item').forEach(el => {
    let startX = 0, currentX = 0, dragging = false;
    const row = el.querySelector('.item-row');
    el.addEventListener('touchstart', (e) => {
      startX = e.touches[0].clientX; dragging = true;
    }, { passive: true });
    el.addEventListener('touchmove', (e) => {
      if (!dragging) return;
      currentX = e.touches[0].clientX - startX;
      if (currentX < 0) row.style.transform = `translateX(${Math.max(currentX, -100)}px)`;
    }, { passive: true });
    el.addEventListener('touchend', async () => {
      dragging = false;
      if (currentX < -60) {
        // Mark hint as seen
        localStorage.setItem('swipeHintShown', '1');
        await deleteItem(el);
      } else {
        row.style.transform = '';
      }
      currentX = 0;
    });
    // Tap to edit weight
    row.addEventListener('click', (e) => {
      if (Math.abs(currentX) > 5) return;  // ignore if this was a swipe
      openEditSheet(el);
    });
  });
}
window.__wireItemGestures = wireItemGestures;

async function deleteItem(el) {
  const mealId = Number(el.dataset.mealId);
  const idx = Number(el.dataset.idx);
  try {
    const res = await api(`/api/meal/item?meal_id=${mealId}&idx=${idx}`, { method: 'DELETE' });
    const removed = res.removed;
    tg?.HapticFeedback?.impactOccurred?.('medium');
    showSnackbar(`Удалено: ${removed.name}`, async () => {
      // Undo: POST same product back to same slot
      const slot = el.closest('.slot')?.dataset.slot;
      await api('/api/meal/item', {
        method: 'POST',
        body: JSON.stringify({
          date: toISO(state.date), slot, name: removed.name,
          weight: removed.weight, source: 'manual',
        }),
      });
      loadDay();
    });
    loadDay();
  } catch (e) {
    tg?.showAlert?.(`Ошибка: ${e.message}`);
  }
}

function openEditSheet(el) {
  const mealId = Number(el.dataset.mealId);
  const idx = Number(el.dataset.idx);
  const meal = state.data.meals.find(m => m.id === mealId);
  const item = meal?.items[idx];
  if (!item) return;
  document.getElementById('edit-sheet-title').textContent = `Изменить: ${item.name}`;
  document.getElementById('edit-weight').value = item.weight;
  document.getElementById('edit-sheet').classList.add('open');
  document.getElementById('edit-submit').onclick = async () => {
    const w = parseFloat(document.getElementById('edit-weight').value);
    if (!w || w <= 0) return;
    try {
      await api('/api/meal/item', {
        method: 'PATCH',
        body: JSON.stringify({ meal_id: mealId, idx, weight: w }),
      });
      document.getElementById('edit-sheet').classList.remove('open');
      tg?.HapticFeedback?.notificationOccurred?.('success');
      loadDay();
    } catch (e) {
      tg?.showAlert?.(`Ошибка: ${e.message}`);
    }
  };
}

document.getElementById('edit-sheet-close').addEventListener('click', () =>
  document.getElementById('edit-sheet').classList.remove('open')
);
document.getElementById('edit-sheet').addEventListener('click', (e) => {
  if (e.target.id === 'edit-sheet') e.target.classList.remove('open');
});
```

- [ ] **Step 3: Manual verification**

- Swipe left on item row → it shifts, reveals red "Удалить" → releases beyond 60px → item disappears, snackbar shows up
- Tap "Отменить" within 4s → item re-appears
- Wait 4s → snackbar hides
- Tap an item (no swipe) → edit sheet opens, change weight, hit Save → totals update, both item and footer rebalanced

- [ ] **Step 4: Commit**

```bash
git add telegram-bot/webapp/day.js telegram-bot/webapp/index.html
git commit -m "feat(webapp): swipe-to-delete with undo + tap-to-edit weight"
```

---

## Task 14: Smoke test — end to end on real bot

No automated test here. Deploy-and-test checklist.

- [ ] **Step 1: Restart bot locally (or deploy)**

```bash
docker-compose -f docker-compose.dev.yml restart bot
# or if running directly:
cd telegram-bot && python bot.py
```

- [ ] **Step 2: Open mini-app from Telegram**

- Click mini-app button in the bot (which already opens `index.html`)
- Verify: day editor opens on "Сегодня"
- Verify: day has real data from today (if any) OR shows empty slots

- [ ] **Step 3: Run through the full flow**

1. Go to a day with existing meals — see slots, expand one.
2. Add a new product manually (type "яблоко", 150) — confirm it lands in the right slot.
3. Edit the weight of an existing item (from 100 to 200) — confirm KBJU doubled.
4. Delete a product — confirm snackbar, click Undo — confirm restoration.
5. Delete a product — wait 4s — confirm permanent.
6. Navigate to yesterday, to tomorrow, use the calendar picker.
7. Check footer bars update live and reflect actual goals.
8. Open settings via ⚙️ → existing tiles work → back to day editor via gear toggle.

- [ ] **Step 4: Check server logs**

Run: `docker-compose logs bot --tail=100`
Expected: no tracebacks; requests logged.

- [ ] **Step 5: Commit (if any tweaks were needed)**

```bash
git add -u
git commit -m "chore(nutrition): smoke-test tweaks from real-device verification"
```

---

## Task 15: Update AI_CHANGELOG

**Files:**
- Modify: `docs/ai_context/AI_CHANGELOG.md`

- [ ] **Step 1: Append changelog entry**

Add to the top of `docs/ai_context/AI_CHANGELOG.md` (keep existing date-grouped format; use today's date):
```markdown
## 2026-04-17 — Nutrition day editor mini-app

**Что:** Второй экран Telegram Mini App — редактор дневника питания. Позволяет
просматривать и редактировать все приёмы пищи по любому дню (навигация через
‹ / › / календарь), группированные в 4 слота (Завтрак / Обед / Перекус / Ужин),
добавлять продукты руками (через существующий LLM-пайплайн) или из последних
использованных, менять вес (КБЖУ пересчитывается), удалять со снэкбаром
"Отменить". Sticky-футер с прогресс-барами Ккал/Б/Ж/У/клетчатка до дневных целей.

**Зачем:** до этого нельзя было исправить ошибочно распознанный вес продукта
и посмотреть историю за любой день — только ввод через бота.

**Где:**
- Спек: [docs/superpowers/specs/2026-04-17-nutrition-day-editor-design.md](../superpowers/specs/2026-04-17-nutrition-day-editor-design.md)
- План: [docs/superpowers/plans/2026-04-17-nutrition-day-editor.md](../superpowers/plans/2026-04-17-nutrition-day-editor.md)
- Фронт: `telegram-bot/webapp/{index.html, day.js, day.css}`
- Бэк: `telegram-bot/webhook/nutrition_api.py`, `nutrition_slots.py`, `nutrition_goals.py`
- CRUD: новые хелперы в `database/crud.py`

**Паттерны UX:** cкопированы из MyFitnessPal / Yazio / Cronometer (day-switcher
сверху, 4 слота, "+ add food" в каждом слоте, свайп-to-delete, прогресс-бары
в футере). Фото/голос остаются в боте, мини-апп — только ручной ввод.
```

- [ ] **Step 2: Commit**

```bash
git add docs/ai_context/AI_CHANGELOG.md
git commit -m "docs: log nutrition day editor in AI_CHANGELOG"
```

---

## Self-review notes

Spec coverage:
- §1 Архитектура — Task 4, 9
- §2 Layout — Task 10, 11
- §3 Add bottom sheet — Task 12
- §4 API (7 endpoints) — Tasks 4, 5, 6, 7, 8
- §5 Data flow slot mapping — Task 1, 5
- §6 Edge cases:
  - Будущие даты +7 — Task 10 (`daysDiff` check)
  - Пустой день — Task 11 (dim slots)
  - Swipe hint один раз — Task 11, 13 (localStorage flag)
  - LLM timeout — Task 5 (graceful zero-macros fallback)
  - Часовой пояс MSK — Task 4 (`date.today()` server-side)
  - Цель не задана — Task 2 (returns None), Task 11 (bar omitted)
  - Отмена удаления — Task 13 (snackbar + POST)
- User scope (initData) — Task 4 (reuses `get_tg_user` from apple_health.py) + explicit 404/not-found scoping in Tasks 3, 6, 7.
- Goals computation — Task 2 (substitutes spec's "из настроек" with macro-split from caloric_budget, documented explicitly).

Types consistency: all API responses use `kcal/p/f/c/fib`; DB uses `calories/protein/fats/carbs/fiber`; serialization-layer funcs `_item_to_wire`, `_totals_to_wire` own the rename. Slot tokens `"breakfast"…"dinner"` are stable across Python and JS (verified by constant `SLOTS` in both sides).

No placeholders — all tests include full code; all implementation steps have code blocks. The only narrative steps (manual verification in Task 10/13/14) correctly describe UI checks that cannot be automated.
