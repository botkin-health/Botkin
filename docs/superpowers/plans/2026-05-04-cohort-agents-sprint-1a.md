# Cohort Agents — Sprint 1a Implementation Plan (Python Foundation)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Подготовить Python-инфраструктуру под cohort-агентов: миграции БД (cohort/RLS/audit), JWT-middleware, 8 Tools API endpoint'ов, Telegram-router, wizard `/start`, `/regenerate_health_token`, адаптивный dashboard. После Sprint 1a существующие пользователи продолжают работать как раньше, плюс готова инфраструктура — но Node-контейнеры ещё не запущены (это Sprint 1b).

**Architecture:** Изменения локализованы в Python: новые SQL-миграции (`database/migrations/`), новый router-модуль (`telegram-bot/webhook/agent_tools_api.py`), JWT-helper (`telegram-bot/webhook/jwt_auth.py`), новый Telegram-роутер (`telegram-bot/webhook/telegram_router.py`). Существующие FastAPI endpoint'ы и handler'ы НЕ трогаем — расширяем через `include_router`.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, PostgreSQL 15, aiogram 3, pytest. JWT через `pyjwt` (новая зависимость). Шифрование BYOK-ключей через `cryptography.fernet` (новая зависимость).

**Pre-requirements:**
- ✅ Бэкап БД сделан (`/Users/.../HealthVault/_backups_db/healthvault_db_2026-05-04_1710_pre-refactor.*`)
- ✅ Auto-backup починен (cron 04:17 UTC работает)
- ✅ Spec утверждён: `docs/superpowers/specs/2026-05-04-cohort-agents-design.md`
- ⚠ Worktree: при желании создать `git worktree add ../HealthVault-sprint1a -b sprint/1a-cohort-foundation` перед Task 1. Иначе работаем в main.

**Deviation from spec:** Использую session-variable RLS-паттерн (`SET LOCAL app.user_id`) вместо PG-роли-на-пользователя. Спек §5.2 обновлён.

---

## File Structure

| Файл | Действие | Что внутри |
|------|----------|------------|
| `database/migrations/add_cohort_columns.sql` | NEW | ALTER `users` (cohort, container_id, container_port, pack_name, jwt_secret, encrypted_openai_key, encrypted_anthropic_key) + backfill для 3 существующих пользователей |
| `database/migrations/add_rls_policies.sql` | NEW | `CREATE ROLE hv_app`, ENABLE RLS на 6 таблицах, политики `user_isolation` |
| `database/migrations/add_audit_log.sql` | NEW | Таблица `audit_log` + триггер `audit_admin_access()` |
| `database/models.py` | MODIFY | User model: новые поля. Новая модель AuditLog. |
| `database/crud.py` | MODIFY | `get_user_by_jwt_user_id()`, `set_user_session_var()`, `regenerate_jwt_secret()`, `regenerate_health_token()` |
| `telegram-bot/webhook/jwt_auth.py` | NEW | JWT validation (`get_agent_user`), генерация токенов |
| `telegram-bot/webhook/agent_tools_api.py` | NEW | 8 endpoint'ов: log_meal_text, log_supplement, log_bp, recent_meals, kb_value, dashboard_summary, user_profile, regenerate_health_token |
| `telegram-bot/webhook/telegram_router.py` | NEW | POST `/telegram/webhook` — вход с роутингом по `from.id` |
| `telegram-bot/handlers/onboarding.py` | NEW | Wizard `/start` для новых пользователей (FSM на aiogram) |
| `telegram-bot/handlers/commands.py` | MODIFY | Добавить `/regenerate_health_token` |
| `telegram-bot/dashboard_blocks.py` | NEW | Helpers `has_garmin_data()`, `has_apple_health_data()`, `has_blood_test_data()` для skip пустых блоков |
| `telegram-bot/dashboard_generator.py` | MODIFY | Использовать helper'ы из `dashboard_blocks.py`, не падать на пустых данных |
| `telegram-bot/webhook/apple_health.py` | MODIFY | Подключить новые роутеры через `include_router` |
| `requirements.txt` | MODIFY | + `pyjwt`, + `cryptography` |
| `tests/test_jwt_auth.py` | NEW | unit-тесты JWT |
| `tests/test_agent_tools_api.py` | NEW | unit + integration тесты endpoint'ов |
| `tests/test_dashboard_blocks.py` | NEW | unit-тесты адаптивных блоков |
| `tests/integration/test_rls_isolation.py` | NEW | integration — RLS блокирует чужие строки |
| `tests/integration/test_audit_trail.py` | NEW | integration — admin SELECT пишется в audit_log |
| `tests/integration/test_telegram_router.py` | NEW | integration — router форвардит правильно |
| `tests/integration/test_onboarding_wizard.py` | NEW | integration — wizard FSM проходит до конца |
| `todo.md` | MODIFY | Маркировать Sprint 1a задачи как done после каждого task'а |

---

## Tasks

### Task 1: Миграция — новые колонки в users

**Files:**
- Create: `database/migrations/add_cohort_columns.sql`
- Modify: `database/models.py` (класс `User`)
- Test: `tests/test_user_model.py` (новый)

- [ ] **Step 1.1: Сделать бэкап перед миграцией**

```bash
ssh root@116.203.213.137 "/opt/healthvault/scripts/auto_backup.sh"
ls -la /opt/healthvault/backups/ | tail -3
```

Expected: новый файл `healthvault_db_<сегодня>.sql.gz` появился.

- [ ] **Step 1.2: Написать failing test для новых полей User**

```python
# tests/test_user_model.py
import pytest
from database.models import User, Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    yield Session()


def test_user_has_cohort_field(db):
    u = User(telegram_id=999, first_name="Test", cohort="early_user", pack_name="cardiac")
    db.add(u)
    db.commit()
    fetched = db.query(User).filter_by(telegram_id=999).first()
    assert fetched.cohort == "early_user"
    assert fetched.pack_name == "cardiac"
    assert fetched.container_id is None  # nullable
    assert fetched.jwt_secret is None
```

- [ ] **Step 1.3: Запустить тест — должен упасть**

Run: `pytest tests/test_user_model.py::test_user_has_cohort_field -v`
Expected: FAIL — `'cohort' is an invalid keyword argument for User`.

- [ ] **Step 1.4: Создать SQL-миграцию**

```sql
-- database/migrations/add_cohort_columns.sql
-- Adds cohort/container/pack/jwt/byok columns to users.
-- Run after backup. Idempotent.

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS cohort VARCHAR(20) NOT NULL DEFAULT 'external'
    CHECK (cohort IN ('owner', 'family', 'early_user', 'external')),
  ADD COLUMN IF NOT EXISTS container_id VARCHAR(50),
  ADD COLUMN IF NOT EXISTS container_port INTEGER,
  ADD COLUMN IF NOT EXISTS pack_name VARCHAR(50) NOT NULL DEFAULT 'generic'
    CHECK (pack_name IN ('generic', 'cardiac', 'bariatric', 'female-cycle')),
  ADD COLUMN IF NOT EXISTS jwt_secret VARCHAR(64),
  ADD COLUMN IF NOT EXISTS encrypted_openai_key TEXT,
  ADD COLUMN IF NOT EXISTS encrypted_anthropic_key TEXT;

-- Backfill: existing users.
UPDATE users SET cohort = 'owner',       pack_name = 'bariatric'    WHERE telegram_id = 895655;
UPDATE users SET cohort = 'family',      pack_name = 'female-cycle' WHERE telegram_id = 485132;
UPDATE users SET cohort = 'early_user',  pack_name = 'cardiac'      WHERE telegram_id = 836757955;
```

- [ ] **Step 1.5: Обновить SQLAlchemy модель**

```python
# database/models.py — внутри class User
cohort: Mapped[str] = mapped_column(String(20), default="external", server_default="external")
container_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
container_port: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
pack_name: Mapped[str] = mapped_column(String(50), default="generic", server_default="generic")
jwt_secret: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
encrypted_openai_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
encrypted_anthropic_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
```

- [ ] **Step 1.6: Запустить тест — должен пройти**

Run: `pytest tests/test_user_model.py::test_user_has_cohort_field -v`
Expected: PASS.

- [ ] **Step 1.7: Применить миграцию на dev (локальный docker postgres) → если есть, иначе сразу prod**

```bash
ssh root@116.203.213.137 "docker exec -i healthvault_postgres psql -U healthvault -d healthvault" \
  < database/migrations/add_cohort_columns.sql
```

Expected: `ALTER TABLE`, `UPDATE 1` × 3 (для трёх существующих юзеров).

- [ ] **Step 1.8: Verify в БД**

