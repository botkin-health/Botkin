# Sprint 3: ECG Event + Syncope Event Tables Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `ecg_event` and `syncope_event` tables, populate with Andrey's 122 Apple Watch ECG recordings (66 AFib episodes), expose via 2 read-only agent API endpoints, and apply RLS isolation.

**Architecture:** New tables follow the exact pattern of `activity_log`/`weights` in `database/models.py`. SQL migration runs on the Hetzner server (root@116.203.213.137, docker container `healthvault_postgres`). Import script reads from Andrey's `knowledge_base.json` (apple_health.ecg_recordings). Two new GET endpoints added to `agent_tools_api.py` using the existing `get_agent_user` JWT auth dependency.

**Tech Stack:** SQLAlchemy 2.x mapped_column, FastAPI APIRouter, PostgreSQL 15, psycopg2, pytest

**Key domain facts:**
- Andrey Pokhodnya user_id = 836757955, pack_name = 'cardiac'
- 122 ECG recordings: SinusRhythm (53), AtrialFibrillation (66), Высокий пульс (3)
- 66 AFib episodes span 2021-04-01 → 2026-01-17 — clinically critical (POAF history + Reveal Linq)
- POAF episode: 2025-01-27 to 2025-02-02 (hospitalization), coincides with CRP 46.52
- `syncope_event` starts empty; Reveal Linq events will populate it in Sprint 3b

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `database/models.py` | Modify | Add `EcgEvent`, `SyncopeEvent` SQLAlchemy models |
| `database/migrations/add_ecg_syncope_tables.sql` | Create | DDL for both tables |
| `database/migrations/add_ecg_syncope_rls.sql` | Create | RLS policies for `hv_app` role |
| `scripts/import/import_andrey_ecg.py` | Create | Parse KB JSON → INSERT into ecg_event |
| `telegram-bot/webhook/agent_tools_api.py` | Modify | Add `GET /api/agent/ecg_events`, `GET /api/agent/syncope_events` |
| `tests/test_ecg_syncope.py` | Create | Unit + integration tests |

---

## Task 1: DB Migration — Create Tables

**Files:**
- Create: `database/migrations/add_ecg_syncope_tables.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- database/migrations/add_ecg_syncope_tables.sql
-- Sprint 3: ECG recording events + syncope/cardiac events
-- Apply with:
--   docker exec -i healthvault_postgres psql -U healthvault -d healthvault \
--     < /tmp/add_ecg_syncope_tables.sql

-- ── ecg_event ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ecg_event (
    id              SERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    recorded_at     TIMESTAMPTZ NOT NULL,
    classification  VARCHAR(50) NOT NULL,
    -- 'SinusRhythm' | 'AtrialFibrillation' | 'HighHR' | 'Inconclusive' | 'LowOrHighHR'
    afib            BOOLEAN NOT NULL GENERATED ALWAYS AS (classification = 'AtrialFibrillation') STORED,
    symptoms        TEXT,
    device          VARCHAR(50),
    software_version VARCHAR(20),
    sample_rate     INTEGER,           -- Hz, e.g. 512
    csv_path        TEXT,              -- relative path inside Apple Health ZIP, nullable
    source          VARCHAR(50) NOT NULL DEFAULT 'apple_watch',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_ecg_user_ts UNIQUE (user_id, recorded_at)
);
CREATE INDEX IF NOT EXISTS idx_ecg_user_recorded ON ecg_event (user_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_ecg_user_afib ON ecg_event (user_id, afib) WHERE afib = TRUE;

-- ── syncope_event ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS syncope_event (
    id              SERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    occurred_at     TIMESTAMPTZ NOT NULL,
    duration_sec    INTEGER,           -- if known
    context         TEXT,              -- free text: "morning, post-workout, standing up"
    source          VARCHAR(50) NOT NULL DEFAULT 'manual',
    -- 'manual' | 'reveal_linq' | 'apple_watch'
    data            JSONB,             -- device-specific raw data
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_syncope_user_ts UNIQUE (user_id, occurred_at)
);
CREATE INDEX IF NOT EXISTS idx_syncope_user_occurred ON syncope_event (user_id, occurred_at DESC);

COMMENT ON TABLE ecg_event IS 'Apple Watch ECG recordings and Reveal Linq events per user';
COMMENT ON TABLE syncope_event IS 'Syncope/loss-of-consciousness events from all sources';
```

