# Telegram Mini App — Settings Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Telegram Mini App settings panel that lets each user manage their supplement list, calorie display, and notifications — without code changes.

**Architecture:** New `user_settings` table in PostgreSQL → CRUD functions → FastAPI `/api/settings` endpoint in existing `apple_health.py` → static `webapp/index.html` SPA with Telegram WebApp auth. SupplementService refactored to read from DB instead of hardcoded list.

**Tech Stack:** Python/SQLAlchemy (DB), FastAPI + uvicorn (existing), Vanilla JS + Telegram WebApp JS SDK (frontend), HMAC-SHA256 (auth)

**⚠️ Supplement reminders (APScheduler):** UI toggle is built and saves to DB, but actual message scheduling is v2 — marked "скоро" in UI. Added to todo.md.

---

## File Map

| File | Action | What changes |
|---|---|---|
| `database/models.py` | Modify | Add `UserSettings` model |
| `database/crud.py` | Modify | Add `get_user_settings`, `upsert_user_settings` |
| `core/health/supplements.py` | Modify | Read schedule from `user_settings` instead of hardcode |
| `core/health/caloric_budget.py` | Modify | Add `show_bar: bool` param to `format_budget_line()` |
| `telegram-bot/handlers/photo.py` | Modify | Pass `show_bar` from user settings to `format_budget_line()` |
| `telegram-bot/handlers/commands.py` | Modify | Skip bar blocks when `show_calorie_budget_bar=False` |
| `telegram-bot/webhook/apple_health.py` | Modify | Add HMAC auth + `GET/POST /api/settings` + `StaticFiles` |
| `telegram-bot/webapp/index.html` | Create | Full SPA — 4 sections + Telegram WebApp JS |
| `tests/test_user_settings.py` | Create | Unit tests for CRUD and HMAC auth |

---

## Task 1: UserSettings DB Model

**Files:**
- Modify: `database/models.py`

- [ ] **Step 1: Add `UserSettings` model to `database/models.py`**

Add after the `BodyMeasurement` class:

```python
class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.telegram_id'), primary_key=True)
    show_calorie_budget_bar: Mapped[bool] = mapped_column(Boolean, default=True, server_default='true')
    bmr_override: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    target_weight_kg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    target_weight_date: Mapped[Optional["datetime.date"]] = mapped_column(Date, nullable=True)
    supplement_reminders_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default='false')
    supplement_reminder_time: Mapped["datetime.time"] = mapped_column(Time, default=datetime.strptime("08:00", "%H:%M").time(), server_default='08:00:00')
    supplements: Mapped[list] = mapped_column(JSON, default=list, server_default='[]')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="settings")
```

Also add to the `User` model's relationships section:
```python
settings: Mapped[Optional["UserSettings"]] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")
```

- [ ] **Step 2: Create migration SQL on server**

Run on server via SSH:
```bash
ssh root@116.203.213.137 "cd /opt/healthvault && docker compose exec -T postgres psql -U healthvault -d healthvault -c \"
CREATE TABLE IF NOT EXISTS user_settings (
    user_id BIGINT PRIMARY KEY REFERENCES users(telegram_id) ON DELETE CASCADE,
    show_calorie_budget_bar BOOLEAN NOT NULL DEFAULT TRUE,
    bmr_override INTEGER,
    target_weight_kg FLOAT,
    target_weight_date DATE,
    supplement_reminders_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    supplement_reminder_time TIME NOT NULL DEFAULT '08:00:00',
    supplements JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);\""
```

Expected output: `CREATE TABLE`

- [ ] **Step 3: Verify table exists**

```bash
ssh root@116.203.213.137 "cd /opt/healthvault && docker compose exec -T postgres psql -U healthvault -d healthvault -c '\d user_settings'"
```

Expected: table columns listed.

- [ ] **Step 4: Commit**

```bash
git add database/models.py
git commit -m "feat: add UserSettings SQLAlchemy model"
```

---

## Task 2: CRUD Functions

**Files:**
- Modify: `database/crud.py`
- Create: `tests/test_user_settings.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_user_settings.py`:

```python
"""Tests for user_settings CRUD operations."""
import pytest
from unittest.mock import MagicMock, patch
from database.crud import get_user_settings, upsert_user_settings
from database.models import UserSettings


def make_db():
    """Return a mock SQLAlchemy session."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    return db


def test_get_user_settings_returns_none_when_missing():
    db = make_db()
    result = get_user_settings(db, user_id=895655)
    assert result is None


def test_upsert_creates_new_settings():
    db = make_db()
    result = upsert_user_settings(db, user_id=895655, show_calorie_budget_bar=False)
    db.add.assert_called_once()
    db.commit.assert_called_once()


def test_upsert_updates_existing_settings():
    existing = UserSettings(user_id=895655, show_calorie_budget_bar=True)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = existing

    result = upsert_user_settings(db, user_id=895655, show_calorie_budget_bar=False)
    assert existing.show_calorie_budget_bar == False
    db.commit.assert_called_once()


def test_get_show_bar_default_is_true():
    existing = UserSettings(user_id=895655)
    assert existing.show_calorie_budget_bar == True


def test_get_reminders_default_is_false():
    existing = UserSettings(user_id=895655)
    assert existing.supplement_reminders_enabled == False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/alexlyskovsky/HealthVault && python -m pytest tests/test_user_settings.py -v 2>&1 | tail -20
```