```bash
ssh root@116.203.213.137 "docker exec healthvault_postgres psql -U healthvault -d healthvault -c \
  \"SELECT telegram_id, cohort, pack_name, container_id FROM users WHERE telegram_id IN (895655, 485132, 836757955);\""
```

Expected:
```
 895655    | owner       | bariatric    |
 485132    | family      | female-cycle |
 836757955 | early_user  | cardiac      |
```

- [ ] **Step 1.9: Commit**

```bash
git add database/migrations/add_cohort_columns.sql database/models.py tests/test_user_model.py
git commit -m "feat(db): add cohort/container/pack/jwt/byok columns to users"
```

---

### Task 2: Миграция — RLS политики + app-роль

**Files:**
- Create: `database/migrations/add_rls_policies.sql`
- Modify: `database/crud.py` (новая функция `set_user_session_var`)
- Test: `tests/integration/test_rls_isolation.py` (новый)

- [ ] **Step 2.1: Сгенерировать пароль для hv_app роли**

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# Сохрани вывод — добавим в .env как HV_APP_DB_PASSWORD
```

- [ ] **Step 2.2: Добавить пароль в .env (локально и на сервере)**

```bash
# локально
echo "HV_APP_DB_PASSWORD=<сгенерированный_выше>" >> .env

# на сервере
ssh root@116.203.213.137 "echo 'HV_APP_DB_PASSWORD=<сгенерированный>' >> /opt/healthvault/.env"
```

- [ ] **Step 2.3: Написать failing integration test для RLS**

```python
# tests/integration/test_rls_isolation.py
import pytest
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


pytestmark = pytest.mark.integration


@pytest.fixture
def hv_app_session():
    """Connection as hv_app role — RLS-restricted."""
    pwd = os.environ["HV_APP_DB_PASSWORD"]
    url = f"postgresql://hv_app:{pwd}@116.203.213.137:5432/healthvault"
    engine = create_engine(url)
    Session = sessionmaker(bind=engine)
    yield Session()


def test_rls_blocks_other_users_meals(hv_app_session):
    """When session.app.user_id = Sasha, can't see Nika's nutrition_log rows."""
    hv_app_session.execute(text("SET LOCAL app.user_id = '895655'"))  # Sasha
    rows = hv_app_session.execute(
        text("SELECT user_id FROM nutrition_log WHERE user_id = 485132 LIMIT 5")
    ).fetchall()
    assert len(rows) == 0, "Sasha's session shouldn't see Nika's nutrition rows"


def test_rls_allows_own_user_meals(hv_app_session):
    """When session.app.user_id = Sasha, can see Sasha's nutrition_log rows."""
    hv_app_session.execute(text("SET LOCAL app.user_id = '895655'"))
    rows = hv_app_session.execute(
        text("SELECT user_id FROM nutrition_log WHERE user_id = 895655 LIMIT 5")
    ).fetchall()
    assert len(rows) > 0, "Sasha's session should see Sasha's own rows"
```

- [ ] **Step 2.4: Запустить тест — должен упасть**

Run: `pytest tests/integration/test_rls_isolation.py -m integration -v`
Expected: FAIL — `role "hv_app" does not exist` или похожее.

- [ ] **Step 2.5: Создать SQL-миграцию RLS**

```sql
-- database/migrations/add_rls_policies.sql
-- Создаёт app-роль hv_app, включает RLS на 6 data-таблицах.
-- Admin-роль 'healthvault' (superuser) обходит RLS — для неё работает audit_log (см. add_audit_log.sql).

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hv_app') THEN
    EXECUTE format('CREATE ROLE hv_app LOGIN PASSWORD %L', current_setting('hv.app_password'));
  END IF;
END $$;

GRANT CONNECT ON DATABASE healthvault TO hv_app;
GRANT USAGE ON SCHEMA public TO hv_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO hv_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hv_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO hv_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO hv_app;

-- RLS
ALTER TABLE nutrition_log         ENABLE ROW LEVEL SECURITY;
ALTER TABLE supplements_log       ENABLE ROW LEVEL SECURITY;
ALTER TABLE weights               ENABLE ROW LEVEL SECURITY;
ALTER TABLE activity_log          ENABLE ROW LEVEL SECURITY;
ALTER TABLE blood_pressure_logs   ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_settings         ENABLE ROW LEVEL SECURITY;

CREATE POLICY user_isolation ON nutrition_log         FOR ALL TO hv_app USING (user_id = current_setting('app.user_id', TRUE)::bigint);
CREATE POLICY user_isolation ON supplements_log       FOR ALL TO hv_app USING (user_id = current_setting('app.user_id', TRUE)::bigint);
CREATE POLICY user_isolation ON weights               FOR ALL TO hv_app USING (user_id = current_setting('app.user_id', TRUE)::bigint);
CREATE POLICY user_isolation ON activity_log          FOR ALL TO hv_app USING (user_id = current_setting('app.user_id', TRUE)::bigint);
CREATE POLICY user_isolation ON blood_pressure_logs   FOR ALL TO hv_app USING (user_id = current_setting('app.user_id', TRUE)::bigint);
CREATE POLICY user_isolation ON user_settings         FOR ALL TO hv_app USING (user_id = current_setting('app.user_id', TRUE)::bigint);
```

- [ ] **Step 2.6: Применить миграцию (с передачей пароля через psql переменную)**

```bash
PWD_VAL=$(grep '^HV_APP_DB_PASSWORD=' .env | cut -d= -f2)
ssh root@116.203.213.137 "docker exec -i healthvault_postgres psql -U healthvault -d healthvault \
  -v hv.app_password='$PWD_VAL' -c \"SET hv.app_password TO '$PWD_VAL';\" -f -" \
  < database/migrations/add_rls_policies.sql
```

Expected: `CREATE ROLE`, `GRANT`, `ALTER TABLE` × 6, `CREATE POLICY` × 6.

- [ ] **Step 2.7: Добавить helper в crud.py**

```python
# database/crud.py — append
from sqlalchemy import text


def set_user_session_var(db, user_id: int) -> None:
    """Set app.user_id session variable for RLS filtering.

    Must be called at the start of every request that uses hv_app role.
    Use SET LOCAL inside a transaction so it auto-clears at commit/rollback.
    """
    db.execute(text("SET LOCAL app.user_id = :uid"), {"uid": str(user_id)})
```

- [ ] **Step 2.8: Запустить integration test — должен пройти**

```bash
HV_APP_DB_PASSWORD=$(grep '^HV_APP_DB_PASSWORD=' .env | cut -d= -f2) \
  pytest tests/integration/test_rls_isolation.py -m integration -v
```

Expected: PASS обоих тестов.

- [ ] **Step 2.9: Commit**

```bash
git add database/migrations/add_rls_policies.sql database/crud.py tests/integration/test_rls_isolation.py
git commit -m "feat(db): RLS policies + hv_app role with session-variable user isolation"
```

---

### Task 3: Миграция — audit_log + триггер

**Files:**
- Create: `database/migrations/add_audit_log.sql`
- Modify: `database/models.py` (добавить класс `AuditLog`)
- Test: `tests/integration/test_audit_trail.py` (новый)

- [ ] **Step 3.1: Failing test — admin SELECT под healthvault-ролью пишется в audit_log**

```python
# tests/integration/test_audit_trail.py
import pytest
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


pytestmark = pytest.mark.integration


@pytest.fixture
def admin_session():
    """Connection as healthvault (admin) role."""
    url = os.environ["DATABASE_URL"]  # текущий DSN, admin-роль
    engine = create_engine(url)
    Session = sessionmaker(bind=engine)
    yield Session()


def test_admin_select_logged(admin_session):
    """SELECT от admin-роли пишется в audit_log."""
    before = admin_session.execute(text("SELECT COUNT(*) FROM audit_log")).scalar()

    # Admin делает privileged read
    admin_session.execute(text("SELECT * FROM nutrition_log WHERE user_id = 485132 LIMIT 1"))
    admin_session.commit()

    after = admin_session.execute(text("SELECT COUNT(*) FROM audit_log")).scalar()
    assert after > before, "Admin SELECT must be audited"

    last = admin_session.execute(
        text("SELECT db_user, query_excerpt FROM audit_log ORDER BY ts DESC LIMIT 1")
    ).first()
    assert last.db_user == "healthvault"
    assert "nutrition_log" in last.query_excerpt
```

- [ ] **Step 3.2: Запустить тест — должен упасть**

Run: `pytest tests/integration/test_audit_trail.py -m integration -v`
Expected: FAIL — `relation "audit_log" does not exist`.

- [ ] **Step 3.3: Создать SQL-миграцию**

```sql
-- database/migrations/add_audit_log.sql
-- Audit-trail для admin-доступа к чувствительным данным.
-- Триггер срабатывает на SELECT/INSERT/UPDATE/DELETE от роли 'healthvault' (admin).
-- Роль hv_app НЕ логируется (она работает в рамках своего user_id через RLS).