- [ ] **Step 2: Apply migration on server**

```bash
PROJECT_DIR="$HOME/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/Projects/Vibe coding/HealthVault-engine"
SERVER_PASS=$(grep -m1 'PASS=' "$PROJECT_DIR/scripts/util/diagnose_remote.sh" | cut -d'"' -f2)

# Copy and apply
/opt/homebrew/bin/sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no root@116.203.213.137 \
  "docker exec -i healthvault_postgres psql -U healthvault -d healthvault" \
  < "$PROJECT_DIR/database/migrations/add_ecg_syncope_tables.sql"
```

Expected: `CREATE TABLE` × 2, `CREATE INDEX` × 4, `COMMENT` × 2

- [ ] **Step 3: Verify tables exist**

```bash
/opt/homebrew/bin/sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no root@116.203.213.137 \
  "docker exec -i healthvault_postgres psql -U healthvault -d healthvault" << 'SQL'
SELECT table_name FROM information_schema.tables
WHERE table_schema='public' AND table_name IN ('ecg_event','syncope_event');
SQL
```

Expected: 2 rows returned.

- [ ] **Step 4: Commit**

```bash
cd "$PROJECT_DIR"
git add database/migrations/add_ecg_syncope_tables.sql
git commit -m "feat(db): add ecg_event and syncope_event tables — Sprint 3"
```

---

## Task 2: SQLAlchemy Models

**Files:**
- Modify: `database/models.py` (add after `ActivityLog` class, around line 200)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ecg_syncope.py
from database.models import EcgEvent, SyncopeEvent

def test_ecg_event_model_attributes():
    """EcgEvent model must have all required columns."""
    cols = {c.key for c in EcgEvent.__table__.columns}
    assert 'user_id' in cols
    assert 'recorded_at' in cols
    assert 'classification' in cols
    assert 'afib' in cols
    assert 'symptoms' in cols
    assert 'csv_path' in cols

def test_syncope_event_model_attributes():
    cols = {c.key for c in SyncopeEvent.__table__.columns}
    assert 'user_id' in cols
    assert 'occurred_at' in cols
    assert 'context' in cols
    assert 'source' in cols
    assert 'data' in cols
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd "$PROJECT_DIR"
python -m pytest tests/test_ecg_syncope.py -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'EcgEvent'`

- [ ] **Step 3: Add models to database/models.py**

Add after the `ActivityLog` class (after its closing brace):

```python
class EcgEvent(Base):
    __tablename__ = "ecg_event"
    __table_args__ = (
        UniqueConstraint("user_id", "recorded_at", name="uq_ecg_user_ts"),
        Index("idx_ecg_user_recorded", "user_id", "recorded_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    classification: Mapped[str] = mapped_column(String(50), nullable=False)
    # 'SinusRhythm' | 'AtrialFibrillation' | 'HighHR' | 'Inconclusive'
    afib: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    # Note: in production this is a GENERATED column; model stores it explicitly for portability
    symptoms: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    device: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    software_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    sample_rate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    csv_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, server_default="apple_watch")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="ecg_events")


class SyncopeEvent(Base):
    __tablename__ = "syncope_event"
    __table_args__ = (
        UniqueConstraint("user_id", "occurred_at", name="uq_syncope_user_ts"),
        Index("idx_syncope_user_occurred", "user_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id", ondelete="CASCADE"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_sec: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    context: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, server_default="manual")
    data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="syncope_events")