Expected: ImportError or AttributeError (functions don't exist yet).

- [ ] **Step 3: Add CRUD functions to `database/crud.py`**

Add after the existing user operations section:

```python
# ==================== USER SETTINGS ====================

def get_user_settings(db: Session, user_id: int) -> Optional["UserSettings"]:
    """Get settings for a user. Returns None if no settings saved yet."""
    from database.models import UserSettings
    return db.query(UserSettings).filter(UserSettings.user_id == user_id).first()


def upsert_user_settings(db: Session, user_id: int, **kwargs) -> "UserSettings":
    """Create or update user settings. Pass fields as kwargs.

    Example:
        upsert_user_settings(db, user_id=895655, show_calorie_budget_bar=False)
    """
    from database.models import UserSettings
    from datetime import datetime

    settings = get_user_settings(db, user_id)
    if settings is None:
        settings = UserSettings(user_id=user_id, **kwargs)
        db.add(settings)
    else:
        for key, value in kwargs.items():
            setattr(settings, key, value)
        settings.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(settings)
    return settings
```

- [ ] **Step 4: Run tests — expect pass**

```bash
cd /Users/alexlyskovsky/HealthVault && python -m pytest tests/test_user_settings.py -v 2>&1 | tail -15
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add database/crud.py tests/test_user_settings.py
git commit -m "feat: add get_user_settings and upsert_user_settings CRUD"
```

---

## Task 3: SupplementService — Read from DB

**Files:**
- Modify: `core/health/supplements.py`

The current `SupplementService.__init__` has a hardcoded `self.schedule` dict. Replace it with a DB read.

- [ ] **Step 1: Add `DEFAULT_SUPPLEMENTS` constant and `_load_schedule()` method**

At the top of `core/health/supplements.py`, after imports, add:

```python
# Default supplement schedule — used for new users and migration
DEFAULT_SUPPLEMENTS = [
    {"name": "Псиллиум",     "slot": "morning_before"},
    {"name": "Витамин D3",   "slot": "morning_with"},
    {"name": "Омега 3",      "slot": "morning_with"},
    {"name": "Plant Sterols","slot": "morning_with"},
    {"name": "Метилфолат",   "slot": "morning_with"},
    {"name": "Plant Sterols","slot": "evening"},
    {"name": "Магний",       "slot": "evening"},
    {"name": "Креатин",      "slot": "evening"},
]
```

- [ ] **Step 2: Replace hardcoded schedule in `__init__` with DB load**

Find the block in `SupplementService.__init__` that sets `self.schedule = {...}` (around line 100–125). Replace it with:

```python
# Load schedule from user_settings (or migrate defaults)
self.schedule = self._load_schedule()
```

Add the `_load_schedule()` method to `SupplementService`:

```python
def _load_schedule(self) -> dict:
    """Load supplement schedule from user_settings.

    If no settings exist for this user, saves DEFAULT_SUPPLEMENTS and returns them.
    Returns dict: {"morning_before": [...], "morning_with": [...], "evening": [...]}
    """
    from database import SessionLocal
    from database.crud import get_user_settings, upsert_user_settings

    db = SessionLocal()
    try:
        settings = get_user_settings(db, self.user_id)
        if settings is None or not settings.supplements:
            # First time — migrate defaults into DB
            upsert_user_settings(db, self.user_id, supplements=DEFAULT_SUPPLEMENTS)
            raw = DEFAULT_SUPPLEMENTS
        else:
            raw = settings.supplements
    finally:
        db.close()

    # Convert [{name, slot}, ...] → {slot: [name, ...]}
    slots: dict = {"morning_before": [], "morning_with": [], "evening": []}
    for item in raw:
        slot = item.get("slot", "morning_with")
        name = item.get("name", "")
        if slot in slots and name:
            slots[slot].append(name)
    return slots
```

- [ ] **Step 3: Run existing supplement tests**

```bash
cd /Users/alexlyskovsky/HealthVault && python -m pytest tests/ -k "supplement" -v 2>&1 | tail -20
```

Expected: all supplement tests pass (they use mocks and shouldn't be affected).

- [ ] **Step 4: Smoke test locally**

```bash
cd /Users/alexlyskovsky/HealthVault && python -c "
import os; os.environ['DATABASE_URL'] = 'postgresql://healthvault:dev_password_123@localhost:5432/healthvault'
from core.health.supplements import SupplementService
s = SupplementService(user_id=895655)
print(s.schedule)
"
```

Expected: schedule dict with 3 slots and supplement names.

- [ ] **Step 5: Commit**

```bash
git add core/health/supplements.py
git commit -m "feat: SupplementService reads schedule from user_settings DB"
```

---

## Task 4: Calorie Budget Bar — show_bar Parameter

**Files:**
- Modify: `core/health/caloric_budget.py`
- Modify: `telegram-bot/handlers/photo.py`
- Modify: `telegram-bot/handlers/commands.py`

- [ ] **Step 1: Add `show_bar` param to `format_budget_line()` in `caloric_budget.py`**

Change signature at line 110 from:
```python
def format_budget_line(user_id: int, for_date: Optional[date_type] = None) -> str:
```
To:
```python
def format_budget_line(user_id: int, for_date: Optional[date_type] = None, show_bar: bool = True) -> str:
```

Find the return statement (around line 158) and replace with:

```python
    if show_bar:
        bar = sq_fill * filled + "⬜" * (10 - filled)
        return (
            f"\n{icon} {bar} {pct}%\n"
            f"{day_label}: {consumed} / {target} ккал · {tail}{hint}"
        )
    else:
        return f"\n{day_label}: {consumed} / {target} ккал · {tail}{hint}"
```

- [ ] **Step 2: Update `photo.py` to pass `show_bar` from user settings**

In `telegram-bot/handlers/photo.py` near line 1095, replace:

```python
from core.caloric_budget import format_budget_line
# ...
budget = format_budget_line(telegram_user_id, for_date=meal_date)
```

With:

```python
from core.caloric_budget import format_budget_line
from database import SessionLocal
from database.crud import get_user_settings
# ...
_db = SessionLocal()
try:
    _settings = get_user_settings(_db, telegram_user_id)
    _show_bar = _settings.show_calorie_budget_bar if _settings else True
finally:
    _db.close()
budget = format_budget_line(telegram_user_id, for_date=meal_date, show_bar=_show_bar)
```

- [ ] **Step 3: Update `cmd_day()` in `commands.py` to skip bars when show_bar=False**

In `cmd_day()` (around line 155), after importing from caloric_budget, add:

```python
from database import SessionLocal
from database.crud import get_user_settings

_db_s = SessionLocal()
try:
    _us = get_user_settings(_db_s, user_id)
    show_bar = _us.show_calorie_budget_bar if _us else True
finally:
    _db_s.close()
```

Then wrap the bar generation block (lines 181–210) with a condition:

```python
if show_bar:
    cal_bar, cal_pct = make_block_bar(totals.calories, target_cal)
    # ... all bar lines ...
    response_parts.append(
        f"{cal_bar} {round(totals.calories):.0f} / {target_cal} ккал · {cal_tail}",
        # macro bars etc
    )
else:
    # No bar — plain text calorie line
    response_parts.append(
        f"{round(totals.calories):.0f} / {target_cal} ккал · {cal_tail}"
    )
```

- [ ] **Step 4: Run full test suite**

```bash
cd /Users/alexlyskovsky/HealthVault && python -m pytest tests/ -v --timeout=10 2>&1 | tail -20
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add core/health/caloric_budget.py telegram-bot/handlers/photo.py telegram-bot/handlers/commands.py
git commit -m "feat: add show_bar param to calorie budget — respects user settings"
```

---

## Task 5: API Endpoint `/api/settings`

**Files:**
- Modify: `telegram-bot/webhook/apple_health.py`

- [ ] **Step 1: Add HMAC auth helper**

At the top of `apple_health.py`, after imports, add:

```python
import hmac
import hashlib
import json
import urllib.parse

BOT_TOKEN = os.getenv("BOT_TOKEN", "")


def verify_telegram_init_data(init_data_str: str) -> dict:
    """
    Validate Telegram WebApp initData signature and return user dict.
    Raises ValueError if invalid.

    Telegram docs: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    if not init_data_str:
        raise ValueError("Empty initData")

    params = dict(urllib.parse.parse_qsl(init_data_str, keep_blank_values=True))
    received_hash = params.pop("hash", None)
    if not received_hash:
        raise ValueError("No hash in initData")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed, received_hash):
        raise ValueError("initData HMAC mismatch")

    return json.loads(params.get("user", "{}"))


def get_tg_user(authorization: str = Header(...)) -> dict:
    """FastAPI dependency: validates TMA token, returns Telegram user dict."""
    if not authorization.startswith("tma "):
        raise HTTPException(status_code=401, detail="Expected 'tma <initData>'")
    init_data = authorization.removeprefix("tma ").strip()
    try:
        return verify_telegram_init_data(init_data)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
```

- [ ] **Step 2: Add Pydantic schema and GET/POST endpoints**

After the existing `/health` endpoint, add:

```python
from pydantic import BaseModel as PydanticBase
from typing import List as TypingList

class SupplementItem(PydanticBase):
    name: str
    slot: str  # morning_before | morning_with | evening


class UserSettingsSchema(PydanticBase):
    show_calorie_budget_bar: bool = True
    bmr_override: Optional[int] = None
    target_weight_kg: Optional[float] = None
    target_weight_date: Optional[str] = None  # YYYY-MM-DD string
    supplement_reminders_enabled: bool = False
    supplement_reminder_time: str = "08:00"   # HH:MM string
    supplements: TypingList[SupplementItem] = []


@app.get("/api/settings")
async def get_settings(tg_user: dict = Depends(get_tg_user)):
    """Return current settings for authenticated Telegram user."""
    user_id = tg_user.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="No user id in initData")

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

    from database import SessionLocal
    from database.crud import get_user_settings
    from core.health.supplements import DEFAULT_SUPPLEMENTS

    db = SessionLocal()
    try:
        s = get_user_settings(db, user_id)
        if s is None:
            # Return defaults for unknown user
            return {
                "show_calorie_budget_bar": True,
                "bmr_override": None,
                "target_weight_kg": None,
                "target_weight_date": None,
                "supplement_reminders_enabled": False,
                "supplement_reminder_time": "08:00",
                "supplements": DEFAULT_SUPPLEMENTS,
            }
        return {
            "show_calorie_budget_bar": s.show_calorie_budget_bar,
            "bmr_override": s.bmr_override,
            "target_weight_kg": s.target_weight_kg,
            "target_weight_date": s.target_weight_date.isoformat() if s.target_weight_date else None,
            "supplement_reminders_enabled": s.supplement_reminders_enabled,
            "supplement_reminder_time": s.supplement_reminder_time.strftime("%H:%M") if s.supplement_reminder_time else "08:00",
            "supplements": s.supplements or [],
        }
    finally:
        db.close()


@app.post("/api/settings")
async def save_settings(payload: UserSettingsSchema, tg_user: dict = Depends(get_tg_user)):
    """Save settings for authenticated Telegram user."""
    user_id = tg_user.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="No user id in initData")

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

    from database import SessionLocal
    from database.crud import upsert_user_settings
    from datetime import date as date_cls, time as time_cls

    # Parse target_weight_date string → date object
    twd = None
    if payload.target_weight_date:
        try:
            twd = date_cls.fromisoformat(payload.target_weight_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid target_weight_date format, use YYYY-MM-DD")

    # Parse supplement_reminder_time string → time object
    try:
        h, m = payload.supplement_reminder_time.split(":")
        reminder_time = time_cls(int(h), int(m))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid supplement_reminder_time, use HH:MM")

    supplements_list = [s.dict() for s in payload.supplements]

    db = SessionLocal()
    try:
        upsert_user_settings(
            db,
            user_id=user_id,
            show_calorie_budget_bar=payload.show_calorie_budget_bar,
            bmr_override=payload.bmr_override,
            target_weight_kg=payload.target_weight_kg,
            target_weight_date=twd,
            supplement_reminders_enabled=payload.supplement_reminders_enabled,
            supplement_reminder_time=reminder_time,
            supplements=supplements_list,
        )
    finally:
        db.close()

    return {"status": "ok"}
```

- [ ] **Step 3: Mount static files for webapp**

At the bottom of the FastAPI app setup (after all routes), add:

```python
from fastapi.staticfiles import StaticFiles
from pathlib import Path

_webapp_dir = Path(__file__).parent.parent / "webapp"
if _webapp_dir.exists():
    app.mount("/webapp", StaticFiles(directory=str(_webapp_dir), html=True), name="webapp")
```

- [ ] **Step 4: Add `fastapi[staticfiles]` dependency check**

In `Dockerfile` or `requirements.txt`, ensure `aiofiles` is present (needed by StaticFiles):

```bash
grep "aiofiles" /Users/alexlyskovsky/HealthVault/requirements.txt || echo "aiofiles" >> /Users/alexlyskovsky/HealthVault/requirements.txt
```

- [ ] **Step 5: Commit**

```bash
git add telegram-bot/webhook/apple_health.py requirements.txt
git commit -m "feat: add /api/settings endpoint with Telegram WebApp auth"
```

---

## Task 6: Frontend — `webapp/index.html`

**Files:**
- Create: `telegram-bot/webapp/index.html`

- [ ] **Step 1: Create `telegram-bot/webapp/` directory and `index.html`**

```bash
mkdir -p /Users/alexlyskovsky/HealthVault/telegram-bot/webapp
```

Create `telegram-bot/webapp/index.html` with the full SPA. The app has one HTML file with inline CSS and JS — no build step needed.

```html
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
  <title>Настройки NutriLogBot</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           background: var(--tg-theme-bg-color, #fff);
           color: var(--tg-theme-text-color, #222);
           padding: 16px; max-width: 480px; margin: 0 auto; }
    h1 { font-size: 17px; font-weight: 600; margin-bottom: 4px; }
    .subtitle { font-size: 13px; color: #888; margin-bottom: 20px; }
    .tiles { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .tile { background: #f0f7ff; border-radius: 14px; padding: 18px 14px;
            text-align: center; cursor: pointer; border: none; width: 100%;
            transition: opacity .15s; }
    .tile:active { opacity: .7; }
    .tile .icon { font-size: 28px; margin-bottom: 8px; }
    .tile .name { font-weight: 600; font-size: 13px; }
    .tile .desc { font-size: 11px; color: #888; margin-top: 3px; }
    .tile.green { background: #f0fff4; }
    .tile.orange { background: #fff8f0; }
    .tile.purple { background: #faf0ff; }

    .section { display: none; }
    .section.active { display: block; }

    .back-btn { background: none; border: none; color: #2a7ae2; font-size: 15px;
                cursor: pointer; padding: 0 0 16px 0; display: flex; align-items: center; gap: 4px; }
    .section-title { font-size: 16px; font-weight: 600; margin-bottom: 20px; }

    .field-group { margin-bottom: 20px; }
    .field-label { font-size: 11px; color: #888; text-transform: uppercase;
                   letter-spacing: .5px; margin-bottom: 6px; }
    .field-row { display: flex; gap: 8px; align-items: center; }
    input[type=number], input[type=date], input[type=time], input[type=text] {
      border: 1px solid #ddd; border-radius: 8px; padding: 8px 12px;
      font-size: 14px; outline: none; }
    input:focus { border-color: #2a7ae2; }
    .unit { color: #888; font-size: 13px; white-space: nowrap; }
    .hint { font-size: 11px; color: #aaa; margin-top: 4px; }

    .calc-btn { background: #f0f7ff; border: 1px solid #b3d4f5; border-radius: 8px;
                padding: 6px 10px; font-size: 12px; color: #2a7ae2; cursor: pointer;
                white-space: nowrap; }
    .calc-panel { background: #f8f9fa; border-radius: 10px; padding: 12px;
                  margin-top: 8px; display: none; }
    .calc-panel.open { display: block; }
    .calc-panel .field-row { margin-bottom: 8px; }

    .toggle-row { display: flex; justify-content: space-between; align-items: center;
                  padding: 12px 0; border-bottom: 1px solid #f0f0f0; }
    .toggle-info .name { font-size: 13px; font-weight: 500; }
    .toggle-info .desc { font-size: 11px; color: #aaa; margin-top: 2px; }
    .toggle { position: relative; width: 40px; height: 22px; flex-shrink: 0; }
    .toggle input { opacity: 0; width: 0; height: 0; }
    .slider { position: absolute; inset: 0; background: #ccc; border-radius: 11px;
              cursor: pointer; transition: .2s; }
    .slider:before { content: ''; position: absolute; width: 18px; height: 18px;
                     background: #fff; border-radius: 9px; top: 2px; left: 2px; transition: .2s; }
    input:checked + .slider { background: #34c759; }
    input:checked + .slider:before { transform: translateX(18px); }
    input:disabled + .slider { opacity: .4; cursor: not-allowed; }

    .slot-group { margin-bottom: 16px; }
    .slot-title { font-size: 12px; color: #888; margin-bottom: 6px; font-weight: 500; }
    .supp-list { background: #f8f9fa; border-radius: 10px; overflow: hidden; }
    .supp-item { display: flex; justify-content: space-between; align-items: center;
                 padding: 10px 12px; border-bottom: 1px solid #eee; font-size: 13px; }
    .supp-item:last-child { border-bottom: none; }
    .del-btn { background: none; border: none; color: #ccc; font-size: 18px;
               cursor: pointer; line-height: 1; padding: 0 4px; }
    .del-btn:hover { color: #e74c3c; }
    .add-panel { margin-top: 10px; display: none; }
    .add-panel.open { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    .add-panel input { flex: 1; min-width: 120px; }
    .add-panel select { border: 1px solid #ddd; border-radius: 8px; padding: 8px 10px;
                        font-size: 13px; background: #fff; }
    .add-open-btn { width: 100%; background: #f0fff4; border: 1px dashed #6bcf8a;
                    border-radius: 10px; padding: 10px; font-size: 13px;
                    color: #1a7a3a; cursor: pointer; margin-top: 8px; }
    .add-confirm-btn { background: #2a7ae2; color: #fff; border: none; border-radius: 8px;
                       padding: 8px 14px; font-size: 13px; cursor: pointer; }

    .save-btn { width: 100%; background: #2a7ae2; color: #fff; border: none;
                border-radius: 12px; padding: 14px; font-size: 15px; font-weight: 600;
                cursor: pointer; margin-top: 24px; }
    .save-btn:active { opacity: .85; }
    .saved-toast { text-align: center; color: #34c759; font-size: 13px; margin-top: 8px;
                   display: none; }

    .help-block { margin-bottom: 20px; }
    .help-block h3 { font-size: 14px; font-weight: 600; margin-bottom: 8px; }
    .help-block p, .help-block li { font-size: 13px; color: #555; line-height: 1.7; }
    .help-block ul { list-style: none; padding: 0; }
    .help-block ul li { display: flex; gap: 8px; margin-bottom: 6px; }
    .help-block ul li .emoji { flex-shrink: 0; }
    code { background: #f0f0f0; border-radius: 4px; padding: 1px 6px;
           font-size: 12px; font-family: monospace; }
    .cmd-table { width: 100%; border-collapse: collapse; font-size: 13px; }
    .cmd-table td { padding: 5px 0; border-bottom: 1px solid #f5f5f5; }
    .cmd-table td:first-child { color: #2a7ae2; font-family: monospace; width: 90px; }
    .disabled-notice { font-size: 11px; color: #aaa; margin-top: 3px; }
  </style>
</head>
<body>

<!-- HOME -->
<div id="home" class="section active">
  <h1>⚙️ Настройки</h1>
  <p class="subtitle" id="user-name">NutriLogBot</p>
  <div class="tiles">
    <button class="tile" onclick="go('nutrition')">
      <div class="icon">🥗</div>
      <div class="name">Питание</div>
      <div class="desc">BMR · цель · шкала</div>
    </button>
    <button class="tile green" onclick="go('supplements')">
      <div class="icon">💊</div>
      <div class="name">Добавки</div>
      <div class="desc" id="supp-count">загрузка...</div>
    </button>
    <button class="tile orange" onclick="go('notifications')">
      <div class="icon">🔔</div>
      <div class="name">Уведомления</div>
      <div class="desc" id="notif-status">Выкл</div>
    </button>
    <button class="tile purple" onclick="go('help')">
      <div class="icon">📖</div>
      <div class="name">Справка</div>
      <div class="desc">Как пользоваться</div>
    </button>
  </div>
</div>

<!-- NUTRITION -->
<div id="nutrition" class="section">
  <button class="back-btn" onclick="go('home')">← Назад</button>
  <div class="section-title">🥗 Питание</div>

  <div class="field-group">
    <div class="field-label">Базовый обмен (BMR)</div>
    <div class="field-row">
      <input type="number" id="bmr-input" placeholder="1950" min="800" max="4000" style="width:110px">
      <span class="unit">ккал/день</span>
      <button class="calc-btn" onclick="toggleCalc()">🧮 Рассчитать</button>
    </div>
    <div class="hint" id="bmr-hint">Оставьте пустым — будет использоваться Garmin</div>
    <div class="calc-panel" id="calc-panel">
      <div class="field-label">Рассчитать по параметрам (Миффлин)</div>
      <div class="field-row"><input type="number" id="calc-height" placeholder="Рост, см" style="width:110px"><span class="unit">см</span></div>
      <div style="height:6px"></div>
      <div class="field-row"><input type="number" id="calc-weight" placeholder="Вес, кг" style="width:110px"><span class="unit">кг</span></div>
      <div style="height:6px"></div>
      <div class="field-row"><input type="number" id="calc-age" placeholder="Возраст" style="width:110px"><span class="unit">лет</span></div>
      <div style="height:8px"></div>
      <button class="calc-btn" onclick="calcBMR()">Рассчитать →</button>
    </div>
  </div>

  <div class="field-group">
    <div class="field-label">Цель по весу</div>
    <div class="field-row">
      <input type="number" id="target-weight" placeholder="75" step="0.1" style="width:90px">
      <span class="unit">кг до</span>
      <input type="date" id="target-date" style="width:150px">
    </div>
  </div>

  <div class="field-group">
    <div class="field-label">Отображение</div>
    <div class="toggle-row">
      <div class="toggle-info">
        <div class="name">Шкала калорий в /day</div>
        <div class="desc">Полоска 🟩🟥 с процентами</div>
      </div>
      <label class="toggle">
        <input type="checkbox" id="show-bar" checked>
        <span class="slider"></span>
      </label>
    </div>
  </div>

  <button class="save-btn" onclick="saveNutrition()">Сохранить</button>
  <div class="saved-toast" id="nutrition-toast">✅ Сохранено</div>
</div>

<!-- SUPPLEMENTS -->
<div id="supplements" class="section">
  <button class="back-btn" onclick="go('home')">← Назад</button>
  <div class="section-title">💊 Добавки</div>
  <div id="supp-slots"></div>
  <button class="add-open-btn" onclick="toggleAddPanel()">+ Добавить добавку</button>
  <div class="add-panel" id="add-panel">
    <input type="text" id="new-supp-name" placeholder="Название добавки" style="flex:1;min-width:120px">
    <select id="new-supp-slot">
      <option value="morning_before">☀️ Утро (до еды)</option>
      <option value="morning_with" selected>🌅 Утро (с завтраком)</option>
      <option value="evening">🌙 Вечер</option>
    </select>
    <button class="add-confirm-btn" onclick="addSupplement()">Добавить</button>
  </div>
  <button class="save-btn" onclick="saveSupplements()">Сохранить</button>
  <div class="saved-toast" id="supp-toast">✅ Сохранено</div>
</div>

<!-- NOTIFICATIONS -->
<div id="notifications" class="section">
  <button class="back-btn" onclick="go('home')">← Назад</button>
  <div class="section-title">🔔 Уведомления</div>

  <div class="toggle-row">
    <div class="toggle-info">
      <div class="name">Напоминание о добавках</div>
      <div class="desc">Бот напишет в указанное время</div>
    </div>
    <label class="toggle">
      <input type="checkbox" id="reminders-toggle" onchange="toggleReminderTime()">
      <span class="slider"></span>
    </label>
  </div>
  <div id="reminder-time-row" style="padding:10px 0;display:none">
    <div class="field-row">
      <span class="unit">Время:</span>
      <input type="time" id="reminder-time" value="08:00" style="width:100px">
    </div>
  </div>

  <div class="toggle-row" style="margin-top:12px;opacity:.5">
    <div class="toggle-info">
      <div class="name">Утренний брифинг</div>
      <div class="desc">Сон, HRV, план дня</div>
      <div class="disabled-notice">🔜 Скоро</div>
    </div>
    <label class="toggle">
      <input type="checkbox" disabled>
      <span class="slider"></span>
    </label>
  </div>

  <button class="save-btn" onclick="saveNotifications()">Сохранить</button>
  <div class="saved-toast" id="notif-toast">✅ Сохранено</div>
</div>

<!-- HELP -->
<div id="help" class="section">
  <button class="back-btn" onclick="go('home')">← Назад</button>
  <div class="section-title">📖 Справка</div>

  <div class="help-block">
    <h3>🍽 Как логировать еду</h3>
    <ul>
      <li><span class="emoji">✍️</span><span>Текст: <code>гречка 150г, курица 200г</code></span></li>
      <li><span class="emoji">📸</span><span>Фото тарелки — бот распознает блюдо и оценит КБЖУ</span></li>
      <li><span class="emoji">📦</span><span>Фото упаковки — бот считает с этикетки, укажите количество</span></li>
      <li><span class="emoji">🎤</span><span>Голосовое сообщение — транскрибируется автоматически</span></li>
    </ul>
  </div>

  <div class="help-block">
    <h3>💊 Как отметить добавки</h3>
    <p>Напишите названия в чат: <code>Витамин Д, Омега, Метилфолат</code><br>
    Список добавок настраивается в разделе Добавки.</p>
  </div>

  <div class="help-block">
    <h3>📊 Команды бота</h3>
    <table class="cmd-table">
      <tr><td>/day</td><td>Итог дня — калории, белок, добавки</td></tr>
      <tr><td>/week</td><td>Сводка за 7 дней</td></tr>
      <tr><td>/vitamins</td><td>Чеклист добавок на сегодня</td></tr>
      <tr><td>/settings</td><td>Открыть эти настройки</td></tr>
    </table>
  </div>

  <div class="help-block">
    <h3>⚖️ Как считается лимит калорий</h3>
    <p>Средний расход за 14 дней по Garmin × 0.85 (дефицит 15%).<br>
    Нет Garmin — используется BMR из раздела Питание.</p>
  </div>
</div>

<script>
const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

let settings = {};
const API = '/api/settings';
const SLOTS = {
  morning_before: '☀️ Утро (до еды)',
  morning_with:   '🌅 Утро (с завтраком)',
  evening:        '🌙 Вечер'
};

// ── Navigation ──────────────────────────────────────────────────────────────
function go(section) {
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.getElementById(section).classList.add('active');
}

// ── Load settings ───────────────────────────────────────────────────────────
async function load() {
  try {
    const res = await fetch(API, {
      headers: { Authorization: 'tma ' + tg.initData }
    });
    settings = await res.json();
    populate();
  } catch(e) {
    console.error('Failed to load settings', e);
  }
}

function populate() {
  // Nutrition
  if (settings.bmr_override) document.getElementById('bmr-input').value = settings.bmr_override;
  if (settings.target_weight_kg) document.getElementById('target-weight').value = settings.target_weight_kg;
  if (settings.target_weight_date) document.getElementById('target-date').value = settings.target_weight_date;
  document.getElementById('show-bar').checked = settings.show_calorie_budget_bar !== false;

  // Supplements
  renderSupplements();

  // Notifications
  document.getElementById('reminders-toggle').checked = !!settings.supplement_reminders_enabled;
  if (settings.supplement_reminder_time)
    document.getElementById('reminder-time').value = settings.supplement_reminder_time;
  toggleReminderTime();

  // Home tile summaries
  const supps = (settings.supplements || []);
  document.getElementById('supp-count').textContent = supps.length + ' активных';
  document.getElementById('notif-status').textContent =
    settings.supplement_reminders_enabled ? ('Вкл · ' + (settings.supplement_reminder_time || '08:00')) : 'Выкл';

  // Username
  if (tg.initDataUnsafe && tg.initDataUnsafe.user)
    document.getElementById('user-name').textContent = tg.initDataUnsafe.user.first_name || '';
}

// ── Supplement rendering ─────────────────────────────────────────────────────
function renderSupplements() {
  const supps = settings.supplements || [];
  const container = document.getElementById('supp-slots');
  container.innerHTML = '';

  for (const [slot, label] of Object.entries(SLOTS)) {
    const items = supps.filter(s => s.slot === slot);
    const div = document.createElement('div');
    div.className = 'slot-group';
    div.innerHTML = `<div class="slot-title">${label}</div>
      <div class="supp-list" id="slot-${slot}">
        ${items.length === 0 ? '<div class="supp-item" style="color:#aaa;font-size:12px">— пусто —</div>' :
          items.map((s,i) => `
            <div class="supp-item">
              <span>${s.name}</span>
              <button class="del-btn" onclick="deleteSupplement('${slot}','${s.name}')">✕</button>
            </div>`).join('')}
      </div>`;
    container.appendChild(div);
  }
}

function deleteSupplement(slot, name) {
  settings.supplements = (settings.supplements || []).filter(
    s => !(s.slot === slot && s.name === name)
  );
  renderSupplements();
}

function toggleAddPanel() {
  const p = document.getElementById('add-panel');
  p.classList.toggle('open');
  if (p.classList.contains('open')) document.getElementById('new-supp-name').focus();
}

function addSupplement() {
  const name = document.getElementById('new-supp-name').value.trim();
  const slot = document.getElementById('new-supp-slot').value;
  if (!name) return;
  settings.supplements = settings.supplements || [];
  settings.supplements.push({ name, slot });
  document.getElementById('new-supp-name').value = '';
  document.getElementById('add-panel').classList.remove('open');
  renderSupplements();
}

// ── BMR calculator ──────────────────────────────────────────────────────────
function toggleCalc() {
  document.getElementById('calc-panel').classList.toggle('open');
}

function calcBMR() {
  const h = parseFloat(document.getElementById('calc-height').value);
  const w = parseFloat(document.getElementById('calc-weight').value);
  const a = parseFloat(document.getElementById('calc-age').value);
  if (!h || !w || !a) { alert('Введите рост, вес и возраст'); return; }
  // Mifflin-St Jeor for male (BMR only, no activity multiplier)
  const bmr = Math.round(10 * w + 6.25 * h - 5 * a + 5);
  document.getElementById('bmr-input').value = bmr;
  document.getElementById('calc-panel').classList.remove('open');
}

// ── Reminder time toggle ────────────────────────────────────────────────────
function toggleReminderTime() {
  const enabled = document.getElementById('reminders-toggle').checked;
  document.getElementById('reminder-time-row').style.display = enabled ? 'block' : 'none';
}

// ── Save helpers ─────────────────────────────────────────────────────────────
async function post(data) {
  const res = await fetch(API, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'tma ' + tg.initData },
    body: JSON.stringify({ ...settings, ...data })
  });
  return res.json();
}

function showToast(id) {
  const t = document.getElementById(id);
  t.style.display = 'block';
  setTimeout(() => { t.style.display = 'none'; }, 2000);
}

async function saveNutrition() {
  const bmr = parseInt(document.getElementById('bmr-input').value) || null;
  const tw  = parseFloat(document.getElementById('target-weight').value) || null;
  const td  = document.getElementById('target-date').value || null;
  const bar = document.getElementById('show-bar').checked;
  await post({ bmr_override: bmr, target_weight_kg: tw, target_weight_date: td, show_calorie_budget_bar: bar });
  Object.assign(settings, { bmr_override: bmr, target_weight_kg: tw, target_weight_date: td, show_calorie_budget_bar: bar });
  showToast('nutrition-toast');
}

async function saveSupplements() {
  await post({ supplements: settings.supplements });
  document.getElementById('supp-count').textContent = (settings.supplements || []).length + ' активных';
  showToast('supp-toast');
}

async function saveNotifications() {
  const enabled = document.getElementById('reminders-toggle').checked;
  const time    = document.getElementById('reminder-time').value;
  await post({ supplement_reminders_enabled: enabled, supplement_reminder_time: time });
  Object.assign(settings, { supplement_reminders_enabled: enabled, supplement_reminder_time: time });
  document.getElementById('notif-status').textContent = enabled ? ('Вкл · ' + time) : 'Выкл';
  showToast('notif-toast');
}

// ── Init ─────────────────────────────────────────────────────────────────────
load();
</script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add telegram-bot/webapp/index.html
git commit -m "feat: add Telegram Mini App webapp/index.html (4 sections)"
```

---

## Task 7: BotFather — Register Menu Button

This is a manual step.

- [ ] **Step 1: Open Telegram, find @BotFather**

Send: `/mybots` → select `@NutriLogBot` → `Bot Settings` → `Menu Button` → `Configure menu button`

- [ ] **Step 2: Set Menu Button URL**

Enter URL: `https://health.orangegate.cc/webapp/`
Enter title: `Настройки`

- [ ] **Step 3: Verify button appears**

Open a chat with the bot — bottom-left should show a menu/app icon. Tap it — should open the webapp.

---

## Task 8: Add to `todo.md` — v2 items

- [ ] **Step 1: Add supplement reminder scheduling to todo.md**

Add the following entry to the `💡 Идеи` section:

```
- 💤 **Supplement reminders — APScheduler (v2)**: UI и DB для напоминаний о добавках готовы (Task 5-6). Нужно добавить APScheduler: `pip install apscheduler`, при старте бота читать всех пользователей с `supplement_reminders_enabled=True`, создавать cron job на каждого через `AsyncIOScheduler`. При изменении настроек через API — обновлять job. Файлы: `telegram-bot/bot.py` (scheduler init), новый `telegram-bot/scheduler.py` (job functions).
```

- [ ] **Step 2: Commit todo change**

```bash
git add todo.md
git commit -m "docs: add APScheduler supplement reminders to v2 todo"
```

---

## Task 9: Deploy and Smoke Test

- [ ] **Step 1: Deploy to server**

```bash
cd /Users/alexlyskovsky/HealthVault && bash deploy.sh
```

- [ ] **Step 2: Verify `/webapp/` is reachable**

```bash
curl -s -o /dev/null -w "%{http_code}" https://health.orangegate.cc/webapp/
```

Expected: `200`

- [ ] **Step 3: Verify API endpoint exists**

```bash
curl -s https://health.orangegate.cc/api/settings \
  -H "Authorization: tma invalid_data" | python3 -m json.tool
```

Expected: `{"detail": "initData HMAC mismatch"}` (403) — confirms endpoint is live and auth works.

- [ ] **Step 4: Open Mini App in Telegram and test full flow**

1. Open @NutriLogBot in Telegram
2. Tap Menu Button → webapp opens
3. Go to Добавки → delete one supplement → save
4. Close and reopen → supplement should still be gone
5. (Nika) Go to Питание → toggle off calorie bar → save
6. Send food to bot → confirm bar is hidden in response

- [ ] **Step 5: Final commit**

```bash
git add .
git commit -m "feat: Telegram Mini App settings — complete v1 implementation"
```