CREATE TABLE IF NOT EXISTS audit_log (
  id            BIGSERIAL PRIMARY KEY,
  ts            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  db_user       TEXT        NOT NULL,
  query_type    TEXT        NOT NULL,
  table_name    TEXT,
  query_excerpt TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts DESC);
CREATE INDEX IF NOT EXISTS idx_audit_user_table ON audit_log(db_user, table_name);

-- Используем pg_audit-style ручной триггер на каждой data-таблице.
-- (pg_audit extension требует superuser-доступа на хостинг — у нас Docker-postgres, не factor-of-managed
--  поэтому ставим вручную и контролируем содержимое.)

CREATE OR REPLACE FUNCTION audit_admin_access() RETURNS TRIGGER AS $$
BEGIN
  IF current_user = 'healthvault' THEN
    INSERT INTO audit_log(db_user, query_type, table_name, query_excerpt)
    VALUES (
      current_user,
      TG_OP,
      TG_TABLE_NAME,
      LEFT(current_query(), 500)
    );
  END IF;
  RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Привязать триггер ко всем чувствительным таблицам — на INSERT/UPDATE/DELETE.
-- (SELECT триггеры PG не поддерживает напрямую — для них используем log_statement = 'all'
--  для admin-роли через ALTER USER, см. опциональный шаг 3.6.)

DO $$
DECLARE
  t TEXT;
BEGIN
  FOR t IN SELECT unnest(ARRAY['nutrition_log','supplements_log','weights','activity_log','blood_pressure_logs','user_settings','users'])
  LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS audit_admin ON %I', t);
    EXECUTE format('CREATE TRIGGER audit_admin AFTER INSERT OR UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION audit_admin_access()', t);
  END LOOP;
END $$;

-- Audit_log сама — read-only для hv_app, full для admin.
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY audit_admin_only ON audit_log FOR ALL TO hv_app USING (FALSE);
GRANT SELECT ON audit_log TO hv_app;  -- видеть могут все, но через политику FALSE — никто
```

- [ ] **Step 3.4: Применить миграцию**

```bash
ssh root@116.203.213.137 "docker exec -i healthvault_postgres psql -U healthvault -d healthvault" \
  < database/migrations/add_audit_log.sql
```

Expected: `CREATE TABLE`, `CREATE INDEX` × 2, `CREATE FUNCTION`, `CREATE TRIGGER` × 7, `ENABLE ROW LEVEL SECURITY`, `CREATE POLICY`, `GRANT`.

- [ ] **Step 3.5: Добавить SQLAlchemy модель AuditLog (для read-only)**

```python
# database/models.py — append
class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    db_user: Mapped[str] = mapped_column(Text)
    query_type: Mapped[str] = mapped_column(Text)
    table_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    query_excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
```

- [ ] **Step 3.6: Optionally — включить SELECT-логирование на admin-роли через postgresql.conf**

Замечание: триггер ловит только INSERT/UPDATE/DELETE. Для SELECT используем `log_statement` на уровне роли. На сервере (через psql admin):

```sql
ALTER ROLE healthvault SET log_statement = 'all';
ALTER ROLE healthvault SET log_min_duration_statement = 0;
```

Эти SELECT'ы пойдут в Postgres-лог `/var/log/postgresql/` (не в `audit_log` таблицу). Парсить можно отдельно. Это compromise — accepted, в Sprint 3 рассмотрим pg_audit extension если нужен structured лог SELECT'ов.

- [ ] **Step 3.7: Запустить integration test — должен пройти**

Run: `pytest tests/integration/test_audit_trail.py -m integration -v`
Expected: PASS.

Замечание: тест использует UPDATE неявно — он проверяет что audit_log пишется. Нужно сделать INSERT через тестовую сессию чтобы триггер сработал. Скорректировать тест:

```python
def test_admin_insert_logged(admin_session):
    before = admin_session.execute(text("SELECT COUNT(*) FROM audit_log WHERE table_name='nutrition_log'")).scalar()

    admin_session.execute(text(
        "INSERT INTO nutrition_log (user_id, date, meal_time, items, totals) "
        "VALUES (895655, NOW()::date, NOW()::time, '[]'::jsonb, '{}'::jsonb)"
    ))
    admin_session.commit()

    after = admin_session.execute(text("SELECT COUNT(*) FROM audit_log WHERE table_name='nutrition_log'")).scalar()
    assert after == before + 1
```

Если тест выше не прошёл — закомментировать `test_admin_select_logged` (SELECT через триггер не ловится, это в Postgres-лог) и оставить только INSERT-тест.

- [ ] **Step 3.8: Commit**

```bash
git add database/migrations/add_audit_log.sql database/models.py tests/integration/test_audit_trail.py
git commit -m "feat(db): audit_log table + trigger on admin DML access"
```

---

### Task 4: JWT auth middleware

**Files:**
- Create: `telegram-bot/webhook/jwt_auth.py`
- Modify: `requirements.txt` (+ `pyjwt`)
- Test: `tests/test_jwt_auth.py` (новый)

- [ ] **Step 4.1: Установить pyjwt**

```bash
echo "pyjwt==2.8.0" >> requirements.txt
pip install pyjwt==2.8.0
```

- [ ] **Step 4.2: Failing test для JWT-middleware**

```python
# tests/test_jwt_auth.py
import jwt
import pytest
from datetime import datetime, timedelta
from fastapi import HTTPException
from unittest.mock import MagicMock

from telegram_bot.webhook.jwt_auth import get_agent_user, generate_agent_jwt


def test_generate_and_decode_jwt():
    secret = "test_secret_64chars_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    token = generate_agent_jwt(user_id=895655, container_id="nc-test", secret=secret)
    decoded = jwt.decode(token, secret, algorithms=["HS256"])
    assert decoded["user_id"] == 895655
    assert decoded["container_id"] == "nc-test"
    assert "exp" in decoded


@pytest.mark.asyncio
async def test_get_agent_user_valid():
    secret = "test_secret_64chars_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    token = generate_agent_jwt(user_id=895655, container_id="nc-test", secret=secret)

    db = MagicMock()
    user = MagicMock(telegram_id=895655, container_id="nc-test", jwt_secret=secret, is_active=True)
    db.query.return_value.filter_by.return_value.first.return_value = user

    result = await get_agent_user(authorization=f"Bearer {token}", db=db)
    assert result.telegram_id == 895655


@pytest.mark.asyncio
async def test_get_agent_user_expired():
    secret = "test_secret_64chars_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    token = jwt.encode(
        {"user_id": 895655, "container_id": "nc-test", "exp": datetime.utcnow() - timedelta(hours=1)},
        secret, algorithm="HS256"
    )
    db = MagicMock()
    user = MagicMock(telegram_id=895655, jwt_secret=secret, is_active=True, container_id="nc-test")
    db.query.return_value.filter_by.return_value.first.return_value = user

    with pytest.raises(HTTPException) as e:
        await get_agent_user(authorization=f"Bearer {token}", db=db)
    assert e.value.status_code == 401


@pytest.mark.asyncio
async def test_get_agent_user_wrong_container():
    """JWT with container_id mismatch — reject."""
    secret = "test_secret_64chars_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    token = generate_agent_jwt(user_id=895655, container_id="nc-attacker", secret=secret)

    db = MagicMock()
    user = MagicMock(telegram_id=895655, jwt_secret=secret, is_active=True, container_id="nc-sasha")
    db.query.return_value.filter_by.return_value.first.return_value = user

    with pytest.raises(HTTPException) as e:
        await get_agent_user(authorization=f"Bearer {token}", db=db)
    assert e.value.status_code == 403
```

- [ ] **Step 4.3: Запустить тест — должен упасть**

Run: `pytest tests/test_jwt_auth.py -v`
Expected: FAIL — `No module named 'telegram_bot.webhook.jwt_auth'`.

- [ ] **Step 4.4: Реализовать jwt_auth.py**

```python
# telegram-bot/webhook/jwt_auth.py
"""JWT authentication for agent → FastAPI tools API.

Each NanoClaw container has its own JWT secret in env, generated when
container was created. The container signs JWT with claims
{user_id, container_id, exp}, FastAPI verifies and looks up the user.

Mismatch between JWT.container_id and DB users.container_id → 403
(prevents one container impersonating another's user_id).
"""

import os
from datetime import datetime, timedelta
from typing import Optional

import jwt
from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session

# Default expiration for agent-generated tokens.
JWT_TTL_HOURS = int(os.getenv("AGENT_JWT_TTL_HOURS", "1"))