```

Also add to `User` model's relationships (find the existing `User` class and add):
```python
    ecg_events: Mapped[List["EcgEvent"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    syncope_events: Mapped[List["SyncopeEvent"]] = relationship(back_populates="user", cascade="all, delete-orphan")
```

- [ ] **Step 4: Run test to confirm it passes**

```bash
python -m pytest tests/test_ecg_syncope.py::test_ecg_event_model_attributes tests/test_ecg_syncope.py::test_syncope_event_model_attributes -v
```

Expected: 2 PASSED

- [ ] **Step 5: Run full test suite (no regression)**

```bash
python -m pytest tests/ -x -q --ignore=tests/integration 2>&1 | tail -5
```

Expected: all existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add database/models.py tests/test_ecg_syncope.py
git commit -m "feat(models): add EcgEvent and SyncopeEvent SQLAlchemy models"
```

---

## Task 3: RLS Policies

**Files:**
- Create: `database/migrations/add_ecg_syncope_rls.sql`

- [ ] **Step 1: Write RLS migration**

```sql
-- database/migrations/add_ecg_syncope_rls.sql
-- Sprint 3: Row Level Security for ecg_event and syncope_event
-- hv_app role already exists (created by add_rls_policies.sql in Sprint 1a)

GRANT SELECT, INSERT, UPDATE, DELETE ON ecg_event   TO hv_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON syncope_event TO hv_app;
GRANT USAGE, SELECT ON SEQUENCE ecg_event_id_seq      TO hv_app;
GRANT USAGE, SELECT ON SEQUENCE syncope_event_id_seq  TO hv_app;

ALTER TABLE ecg_event     ENABLE ROW LEVEL SECURITY;
ALTER TABLE syncope_event ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS user_isolation ON ecg_event;
DROP POLICY IF EXISTS user_isolation ON syncope_event;

CREATE POLICY user_isolation ON ecg_event
    FOR ALL TO hv_app
    USING (user_id = (NULLIF(current_setting('app.user_id', TRUE), ''))::bigint);

CREATE POLICY user_isolation ON syncope_event
    FOR ALL TO hv_app
    USING (user_id = (NULLIF(current_setting('app.user_id', TRUE), ''))::bigint);
```

- [ ] **Step 2: Apply on server**

```bash
/opt/homebrew/bin/sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no root@116.203.213.137 \
  "docker exec -i healthvault_postgres psql -U healthvault -d healthvault" \
  < "$PROJECT_DIR/database/migrations/add_ecg_syncope_rls.sql"
```

Expected: `GRANT`, `ALTER TABLE` × 2, `DROP POLICY` × 2, `CREATE POLICY` × 2

- [ ] **Step 3: Commit**

```bash
git add database/migrations/add_ecg_syncope_rls.sql
git commit -m "feat(rls): add user_isolation policies for ecg_event and syncope_event"
```

---

## Task 4: ECG Import Script

**Files:**
- Create: `scripts/import/import_andrey_ecg.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ecg_syncope.py — add these tests

import json
from pathlib import Path

def test_parse_ecg_classification():
    """classification normalizer maps known raw values."""
    from scripts.import.import_andrey_ecg import normalize_classification
    assert normalize_classification("SinusRhythm") == "SinusRhythm"
    assert normalize_classification("AtrialFibrillation") == "AtrialFibrillation"
    assert normalize_classification("Высокий пульс") == "HighHR"
    assert normalize_classification("unknown_value") == "Inconclusive"

def test_parse_sample_rate():
    """sample_rate_hz extracts integer from '512 герц' or '512 Hz'."""
    from scripts.import.import_andrey_ecg import parse_sample_rate
    assert parse_sample_rate("512 герц") == 512
    assert parse_sample_rate("512 Hz") == 512
    assert parse_sample_rate("256") == 256
    assert parse_sample_rate(None) is None
    assert parse_sample_rate("unknown") is None
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python -m pytest tests/test_ecg_syncope.py::test_parse_ecg_classification tests/test_ecg_syncope.py::test_parse_sample_rate -v 2>&1 | head -10
```

Expected: `ImportError` — `import_andrey_ecg` doesn't exist yet

- [ ] **Step 3: Create import script**

```python
#!/usr/bin/env python3
"""
scripts/import/import_andrey_ecg.py

Parse Andrey Pokhodnya's ECG recordings from knowledge_base.json (apple_health.ecg_recordings)
and upsert into the ecg_event table.

Usage:
    python3 scripts/import/import_andrey_ecg.py /path/to/andrey_kb.json [--dry-run]

Requires:
    - knowledge_base.json downloaded from GDrive (ID: 1iAjlNDtioPmUp7-tEULuo--D0kXDzfhx)
    - sshpass + server access (root@116.203.213.137)
    - Server env: SERVER_PASS from scripts/util/diagnose_remote.sh
"""
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional


ANDREY_UID = 836757955
SERVER = "root@116.203.213.137"
SSHPASS = "/opt/homebrew/bin/sshpass"

# ── Classification normalization ─────────────────────────────────────────────
_CLASS_MAP = {
    "SinusRhythm": "SinusRhythm",
    "AtrialFibrillation": "AtrialFibrillation",
    "Высокий пульс": "HighHR",
    "HighHR": "HighHR",
    "LowOrHighHR": "HighHR",
    "Inconclusive": "Inconclusive",
}


def normalize_classification(raw: Optional[str]) -> str:
    if raw is None:
        return "Inconclusive"
    return _CLASS_MAP.get(raw, "Inconclusive")


def parse_sample_rate(raw: Optional[str]) -> Optional[int]:
    if raw is None:
        return None
    m = re.search(r'\d+', str(raw))
    return int(m.group()) if m else None


def q(v):
    """SQL-quote a Python value."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    return str(v)


def build_sql(recordings: list) -> str:
    lines = ["BEGIN;"]
    count = 0
    for rec in recordings:
        ts = rec.get("start")
        if not ts:
            continue
        # Normalize timestamp: "2021-04-01 13:29:07" → with timezone
        ts_pg = ts.replace(" ", "T") + "+03:00"  # Apple Health stores Moscow time
        cls = normalize_classification(rec.get("classification"))
        afib = cls == "AtrialFibrillation"
        symptoms = rec.get("symptoms") or None
        device = rec.get("device") or None
        sw = rec.get("software_version") or None
        sr = parse_sample_rate(rec.get("sample_rate"))
        csv_path = rec.get("csv_path") or None
        source = "apple_watch"

        lines.append(
            f"INSERT INTO ecg_event "
            f"(user_id, recorded_at, classification, afib, symptoms, device, software_version, sample_rate, csv_path, source) "
            f"VALUES ({ANDREY_UID}, {q(ts_pg)}, {q(cls)}, {q(afib)}, {q(symptoms)}, "
            f"{q(device)}, {q(sw)}, {q(sr)}, {q(csv_path)}, {q(source)}) "
            f"ON CONFLICT (user_id, recorded_at) DO UPDATE SET "
            f"classification = EXCLUDED.classification, afib = EXCLUDED.afib, "
            f"symptoms = COALESCE(EXCLUDED.symptoms, ecg_event.symptoms), "
            f"csv_path = COALESCE(EXCLUDED.csv_path, ecg_event.csv_path);"
        )
        count += 1

    lines += [
        "COMMIT;",
        "SELECT classification, count(*) FROM ecg_event WHERE user_id=836757955 GROUP BY 1 ORDER BY 1;",
    ]
    return "\n".join(lines), count


def main():
    dry_run = "--dry-run" in sys.argv
    kb_path = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else Path("/tmp/andrey_kb.json")

    print(f"Loading KB from {kb_path} …")
    kb = json.loads(kb_path.read_text())
    recordings = kb["apple_health"].get("ecg_recordings", [])
    print(f"Found {len(recordings)} ECG recordings")

    sql, count = build_sql(recordings)
    print(f"Built {count} INSERT statements")

    if dry_run:
        print("--- DRY RUN: SQL preview (first 500 chars) ---")
        print(sql[:500])
        return

    # Read server password
    project_dir = Path(__file__).resolve().parents[2]
    diag = project_dir / "scripts/util/diagnose_remote.sh"
    server_pass = None
    for line in diag.read_text().splitlines():
        if line.startswith("PASS="):
            server_pass = line.split('"')[1]
            break
    if not server_pass:
        print("ERROR: cannot find PASS in diagnose_remote.sh", file=sys.stderr)
        sys.exit(1)

    print("Inserting into ecg_event on server …")
    result = subprocess.run(
        [SSHPASS, "-p", server_pass, "ssh", "-o", "StrictHostKeyChecking=no",
         SERVER, "docker exec -i healthvault_postgres psql -U healthvault -d healthvault"],
        input=sql, capture_output=True, text=True,
    )
    print("OUT:", result.stdout[-1000:])
    if result.returncode != 0:
        print("ERR:", result.stderr[-500:], file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the failing tests again (should pass now)**

```bash
python -m pytest tests/test_ecg_syncope.py::test_parse_ecg_classification tests/test_ecg_syncope.py::test_parse_sample_rate -v
```

Expected: 2 PASSED

- [ ] **Step 5: Dry-run the import**

```bash
python3 scripts/import/import_andrey_ecg.py /tmp/andrey_kb.json --dry-run
```

Expected output:
```
Loading KB from /tmp/andrey_kb.json …
Found 122 ECG recordings
Built 122 INSERT statements
--- DRY RUN: SQL preview (first 500 chars) ---
BEGIN;
INSERT INTO ecg_event ...
```

- [ ] **Step 6: Run the actual import**

```bash
python3 scripts/import/import_andrey_ecg.py /tmp/andrey_kb.json
```

Expected final lines:
```
      classification      | count
--------------------------+-------
 AtrialFibrillation       |    66
 HighHR                   |     3
 SinusRhythm              |    53
(3 rows)
```

- [ ] **Step 7: Commit**

```bash
git add scripts/import/import_andrey_ecg.py tests/test_ecg_syncope.py
git commit -m "feat(import): ECG event import script for Andrey — 122 Apple Watch recordings"
```

---

## Task 5: Agent API Endpoints

**Files:**
- Modify: `telegram-bot/webhook/agent_tools_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ecg_syncope.py — append

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


def _make_mock_db(ecg_rows, syncope_rows):
    """Returns a mock db Session that yields rows for ecg/syncope queries."""
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = ecg_rows
    return db


def test_ecg_events_endpoint_returns_list(monkeypatch):
    """GET /api/agent/ecg_events returns list of ECG records for authenticated user."""
    from webhook.agent_tools_api import router
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    mock_user = MagicMock()
    mock_user.telegram_id = 836757955
    mock_db = MagicMock()
    mock_ecg = MagicMock()
    mock_ecg.recorded_at.isoformat.return_value = "2025-01-27T10:00:00+03:00"
    mock_ecg.classification = "AtrialFibrillation"
    mock_ecg.afib = True
    mock_ecg.symptoms = ""
    mock_ecg.device = "Watch7,5"
    mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [mock_ecg]

    with patch("webhook.agent_tools_api.get_agent_user", return_value=mock_user), \
         patch("webhook.agent_tools_api.get_db", return_value=iter([mock_db])):
        resp = client.get("/api/agent/ecg_events?limit=10",
                          headers={"Authorization": "Bearer test"})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert data[0]["classification"] == "AtrialFibrillation"
    assert data[0]["afib"] is True
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
python -m pytest tests/test_ecg_syncope.py::test_ecg_events_endpoint_returns_list -v 2>&1 | head -15
```

Expected: FAIL — endpoint doesn't exist yet

- [ ] **Step 3: Add endpoints to agent_tools_api.py**

Add at the end of the file (before any `if __name__` block):

```python
# ── ECG events ────────────────────────────────────────────────────────────────

@router.get("/ecg_events")
async def get_ecg_events(
    limit: int = 50,
    afib_only: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_agent_user),
):
    """Return ECG recordings for the authenticated user, newest first.

    Query params:
    - limit: max rows (default 50, max 200)
    - afib_only: if true, return only AtrialFibrillation recordings
    """
    from database.models import EcgEvent

    limit = min(limit, 200)
    q = db.query(EcgEvent).filter(EcgEvent.user_id == user.telegram_id)
    if afib_only:
        q = q.filter(EcgEvent.afib == True)  # noqa: E712
    rows = q.order_by(EcgEvent.recorded_at.desc()).limit(limit).all()
    return [
        {
            "recorded_at": r.recorded_at.isoformat(),
            "classification": r.classification,
            "afib": r.afib,
            "symptoms": r.symptoms,
            "device": r.device,
            "sample_rate": r.sample_rate,
            "csv_path": r.csv_path,
        }
        for r in rows
    ]


@router.get("/syncope_events")
async def get_syncope_events(
    limit: int = 50,
    db: Session = Depends(get_db),
    user: User = Depends(get_agent_user),
):
    """Return syncope/cardiac events for the authenticated user, newest first."""
    from database.models import SyncopeEvent

    limit = min(limit, 200)
    rows = (
        db.query(SyncopeEvent)
        .filter(SyncopeEvent.user_id == user.telegram_id)
        .order_by(SyncopeEvent.occurred_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "occurred_at": r.occurred_at.isoformat(),
            "duration_sec": r.duration_sec,
            "context": r.context,
            "source": r.source,
            "data": r.data,
        }
        for r in rows
    ]
```

Also add `Session` to imports at top of file if not already present:
```python
from sqlalchemy.orm import Session
```

And add `User` import from database.models if not already there.

- [ ] **Step 4: Run test to confirm it passes**

```bash
python -m pytest tests/test_ecg_syncope.py::test_ecg_events_endpoint_returns_list -v
```

Expected: PASSED

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest tests/ -x -q --ignore=tests/integration 2>&1 | tail -5
```

Expected: all passing

- [ ] **Step 6: Commit**

```bash
git add telegram-bot/webhook/agent_tools_api.py tests/test_ecg_syncope.py
git commit -m "feat(api): add /ecg_events and /syncope_events agent endpoints — Sprint 3"
```

---

## Task 6: Deploy & Smoke Test

**Files:**
- No new files; deploy existing changes

- [ ] **Step 1: Push to GitHub**

```bash
git push origin main
```

- [ ] **Step 2: Deploy to server**

```bash
/opt/homebrew/bin/sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no root@116.203.213.137 bash << 'ENDSSH'
cd /opt/healthvault
git pull origin main
docker compose restart healthvault_app
sleep 5
docker logs healthvault_app --tail 20
ENDSSH
```

Expected: No import errors, "Application startup complete" in logs.

- [ ] **Step 3: Smoke-test endpoint on server**

```bash
# Get Andrey's JWT token first
/opt/homebrew/bin/sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no root@116.203.213.137 \
  "docker exec -i healthvault_postgres psql -U healthvault -d healthvault -c \
   \"SELECT jwt_secret FROM users WHERE telegram_id=836757955;\""

# Then test endpoint (replace JWT_SECRET with actual value)
curl -s https://health.orangegate.cc/api/agent/ecg_events?afib_only=true \
  -H "Authorization: Bearer $(python3 -c "
import hmac, hashlib, base64, json, time
# paste jwt_secret value here
SECRET = 'ANDREY_JWT_SECRET'
header = base64.urlsafe_b64encode(json.dumps({'alg':'HS256','typ':'JWT'}).encode()).rstrip(b'=')
payload = base64.urlsafe_b64encode(json.dumps({'sub':'836757955','exp':int(time.time())+3600}).encode()).rstrip(b'=')
sig = base64.urlsafe_b64encode(hmac.new(SECRET.encode(), header+b'.'+payload, hashlib.sha256).digest()).rstrip(b'=')
print((header+b'.'+payload+b'.'+sig).decode())
")" | python3 -m json.tool | head -20
```

Expected: JSON array with 66 AFib ECG events.

- [ ] **Step 4: Verify counts in DB**

```bash
/opt/homebrew/bin/sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no root@116.203.213.137 \
  "docker exec -i healthvault_postgres psql -U healthvault -d healthvault" << 'SQL'
SELECT classification, count(*), min(recorded_at)::date, max(recorded_at)::date
FROM ecg_event WHERE user_id=836757955 GROUP BY 1 ORDER BY 1;
SQL
```

Expected:
```
    classification    | count |    min     |    max
----------------------+-------+------------+------------
 AtrialFibrillation   |    66 | 2021-04-01 | 2026-01-17
 HighHR               |     3 | ...        | ...
 SinusRhythm          |    53 | ...        | ...
```

- [ ] **Step 5: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix(sprint3): post-deploy fixes if any"
git push origin main
```

---

## Self-Review Checklist

**Spec coverage:**
- ✅ ecg_event table + migration
- ✅ syncope_event table + migration
- ✅ SQLAlchemy models for both
- ✅ RLS policies for hv_app
- ✅ Import script for Andrey's 122 ECG recordings
- ✅ /api/agent/ecg_events endpoint (with afib_only filter)
- ✅ /api/agent/syncope_events endpoint
- ✅ Tests for parsers + endpoints

**Out of scope (Sprint 3b):**
- heart_rate_log (387k rows, needs ZIP parsing)
- Reveal Linq data → syncope_event
- workout_log (GPX routes)
- ECG waveform CSV serving via API

**Notes:**
- The `afib` column is a GENERATED column in PostgreSQL (`GENERATED ALWAYS AS ... STORED`) but stored explicitly in the SQLAlchemy model for portability. Import script sets both classification and afib explicitly.
- Andrey's Apple Health timestamps are in Moscow time (+03:00) — import script adds timezone offset.
- syncope_event starts empty for Andrey (2 events from Reveal Linq will be added manually or in Sprint 3b).