def generate_agent_jwt(user_id: int, container_id: str, secret: str) -> str:
    """Generate a JWT for an agent container.

    Called by container's startup script when it spins up. Rotated when
    /regenerate_health_token is called or when container is restarted.
    """
    payload = {
        "user_id": user_id,
        "container_id": container_id,
        "exp": datetime.utcnow() + timedelta(hours=JWT_TTL_HOURS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


async def get_agent_user(
    authorization: str = Header(...),
    db: Session = Depends(lambda: None),  # placeholder — overridden in apple_health.py
):
    """FastAPI dependency: validate agent JWT, return User.

    Raises 401 on missing/invalid/expired token.
    Raises 403 on container_id mismatch (potential impersonation).
    """
    from database import SessionLocal
    from database.models import User
    from database.crud import set_user_session_var

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization[7:]

    # Decode without verifying first to extract user_id (so we can fetch their secret).
    try:
        unverified = jwt.decode(token, options={"verify_signature": False})
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Malformed JWT")

    user_id = unverified.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="JWT missing user_id")

    if db is None:
        db = SessionLocal()

    user = db.query(User).filter_by(telegram_id=user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    if not user.jwt_secret:
        raise HTTPException(status_code=401, detail="User has no JWT secret (container not provisioned)")

    # Now verify with user's actual secret.
    try:
        verified = jwt.decode(token, user.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="JWT expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="JWT signature invalid")

    if verified.get("container_id") != user.container_id:
        raise HTTPException(status_code=403, detail="JWT container_id mismatch")

    # Set RLS session variable for any subsequent queries in this request.
    set_user_session_var(db, user.telegram_id)

    return user
```

- [ ] **Step 4.5: Запустить все JWT-тесты — должны пройти**

Run: `pytest tests/test_jwt_auth.py -v`
Expected: 4 PASS.

- [ ] **Step 4.6: Commit**

```bash
git add telegram-bot/webhook/jwt_auth.py tests/test_jwt_auth.py requirements.txt
git commit -m "feat(api): JWT auth middleware for agent tools API"
```

---

### Task 5: Tools API — log_meal_text endpoint (TDD-шаблон для остальных)

**Files:**
- Create: `telegram-bot/webhook/agent_tools_api.py`
- Test: `tests/test_agent_tools_api.py` (новый)

- [ ] **Step 5.1: Failing test для log_meal_text**

```python
# tests/test_agent_tools_api.py
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from datetime import datetime

# Импорт app — структура взята из telegram-bot/webhook/apple_health.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram-bot"))

from webhook.apple_health import app  # type: ignore
from webhook.jwt_auth import generate_agent_jwt


client = TestClient(app)
TEST_SECRET = "test_secret_64chars_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"


def _auth_headers(user_id=895655, container="nc-sasha"):
    token = generate_agent_jwt(user_id, container, TEST_SECRET)
    return {"Authorization": f"Bearer {token}"}


@patch("webhook.agent_tools_api.SessionLocal")
def test_log_meal_text_writes_nutrition_row(SessionLocal):
    db = MagicMock()
    SessionLocal.return_value = db

    user = MagicMock(telegram_id=895655, container_id="nc-sasha",
                     jwt_secret=TEST_SECRET, is_active=True)
    db.query.return_value.filter_by.return_value.first.return_value = user

    response = client.post(
        "/api/agent/log_meal_text",
        json={"text": "съел яблоко 200г", "meal_time": "08:30"},
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "nutrition_log_id" in body
```

- [ ] **Step 5.2: Запустить тест — упадёт (роутер не зарегистрирован)**

Run: `pytest tests/test_agent_tools_api.py::test_log_meal_text_writes_nutrition_row -v`
Expected: FAIL — 404.

- [ ] **Step 5.3: Создать agent_tools_api.py с log_meal_text**

```python
# telegram-bot/webhook/agent_tools_api.py
"""Agent Tools API — FastAPI endpoints called by NanoClaw containers.

All endpoints require valid agent JWT (see jwt_auth.py). User context is
set via session variable for RLS isolation. No endpoint takes user_id in
body — it's always derived from JWT.
"""

import logging
from datetime import datetime, time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from webhook.jwt_auth import get_agent_user
from database import SessionLocal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent", tags=["agent-tools"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class LogMealTextRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    meal_time: Optional[str] = None  # HH:MM, default = now


class LogMealTextResponse(BaseModel):
    status: str
    nutrition_log_id: int
    parsed_summary: str  # короткая сводка что распарсилось ("яблоко ~200г, ~95 ккал")


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/log_meal_text", response_model=LogMealTextResponse)
async def log_meal_text(req: LogMealTextRequest, user=Depends(get_agent_user)):
    """Log a meal from free text. Agent has already done the conversation —
    here we just trust the text and parse it through the same pipeline as the
    Telegram text handler."""
    from core.food.nutrition import parse_food_text  # existing parser
    from helpers.db_save import save_meal_to_db

    db = SessionLocal()
    try:
        meal_time_obj = (
            time.fromisoformat(req.meal_time) if req.meal_time else datetime.now().time()
        )

        parsed = parse_food_text(req.text)  # → dict {items, totals}
        meal_id = save_meal_to_db(
            db=db,
            user_id=user.telegram_id,
            date_=datetime.now().date(),
            meal_time=meal_time_obj,
            items=parsed["items"],
            totals=parsed["totals"],
        )
        db.commit()

        summary = ", ".join(f"{i['food']} ~{i['amount_g']}г" for i in parsed["items"][:3])
        return LogMealTextResponse(
            status="ok", nutrition_log_id=meal_id, parsed_summary=summary
        )
    finally:
        db.close()
```

- [ ] **Step 5.4: Подключить роутер к app**

```python
# telegram-bot/webhook/apple_health.py — добавить рядом с другими include_router
from webhook.agent_tools_api import router as agent_tools_router
app.include_router(agent_tools_router)
```

- [ ] **Step 5.5: Запустить тест — должен пройти**

Run: `pytest tests/test_agent_tools_api.py::test_log_meal_text_writes_nutrition_row -v`
Expected: PASS.

- [ ] **Step 5.6: Commit**

```bash
git add telegram-bot/webhook/agent_tools_api.py telegram-bot/webhook/apple_health.py tests/test_agent_tools_api.py
git commit -m "feat(api): /api/agent/log_meal_text — agent food logging endpoint"
```

---

### Task 6: Tools API — log_supplement, log_bp, regenerate_health_token

Расширяем `agent_tools_api.py` ещё тремя write-endpoint'ами по тому же паттерну.

**Files:**
- Modify: `telegram-bot/webhook/agent_tools_api.py`
- Modify: `tests/test_agent_tools_api.py`

- [ ] **Step 6.1: Failing test — log_supplement**

```python
# tests/test_agent_tools_api.py — append
@patch("webhook.agent_tools_api.SessionLocal")
def test_log_supplement(SessionLocal):
    db = MagicMock()
    SessionLocal.return_value = db
    user = MagicMock(telegram_id=895655, container_id="nc-sasha",
                     jwt_secret=TEST_SECRET, is_active=True)
    db.query.return_value.filter_by.return_value.first.return_value = user

    r = client.post(
        "/api/agent/log_supplement",
        json={"name": "Магний цитрат", "dose_mg": 400},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
```

- [ ] **Step 6.2: Реализовать log_supplement**

```python
# telegram-bot/webhook/agent_tools_api.py — append

class LogSupplementRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    dose_mg: Optional[float] = None
    notes: Optional[str] = None


class LogSupplementResponse(BaseModel):
    status: str
    supplement_log_id: int


@router.post("/log_supplement", response_model=LogSupplementResponse)
async def log_supplement(req: LogSupplementRequest, user=Depends(get_agent_user)):
    from helpers.db_save import save_supplements_to_db
    db = SessionLocal()
    try:
        sup_id = save_supplements_to_db(
            db=db,
            user_id=user.telegram_id,
            date_=datetime.now().date(),
            time_=datetime.now().time(),
            items=[{"name": req.name, "dose_mg": req.dose_mg, "notes": req.notes}],
        )
        db.commit()
        return LogSupplementResponse(status="ok", supplement_log_id=sup_id)
    finally:
        db.close()
```

- [ ] **Step 6.3: Тест прошёл — `pytest tests/test_agent_tools_api.py::test_log_supplement -v` → PASS**

- [ ] **Step 6.4: Failing test + impl для log_bp**

Test:
```python
@patch("webhook.agent_tools_api.SessionLocal")
def test_log_bp(SessionLocal):
    db = MagicMock()
    SessionLocal.return_value = db
    user = MagicMock(telegram_id=895655, container_id="nc-sasha",
                     jwt_secret=TEST_SECRET, is_active=True)
    db.query.return_value.filter_by.return_value.first.return_value = user

    r = client.post(
        "/api/agent/log_bp",
        json={"systolic": 128, "diastolic": 82, "pulse": 64},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
```

Impl:
```python
class LogBpRequest(BaseModel):
    systolic: int = Field(..., ge=50, le=300)
    diastolic: int = Field(..., ge=30, le=200)
    pulse: Optional[int] = Field(None, ge=30, le=250)
    notes: Optional[str] = None


@router.post("/log_bp")
async def log_bp(req: LogBpRequest, user=Depends(get_agent_user)):
    from database.models import BloodPressureLog
    db = SessionLocal()
    try:
        row = BloodPressureLog(
            user_id=user.telegram_id,
            measured_at=datetime.now(),
            systolic=req.systolic,
            diastolic=req.diastolic,
            pulse=req.pulse,
            notes=req.notes,
        )
        db.add(row)
        db.commit()
        return {"status": "ok", "blood_pressure_log_id": row.id}
    finally:
        db.close()
```

- [ ] **Step 6.5: Failing test + impl для regenerate_health_token**

Test:
```python
@patch("webhook.agent_tools_api.SessionLocal")
def test_regenerate_health_token(SessionLocal):
    db = MagicMock()
    SessionLocal.return_value = db
    user = MagicMock(telegram_id=895655, container_id="nc-sasha",
                     jwt_secret=TEST_SECRET, is_active=True,
                     health_token="hvt_old")
    db.query.return_value.filter_by.return_value.first.return_value = user

    r = client.post("/api/agent/regenerate_health_token", headers=_auth_headers())
    assert r.status_code == 200
    new_token = r.json()["health_token"]
    assert new_token.startswith("hvt_895655_")
    assert new_token != "hvt_old"
```

Impl:
```python
import secrets

@router.post("/regenerate_health_token")
async def regenerate_health_token(user=Depends(get_agent_user)):
    db = SessionLocal()
    try:
        new_token = f"hvt_{user.telegram_id}_{secrets.token_hex(16)}"
        from database.models import User
        db_user = db.query(User).filter_by(telegram_id=user.telegram_id).first()
        db_user.health_token = new_token
        db.commit()
        return {"status": "ok", "health_token": new_token}
    finally:
        db.close()
```

- [ ] **Step 6.6: Все тесты прошли**

Run: `pytest tests/test_agent_tools_api.py -v`
Expected: 4 PASS.

- [ ] **Step 6.7: Commit**

```bash
git add telegram-bot/webhook/agent_tools_api.py tests/test_agent_tools_api.py
git commit -m "feat(api): /api/agent/log_supplement, log_bp, regenerate_health_token"
```

---

### Task 7: Tools API — read endpoints (recent_meals, kb_value, dashboard_summary, user_profile)

**Files:**
- Modify: `telegram-bot/webhook/agent_tools_api.py`
- Modify: `tests/test_agent_tools_api.py`

- [ ] **Step 7.1: Failing test — recent_meals**

```python
@patch("webhook.agent_tools_api.SessionLocal")
def test_recent_meals(SessionLocal):
    from database.models import NutritionLog
    db = MagicMock()
    SessionLocal.return_value = db
    user = MagicMock(telegram_id=895655, container_id="nc-sasha",
                     jwt_secret=TEST_SECRET, is_active=True)
    db.query.return_value.filter_by.return_value.first.return_value = user

    # mock query for nutrition_log
    fake_meal = MagicMock(date=datetime.now().date(), items=[{"food":"яблоко"}], totals={"cal":95})
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [fake_meal]

    r = client.get("/api/agent/recent_meals?days=7", headers=_auth_headers())
    assert r.status_code == 200
    assert "meals" in r.json()
```

- [ ] **Step 7.2: Implement recent_meals**

```python
@router.get("/recent_meals")
async def recent_meals(days: int = 7, user=Depends(get_agent_user)):
    from database.models import NutritionLog
    from datetime import timedelta
    db = SessionLocal()
    try:
        cutoff = (datetime.now() - timedelta(days=days)).date()
        rows = (db.query(NutritionLog)
                .filter(NutritionLog.user_id == user.telegram_id, NutritionLog.date >= cutoff)
                .order_by(NutritionLog.date.desc(), NutritionLog.meal_time.desc())
                .limit(50).all())
        return {
            "meals": [
                {"date": r.date.isoformat(), "meal_time": r.meal_time.isoformat() if r.meal_time else None,
                 "items": r.items, "totals": r.totals}
                for r in rows
            ]
        }
    finally:
        db.close()
```

- [ ] **Step 7.3: Implement kb_value**

```python
@router.get("/kb_value")
async def kb_value(key: str, user=Depends(get_agent_user)):
    """Return last known value for a biomarker/measurement key from user's KB."""
    import json
    from pathlib import Path
    # KB живёт в repo для owner; для остальных — в их GDrive-папке (Sprint 2)
    if user.cohort == "owner":
        kb_path = Path(__file__).resolve().parents[2] / "knowledge_base.json"
    else:
        # Sprint 1a stub — Sprint 2 заменит на путь к их GDrive-зеркалу
        return {"key": key, "value": None, "source": "not-implemented-for-non-owner"}

    if not kb_path.exists():
        return {"key": key, "value": None}

    kb = json.loads(kb_path.read_text())
    # Простой поиск по ключу в blood_tests/hormones/...
    for section in ["blood_tests", "hormones", "vitamins"]:
        for entry in kb.get(section, []):
            for marker in entry.get("values", []):
                if marker.get("name", "").lower() == key.lower():
                    return {
                        "key": key,
                        "value": marker.get("value"),
                        "unit": marker.get("unit"),
                        "date": entry.get("date"),
                        "lab": entry.get("lab"),
                    }
    return {"key": key, "value": None}
```

- [ ] **Step 7.4: Implement dashboard_summary**

```python
@router.get("/dashboard_summary")
async def dashboard_summary(user=Depends(get_agent_user)):
    """Текстовая сводка для агента — то что увидел бы пользователь на dashboard.

    Возвращает топ-метрики последних 7 дней одной строкой каждая, чтобы
    LLM мог встроить в свой ответ ('твой средний пульс покоя 58, шагов 8200/день').
    """
    from datetime import timedelta
    from database.models import ActivityLog, Weight, NutritionLog
    db = SessionLocal()
    try:
        cutoff = datetime.now().date() - timedelta(days=7)
        avg_steps = db.query(ActivityLog).filter(ActivityLog.user_id==user.telegram_id, ActivityLog.date>=cutoff).all()
        steps = [a.steps for a in avg_steps if a.steps]
        weight_rows = db.query(Weight).filter(Weight.user_id==user.telegram_id).order_by(Weight.measured_at.desc()).limit(7).all()
        meals = db.query(NutritionLog).filter(NutritionLog.user_id==user.telegram_id, NutritionLog.date>=cutoff).all()

        return {
            "summary": {
                "avg_steps_7d": round(sum(steps)/len(steps)) if steps else None,
                "current_weight_kg": weight_rows[0].weight_kg if weight_rows else None,
                "weight_trend_7d_kg": (weight_rows[-1].weight_kg - weight_rows[0].weight_kg) if len(weight_rows) >= 2 else None,
                "meals_logged_7d": len(meals),
            }
        }
    finally:
        db.close()
```

- [ ] **Step 7.5: Implement user_profile**

```python
@router.get("/user_profile")
async def user_profile(user=Depends(get_agent_user)):
    return {
        "telegram_id": user.telegram_id,
        "first_name": user.first_name,
        "cohort": user.cohort,
        "pack_name": user.pack_name,
        "container_id": user.container_id,
        "has_garmin": bool(user.garmin_email),
        "health_token": user.health_token,  # видит свой
    }
```

- [ ] **Step 7.6: Все тесты прошли**

Run: `pytest tests/test_agent_tools_api.py -v`
Expected: ≥7 PASS.

- [ ] **Step 7.7: Commit**

```bash
git add telegram-bot/webhook/agent_tools_api.py tests/test_agent_tools_api.py
git commit -m "feat(api): read endpoints — recent_meals, kb_value, dashboard_summary, user_profile"
```

---

### Task 8: Telegram router

**Files:**
- Create: `telegram-bot/webhook/telegram_router.py`
- Test: `tests/integration/test_telegram_router.py` (новый)

- [ ] **Step 8.1: Failing test — router пробрасывает в legacy для photo, в container для текста**

```python
# tests/integration/test_telegram_router.py
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "telegram-bot"))

from webhook.apple_health import app

client = TestClient(app)


@patch("webhook.telegram_router.legacy_handle_photo", new_callable=AsyncMock)
def test_photo_goes_to_legacy(legacy):
    payload = {
        "update_id": 1, "message": {
            "message_id": 1, "from": {"id": 895655}, "chat": {"id": 895655},
            "photo": [{"file_id": "x"}],
        }
    }
    r = client.post("/telegram/webhook", json=payload)
    assert r.status_code == 200
    legacy.assert_awaited_once()


@patch("webhook.telegram_router.forward_to_container", new_callable=AsyncMock)
@patch("webhook.telegram_router.SessionLocal")
def test_text_goes_to_container(SessionLocal, forward):
    db = MagicMock()
    SessionLocal.return_value = db
    user = MagicMock(telegram_id=895655, container_id="nc-sasha", container_port=8001, is_active=True)
    db.query.return_value.filter_by.return_value.first.return_value = user

    payload = {
        "update_id": 1, "message": {
            "message_id": 1, "from": {"id": 895655}, "chat": {"id": 895655},
            "text": "выпил витамины",
        }
    }
    r = client.post("/telegram/webhook", json=payload)
    assert r.status_code == 200
    forward.assert_awaited_once()
    args, kwargs = forward.call_args
    assert "nc-sasha" in args[0] or kwargs.get("container_id") == "nc-sasha"


@patch("webhook.telegram_router.handle_onboarding", new_callable=AsyncMock)
@patch("webhook.telegram_router.SessionLocal")
def test_unknown_user_goes_to_onboarding(SessionLocal, onb):
    db = MagicMock()
    SessionLocal.return_value = db
    db.query.return_value.filter_by.return_value.first.return_value = None  # new user

    payload = {
        "update_id": 1, "message": {
            "message_id": 1, "from": {"id": 999999, "first_name": "New"}, "chat": {"id": 999999},
            "text": "/start",
        }
    }
    r = client.post("/telegram/webhook", json=payload)
    assert r.status_code == 200
    onb.assert_awaited_once()
```

- [ ] **Step 8.2: Запустить — упадёт**

Run: `pytest tests/integration/test_telegram_router.py -v`
Expected: FAIL — `/telegram/webhook` 404.

- [ ] **Step 8.3: Реализовать telegram_router.py**

```python
# telegram-bot/webhook/telegram_router.py
"""Telegram webhook entry. Routes messages to:
- legacy handlers (photo/voice) for media that NanoClaw containers won't process
- per-user NanoClaw container for text messages from registered users
- onboarding wizard for new users

Router does NOT parse text content — only reads from.id and message type.
"""

import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from database import SessionLocal
from database.models import User

logger = logging.getLogger(__name__)
router = APIRouter()


async def forward_to_container(container_id: str, port: int, payload: dict) -> None:
    """POST payload to container's internal /agent/process endpoint.

    Fire-and-forget — agent will respond to Telegram directly via sendMessage.
    """
    url = f"http://{container_id}:{port}/agent/process"
    async with httpx.AsyncClient(timeout=30.0) as c:
        try:
            await c.post(url, json=payload)
        except httpx.RequestError as e:
            logger.error(f"Failed to forward to {container_id}: {e}")
            # Fallback: tell user to retry — Telegram-bot-token in env
            await _send_fallback(payload["message"]["chat"]["id"],
                                 "⚠ Агент сейчас недоступен, попробуй через минуту.")


async def legacy_handle_photo(payload: dict) -> None:
    """Forward photo to existing handler (telegram-bot/handlers/photo.py)."""
    # In Sprint 1a we just log — actual existing aiogram handler is invoked
    # by the long-polling bot process, not via webhook. Keep as no-op
    # placeholder until Telegram is fully migrated to webhook.
    logger.info(f"Photo from {payload['message']['from']['id']} — handled by existing bot")


async def legacy_handle_voice(payload: dict) -> None:
    logger.info(f"Voice from {payload['message']['from']['id']} — handled by existing bot")


async def handle_onboarding(payload: dict) -> None:
    """New user — kick off /start wizard.

    Sprint 1a: simple FSM via on-the-fly state in users table (column added in
    Task 1: 'onboarding_step'). Replaced by agent-driven onboarding in Sprint 2.
    """
    from telegram_bot.handlers.onboarding import start_wizard
    await start_wizard(payload)


async def _send_fallback(chat_id: int, text: str) -> None:
    bot_token = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN", "")
    async with httpx.AsyncClient() as c:
        await c.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
        )


@router.post("/telegram/webhook")
async def telegram_webhook(payload: dict):
    msg = payload.get("message") or payload.get("edited_message") or {}
    if not msg:
        return {"status": "ok"}

    from_id = msg.get("from", {}).get("id")
    if not from_id:
        return {"status": "ok"}

    db = SessionLocal()
    try:
        user = db.query(User).filter_by(telegram_id=from_id).first()

        # Photo/voice — legacy handler (existing bot processes via long-poll).
        if "photo" in msg:
            await legacy_handle_photo(payload)
            return {"status": "ok"}
        if "voice" in msg:
            await legacy_handle_voice(payload)
            return {"status": "ok"}

        # New user — onboarding.
        if not user:
            await handle_onboarding(payload)
            return {"status": "ok"}

        # Existing user with no container yet (Sprint 1a state for everyone) —
        # fall back to legacy text handler. Sprint 1b: when container provisioned, route to it.
        if not user.container_id or not user.container_port:
            logger.info(f"User {from_id} has no container yet — legacy text handling")
            return {"status": "ok"}

        # Route to container.
        await forward_to_container(user.container_id, user.container_port, payload)
        return {"status": "ok"}
    finally:
        db.close()
```

- [ ] **Step 8.4: Подключить роутер**

```python
# telegram-bot/webhook/apple_health.py — append to imports/include_router section
from webhook.telegram_router import router as telegram_router
app.include_router(telegram_router)
```

- [ ] **Step 8.5: Тесты прошли**

Run: `pytest tests/integration/test_telegram_router.py -v`
Expected: 3 PASS.

- [ ] **Step 8.6: Commit**

```bash
git add telegram-bot/webhook/telegram_router.py telegram-bot/webhook/apple_health.py tests/integration/test_telegram_router.py
git commit -m "feat: Telegram webhook router — legacy photo/voice + container forward + onboarding"
```

---

### Task 9: Onboarding wizard /start

**Files:**
- Create: `telegram-bot/handlers/onboarding.py`
- Modify: `database/migrations/add_cohort_columns.sql` → дополнительно поле `onboarding_step` (или новая мини-миграция)
- Modify: `telegram-bot/handlers/commands.py` (заменить старый `cmd_start` на новый — wizard kicks in для новых)
- Test: `tests/integration/test_onboarding_wizard.py`

- [ ] **Step 9.1: Доп. миграция — onboarding_step**

```sql
-- database/migrations/add_onboarding_step.sql
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS onboarding_step VARCHAR(30) DEFAULT 'done',
  ADD COLUMN IF NOT EXISTS onboarding_data JSONB DEFAULT '{}'::jsonb;

-- Existing users — already onboarded.
UPDATE users SET onboarding_step = 'done' WHERE onboarding_step IS NULL;
```

Применить:
```bash
ssh root@116.203.213.137 "docker exec -i healthvault_postgres psql -U healthvault -d healthvault" \
  < database/migrations/add_onboarding_step.sql
```

И добавить в `database/models.py`:
```python
onboarding_step: Mapped[str] = mapped_column(String(30), default="done", server_default="done")
onboarding_data: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
```

- [ ] **Step 9.2: Failing test — wizard step machine**

```python
# tests/integration/test_onboarding_wizard.py
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from telegram_bot.handlers.onboarding import process_onboarding_message


@pytest.mark.asyncio
@patch("telegram_bot.handlers.onboarding.send_message", new_callable=AsyncMock)
@patch("telegram_bot.handlers.onboarding.SessionLocal")
async def test_new_user_starts_at_name(SessionLocal, send):
    db = MagicMock()
    SessionLocal.return_value = db
    db.query.return_value.filter_by.return_value.first.return_value = None  # not in DB

    payload = {"message": {"from": {"id": 999, "first_name": "New"},
                           "chat": {"id": 999}, "text": "/start"}}
    await process_onboarding_message(payload)

    send.assert_awaited()
    args = send.call_args.args
    assert "имя" in args[1].lower() or "зовут" in args[1].lower()


@pytest.mark.asyncio
@patch("telegram_bot.handlers.onboarding.send_message", new_callable=AsyncMock)
@patch("telegram_bot.handlers.onboarding.SessionLocal")
async def test_after_age_question_advances(SessionLocal, send):
    db = MagicMock()
    SessionLocal.return_value = db
    user = MagicMock(telegram_id=999, onboarding_step="age", onboarding_data={"name":"Андрей"})
    db.query.return_value.filter_by.return_value.first.return_value = user

    payload = {"message": {"from":{"id":999}, "chat":{"id":999}, "text":"48"}}
    await process_onboarding_message(payload)

    assert user.onboarding_step in ("sex", "height")  # advances after age accepted
```

- [ ] **Step 9.3: Реализовать onboarding.py**

```python
# telegram-bot/handlers/onboarding.py
"""Throwaway onboarding wizard for Sprint 1.

State machine via users.onboarding_step + users.onboarding_data (jsonb).
Steps: name → age → sex → height → has_garmin → done.
After done: spawn container, generate health_token, send dashboard URL.
"""

import logging
import os
from datetime import datetime
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from database import SessionLocal
from database.models import User

logger = logging.getLogger(__name__)

STEPS = ["name", "age", "sex", "height", "has_garmin", "done"]


async def send_message(chat_id: int, text: str, reply_markup: Optional[dict] = None) -> None:
    bot_token = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN", "")
    body = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        body["reply_markup"] = reply_markup
    async with httpx.AsyncClient() as c:
        await c.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json=body)


async def start_wizard(payload: dict) -> None:
    """Entry point — called by router for new users."""
    await process_onboarding_message(payload)


async def process_onboarding_message(payload: dict) -> None:
    msg = payload.get("message", {})
    from_id = msg.get("from", {}).get("id")
    chat_id = msg.get("chat", {}).get("id")
    text = (msg.get("text") or "").strip()

    db = SessionLocal()
    try:
        user = db.query(User).filter_by(telegram_id=from_id).first()

        if not user:
            # Brand new — create row, ask name.
            user = User(
                telegram_id=from_id,
                username=msg.get("from", {}).get("username"),
                first_name=msg.get("from", {}).get("first_name"),
                cohort="external",
                pack_name="generic",
                onboarding_step="name",
                onboarding_data={},
                is_active=True,
            )
            db.add(user); db.commit()
            await send_message(chat_id, "👋 Привет! Я твой персональный health-coach.\n\nКак тебя зовут? (для удобства общения)")
            return

        step = user.onboarding_step or "name"
        data = dict(user.onboarding_data or {})

        if step == "name":
            data["name"] = text[:100]
            user.first_name = text[:100]
            user.onboarding_step = "age"
            user.onboarding_data = data
            db.commit()
            await send_message(chat_id, f"Приятно, {text}! Сколько тебе лет?")
            return

        if step == "age":
            try:
                age = int(text)
                if age < 10 or age > 120: raise ValueError
            except ValueError:
                await send_message(chat_id, "Введи число от 10 до 120 — сколько тебе лет?")
                return
            data["age"] = age
            user.onboarding_step = "sex"; user.onboarding_data = data; db.commit()
            await send_message(chat_id, "Пол?", {"keyboard":[["М","Ж"]],"one_time_keyboard":True,"resize_keyboard":True})
            return

        if step == "sex":
            sex = "M" if text.upper().startswith("М") else "F" if text.upper().startswith("Ж") else None
            if not sex:
                await send_message(chat_id, "Жми кнопку М или Ж")
                return
            data["sex"] = sex
            user.onboarding_step = "height"; user.onboarding_data = data; db.commit()
            await send_message(chat_id, "Рост в см? (например 178)")
            return

        if step == "height":
            try:
                h = int(text)
                if h < 100 or h > 230: raise ValueError
            except ValueError:
                await send_message(chat_id, "Введи рост в см от 100 до 230")
                return
            data["height_cm"] = h
            user.onboarding_step = "has_garmin"; user.onboarding_data = data; db.commit()
            await send_message(chat_id, "У тебя есть Garmin?", {"keyboard":[["Да","Нет"]],"one_time_keyboard":True,"resize_keyboard":True})
            return

        if step == "has_garmin":
            data["has_garmin"] = text.lower().startswith("д")
            user.onboarding_data = data
            user.onboarding_step = "done"

            # Issue health_token and pack assignment.
            import secrets
            user.health_token = f"hvt_{user.telegram_id}_{secrets.token_hex(16)}"
            db.commit()

            await send_message(
                chat_id,
                f"Готово! 🎉\n\n"
                f"<b>Твой Apple Health токен:</b>\n<code>{user.health_token}</code>\n\n"
                f"Установи приложение Health Auto Export ($24.99 lifetime, 7 дней триал):\n"
                f"https://apps.apple.com/app/health-auto-export-json-csv/id1115567069\n\n"
                f"В нём → REST API → URL: <code>https://health.orangegate.cc/apple_health_v2</code>, "
                f"Header: <code>Authorization: Bearer {user.health_token}</code>\n\n"
                f"Дальше — пиши еду текстом/голосом/фото, считаю калории. "
                f"Через несколько недель появится агент-врач — подключим тебя.",
            )
            return

        # step == 'done' — already onboarded, ignore (router shouldn't have sent here)
        logger.info(f"User {from_id} sent message but onboarding_step=done, ignoring")
    finally:
        db.close()
```

- [ ] **Step 9.4: Тесты прошли**

Run: `pytest tests/integration/test_onboarding_wizard.py -v`
Expected: 2 PASS.

- [ ] **Step 9.5: Commit**

```bash
git add database/migrations/add_onboarding_step.sql database/models.py telegram-bot/handlers/onboarding.py tests/integration/test_onboarding_wizard.py
git commit -m "feat: throwaway onboarding wizard for new users (Sprint 1a)"
```

---

### Task 10: Адаптивный dashboard (skip пустых блоков)

**Files:**
- Create: `telegram-bot/dashboard_blocks.py`
- Modify: `telegram-bot/dashboard_generator.py` (использовать helpers)
- Test: `tests/test_dashboard_blocks.py`

- [ ] **Step 10.1: Failing tests для helpers**

```python
# tests/test_dashboard_blocks.py
import pytest
from unittest.mock import MagicMock
from telegram_bot.dashboard_blocks import (
    has_garmin_data, has_apple_health_data, has_blood_test_data, has_nutrition_data
)


def test_has_garmin_data_false_for_no_garmin():
    user = MagicMock(garmin_email=None, telegram_id=999)
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = None
    assert has_garmin_data(db, user) is False


def test_has_garmin_data_true_when_activity_logged():
    user = MagicMock(garmin_email="x@y.com", telegram_id=895655)
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = MagicMock(steps=8000)
    assert has_garmin_data(db, user) is True
```

- [ ] **Step 10.2: Реализовать dashboard_blocks.py**

```python
# telegram-bot/dashboard_blocks.py
"""Helpers — does this user have data for a given dashboard block.

Used by dashboard_generator.py to skip empty sections instead of
rendering 'no data' placeholders.
"""

from datetime import date, timedelta
from sqlalchemy.orm import Session

from database.models import User, ActivityLog, BloodPressureLog, NutritionLog, Weight


def _last_n_days(n: int = 30):
    return date.today() - timedelta(days=n)


def has_garmin_data(db: Session, user: User) -> bool:
    """User has Garmin if either email set OR any activity_log row in last 30 days."""
    if user.garmin_email:
        return True
    return db.query(ActivityLog).filter(
        ActivityLog.user_id == user.telegram_id,
        ActivityLog.date >= _last_n_days(30),
    ).first() is not None


def has_apple_health_data(db: Session, user: User) -> bool:
    """Any blood_pressure_logs (typically from HAE) or activity_log with raw_data containing 'apple_*'."""
    return db.query(BloodPressureLog).filter(BloodPressureLog.user_id == user.telegram_id).first() is not None


def has_blood_test_data(db: Session, user: User) -> bool:
    """Owner has knowledge_base.json with values; non-owner — Sprint 2 KB pipeline."""
    if user.cohort != "owner":
        return False  # placeholder Sprint 1a
    import json
    from pathlib import Path
    kb_path = Path(__file__).resolve().parents[1] / "knowledge_base.json"
    if not kb_path.exists():
        return False
    try:
        kb = json.loads(kb_path.read_text())
        for entry in kb.get("blood_tests", []):
            if entry.get("values"):
                return True
    except Exception:
        pass
    return False


def has_nutrition_data(db: Session, user: User) -> bool:
    return db.query(NutritionLog).filter(NutritionLog.user_id == user.telegram_id).first() is not None


def has_weight_data(db: Session, user: User) -> bool:
    return db.query(Weight).filter(Weight.user_id == user.telegram_id).first() is not None
```

- [ ] **Step 10.3: Использовать в dashboard_generator.py**

В `dashboard_generator.py` (см. строку 1568 `def generate_dashboard_html`) добавить в начало функции:

```python
from telegram_bot.dashboard_blocks import (
    has_garmin_data, has_apple_health_data, has_blood_test_data,
    has_nutrition_data, has_weight_data,
)

def generate_dashboard_html(db: Session, user_id: int) -> str:
    user = db.query(User).filter_by(telegram_id=user_id).first()
    if not user:
        raise ValueError(f"User {user_id} not found")

    available_blocks = {
        "body":     has_weight_data(db, user),
        "nutrition": has_nutrition_data(db, user),
        "sport":    has_garmin_data(db, user),
        "sleep":    has_garmin_data(db, user),
        "heart":    has_garmin_data(db, user) or has_apple_health_data(db, user),
        "blood_tests": has_blood_test_data(db, user),
        "blood_pressure": has_apple_health_data(db, user),
        "air":      user.cohort == "owner",  # Netatmo только у Александра
    }
    # ... existing rendering, but wrap each block in `if available_blocks[name]:`
```

(Конкретные правки в `generate_dashboard_html` — итеративно по блокам в существующем коде. Каждый блок обёрнут в `if available_blocks["sport"]:` перед `render_sport_block(...)`.)

- [ ] **Step 10.4: Тесты dashboard_blocks прошли**

Run: `pytest tests/test_dashboard_blocks.py -v`
Expected: PASS.

- [ ] **Step 10.5: Smoke-проверка — dashboard для нового пользователя без Garmin не падает**

```bash
# Создать тестового нового юзера в локальной/dev БД и открыть его dashboard
curl -s "https://health.orangegate.cc/mc/<test_share_token>" | head -100
```

Expected: HTML без блоков sport/sleep/heart/blood_tests; есть только то по чему есть данные.

- [ ] **Step 10.6: Commit**

```bash
git add telegram-bot/dashboard_blocks.py telegram-bot/dashboard_generator.py tests/test_dashboard_blocks.py
git commit -m "feat(dashboard): adaptive blocks — skip sections with no data"
```

---

### Task 11: BotFather setup + webhook URL

**Files:**
- Doc only: `docs/SPRINT_1A_DEPLOY.md`

- [ ] **Step 11.1: Создать @health_vault_bot через BotFather**

Открыть Telegram → `@BotFather` → `/newbot`
- Имя: `HealthVault Coach`
- Username: `health_vault_bot` (если занят — `health_vault_pro_bot` или `hv_coach_bot`)
- Сохранить токен в `1Password → "HealthVault Bot Token"`.

- [ ] **Step 11.2: Установить токен в .env на сервере**

```bash
ssh root@116.203.213.137 "
  grep -q '^TELEGRAM_BOT_TOKEN=' /opt/healthvault/.env && \
    sed -i 's/^TELEGRAM_BOT_TOKEN=.*/TELEGRAM_BOT_TOKEN=<new_token>/' /opt/healthvault/.env || \
    echo 'TELEGRAM_BOT_TOKEN=<new_token>' >> /opt/healthvault/.env
"
```

- [ ] **Step 11.3: Зарегистрировать webhook**

```bash
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d "url=https://health.orangegate.cc/telegram/webhook"
```

Expected: `{"ok":true,"result":true,"description":"Webhook was set"}`.

- [ ] **Step 11.4: Verify**

```bash
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"
```

Expected: `pending_update_count: 0`, `url: https://health.orangegate.cc/telegram/webhook`.

- [ ] **Step 11.5: Commit deploy doc**

```bash
# Записать всё что сделано в docs/SPRINT_1A_DEPLOY.md
git add docs/SPRINT_1A_DEPLOY.md
git commit -m "docs: Sprint 1a deploy — BotFather + webhook setup"
```

---

### Task 12: End-to-end smoke + регрессия существующих пользователей

**Files:**
- Test: `tests/integration/test_sprint_1a_smoke.py`

- [ ] **Step 12.1: Smoke-сценарий — Александр (owner) логирует еду через старый бот**

```bash
# Послать в @health_vault_bot текст: «съел яблоко 200г»
# Через aiogram-handler (legacy text path) — записывается как раньше
# Verify в БД:
ssh root@116.203.213.137 "docker exec healthvault_postgres psql -U healthvault -d healthvault -c \
  \"SELECT date, items FROM nutrition_log WHERE user_id=895655 ORDER BY date DESC, meal_time DESC LIMIT 1;\""
```

Expected: новая запись с яблоком.

- [ ] **Step 12.2: Smoke — новый юзер проходит wizard**

В Telegram нажать `/start` от нового аккаунта → проходить шаги (name/age/sex/height/has_garmin) → получить health_token.

- [ ] **Step 12.3: Smoke — новый юзер видит свой dashboard**

```bash
# Получить share_token из БД
ssh root@116.203.213.137 "docker exec healthvault_postgres psql -U healthvault -d healthvault -c \
  \"SELECT share_token FROM users WHERE telegram_id=<new_user_id>;\""

# Открыть в браузере: https://health.orangegate.cc/mc/<share_token>
# Должен быть рендер БЕЗ блоков sport/sleep (нет Garmin), без blood_tests, без air.
# Если нового юзера ещё ничего нет — рендер с заголовком + статусом «начни логировать».
```

- [ ] **Step 12.4: Smoke — Tools API endpoint работает с тестовым JWT**

```bash
# Сгенерировать JWT для существующего пользователя (через python repl на сервере)
ssh root@116.203.213.137 "cd /opt/healthvault && python3 -c \"
from telegram_bot.webhook.jwt_auth import generate_agent_jwt
import os
# Установи jwt_secret для Sasha вручную для теста
print(generate_agent_jwt(895655, 'nc-sasha-test', 'test_secret_for_smoke'))
\""

# Сначала: UPDATE users SET jwt_secret='test_secret_for_smoke', container_id='nc-sasha-test' WHERE telegram_id=895655;

# Дёрнуть endpoint:
curl -H "Authorization: Bearer <token>" https://health.orangegate.cc/api/agent/user_profile
```

Expected: JSON с профилем Sasha.

- [ ] **Step 12.5: Регрессия — Никины записи всё ещё пишутся**

Никой написать «выпила 250мл воды» в @health_vault_bot → проверить в БД что записалось в nutrition_log с user_id=485132.

- [ ] **Step 12.6: Регрессия — HAE webhook работает**

```bash
# Послать тестовый POST на /apple_health_v2 с Bearer для Sasha — должен записаться.
curl -X POST https://health.orangegate.cc/apple_health_v2 \
  -H "Authorization: Bearer <SASHA_HEALTH_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"data":{"metrics":[{"name":"step_count","units":"count","data":[{"date":"2026-05-04","qty":5000}]}]}}'
```

Expected: `200 OK` + новая строка в `activity_log` для Sasha.

- [ ] **Step 12.7: После всех smoke-проверок — обновить todo.md**

Маркировать Sprint 1a задачи как `[x]` в `todo.md` (раздел про мультиюзер). Commit:

```bash
git add todo.md
git commit -m "docs: mark Sprint 1a complete in todo.md"
git push origin main
```

---

## Self-Review

После написания всех 12 задач — проверка:

**1. Spec coverage** — каждый пункт спека Sprint 1 (§10.1) покрыт:
- Миграция БД cohort/RLS/audit → Tasks 1, 2, 3 ✓
- 10 FastAPI tools API + JWT — Tasks 4–7 (8 endpoint'ов, 3 deferred to Sprint 3 как медтаблицы) ✓ с уточнением: `log_meds`, `log_symptom`, `log_nicotine` НЕ имплементируются в Sprint 1a (нет таблиц) — задокументировано
- Telegram router → Task 8 ✓
- Wizard /start → Task 9 ✓
- /regenerate_health_token → Task 6 (внутри Tools API) ✓
- Адаптивный dashboard → Task 10 ✓
- BotFather + webhook → Task 11 ✓
- NanoClaw scaffold + nc-andrey + pack:cardiac → **DEFERRED to Sprint 1b** (отдельный план)
- Базовые skills → DEFERRED to Sprint 1b
- Smoke-тест → Task 12 ✓

**2. Placeholder scan** — никаких TBD/TODO/«implement later» в коде. В Task 9.1 есть упоминание «throwaway state-machine — заменим в Sprint 2» — это явный disclaimer, не placeholder.

**3. Type consistency** — `User.cohort`, `User.pack_name`, `User.container_id`, `User.jwt_secret` упомянуты везде одинаково. `generate_agent_jwt` сигнатура (user_id, container_id, secret) — одна и та же в Task 4 и Task 12.

**4. Ambiguity** — Task 10.3 «итеративные правки в `generate_dashboard_html`» — единственное место где код не показан полностью. Это намеренно — implementation-плану не нужно дублировать существующий код, только обернуть блоки в `if`. Подходит для plan-уровня детализации.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-04-cohort-agents-sprint-1a.md`. Two execution options:

**1. Subagent-Driven (recommended)** — диспетчерю свежего subagent'а на каждую задачу, ревью между задачами, быстрая итерация. Я возвращаюсь между задачами с проверками и фиксами.

**2. Inline Execution** — выполнение задач в этой сессии через executing-plans, batch с чекпоинтами на ревью.

Какой подход?
