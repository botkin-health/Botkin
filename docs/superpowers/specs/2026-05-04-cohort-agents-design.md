# HealthVault Cohort Agents — Design Spec

**Дата:** 4 мая 2026
**Автор:** Claude (брейншторм с Александром)
**Статус:** черновик, ждёт ревью пользователя
**Фоновая сессия:** brainstorm `2026-05-04-cohort-agents` (`.superpowers/brainstorm/83136-1777905470/`)

## 1. Контекст

HealthVault сейчас — Telegram-бот на Python/aiogram с 3 активными пользователями (Александр, Ника, Андрей). Работает: парсинг еды по фото/голосу/тексту через Claude Vision/Whisper, логирование добавок, вес, дашборд (`/mc/{share_token}`), HAE-вебхук от Apple Watch, Garmin/Zepp/Netatmo синки, knowledge_base.json.

Архитектурно бот — это «парсер команд + handler-ы»: текст пользователя проходит через LLM только для извлечения структурированных данных (food → JSON), но никакого диалога, памяти, медицинского контекста и проактивности нет. SYSTEM_PROMPT глобальный, один на всех.

**Цель:** превратить HealthVault из персонального трекера в **cohort-платформу первых пользователей** (10+ к концу мая) с per-user медицинским контекстом, приватностью и проактивным AI-коучингом. Кейсы:
- **Андрей Походня** — POAF после 4-й фундопликации, ICM Reveal Linq, ожирение I, не принимает Метформин 4 месяца, никотиновая зависимость. Нужен агент-кардиолог с adherence-ремайндерами.
- **Элен** — женский цикл, гормоны (явный запрос). Нужен агент с пониманием цикла и его связи с весом/настроением/планами.
- **Александр** — поздний демпинг, фокус на вес. Текущий контекст.
- **Ника** — приватность: «не хочу шарить часть данных с Сашей, только с ИИ-агентом».
- **Дальше:** мама, дети, друзья (10+ к концу мая).

**Дедлайн:** 14 мая 2026 — Андрей получает Withings + Libre 2, к этому моменту у него должен быть рабочий персональный агент.

**Чего нельзя сломать:** существующих 3 пользователей, их данные, текущие потоки питания/HAE/dashboard.

## 2. Требования

### 2.1 Функциональные

- Multi-tenant платформа на 10+ пользователей одновременно с per-user медицинским контекстом.
- Self-serve онбординг: новый пользователь сам стартует через Telegram, без ручного деплоя.
- Каждый пользователь общается со своим AI-агентом, у которого: персональный doctor-prompt (medical history, диагнозы, лекарства, цели), приватная долговременная память, доступ к данным только этого пользователя.
- Privacy boundary: данные одного пользователя не доступны другому через приложение. Админ (Александр) может технически прочесть, но это **залогировано** в audit trail.
- Tools у агента: логирование еды/добавок/АД/симптомов/лекарств, query knowledge_base, получение dashboard summary, проактивные ремайндеры с inline-buttons.
- Существующие потоки (фото-парсер еды, HAE, dashboard) продолжают работать без изменений с точки зрения пользователя.

### 2.2 Нефункциональные

- Запас по производительности: ≥50 пользователей на одном Hetzner-сервере без вертикального скейла.
- Latency: ответ агента ≤5 сек p95 (LLM-вызов 1–3 сек + tool-calls).
- Доступность: ≥99% за месяц (без SLA-обязательств, but reasonable).
- Стоимость LLM: ≤$10/мес/пользователь при средней нагрузке (BYOK снимает нагрузку для тех кто сам платит).
- Все секреты (LLM-ключи, Telegram-токен, PG-пароли) — не в коде, не в логах, в env или зашифрованы в БД.

### 2.3 Out of scope (вне этого спека)

- MDT-консилиум (5–9 AI-специалистов + GP-синтезатор) — отдельный эпик после реализации этого спека.
- Полный rewrite на TypeScript — отвергнут (см. § 3, опция C).
- Mobile-приложение — Telegram + miniapp достаточно.
- Биллинг и платная подписка — обсуждалось в `todo.md`, не входит в Sprint 1–3.

## 3. Принятые архитектурные решения

| # | Решение | Альтернативы (отвергнуты) | Обоснование |
|---|---------|-------------------------|-------------|
| 1 | **Топология B (Сбалансированный):** агент в NanoClaw берёт диалог + doctor-prompt + memory + ремайндеры + текстовое логирование (meds, BP, симптомы); Python оставляет фото/голос/dashboard/HAE/KB-pipeline. ~30% переноса. | A (тонкий — агент только разговор, теряем agentic-action); C (толстый — 70% переноса, не успеваем к 14.05 и зря переписываем работающий dashboard и фото-парсер). | Sweet spot: агент действительно агентичен где это даёт ценность, но не переписываем работающее. |
| 2 | **Privacy B (RLS + audit log):** PG row-level security per-user-роль + триггер на admin SELECT/UPDATE. Sprint 3 → +column-level crypto для symptom/cycle/nicotine/private notes. | A (доверие только) — слабая граница, неприемлемо для Никиного запроса; C сразу (RLS+crypto) — 5 дней, Sprint 1 не успеваем; крипто на чувствительные поля можно добавить инкрементально поверх готового RLS. | Honest baseline: «могу, но залогировано» — это качественно другой разговор с пользователем, чем «обещаю». |
| 3 | **Один Telegram-бот** `@health_vault_bot` + тонкий Python-router. Router читает только `from.id`, форвардит payload в контейнер пользователя, не парсит текст. | Per-user боты (10 BotFather-токенов, ручной онбординг каждого, не масштабируется). | Self-serve онбординг новых пользователей. Privacy от router'а — добавочно, но для baseline B этого достаточно. |
| 4 | **Tools API: HTTP REST к существующему FastAPI.** Агент вызывает `POST /api/agent/log_supplement` и т.п. JWT-аутентификация. ~10 новых endpoint'ов. | Прямой Postgres из Node (β) — дублирует схему БД и валидацию между Python и Node, миграции ломают оба слоя; MCP server — overkill для inter-service на одном хосте. | Single source of truth по схеме БД (Python), переиспользование валидации, +50ms latency не критичен для chat-бота (LLM сам 1–3 сек). |

## 4. Архитектура

```
┌─────────────────────────────────┬──────────────────────────────────┐
│ Telegram (@health_vault_bot)    │ Apple Watch + HAE app            │
│ один токен, один webhook        │ POST /apple_health_v2 (Bearer)   │
└────────────┬────────────────────┴──────────────┬───────────────────┘
             │                                   │
             ▼                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Python (FastAPI, существующий код)                                  │
│                                                                     │
│ ┌─ Telegram entry/router ────────────────────────────────────────┐  │
│ │ читает from.id → lookup users.container_id → forward payload   │  │
│ │ не парсит содержимое сообщения                                 │  │
│ └────────────────────────────────────────────────────────────────┘  │
│                                                                     │
│ ┌─ HAE webhook (как сейчас) ─┐  ┌─ Парсеры (как сейчас) ──────────┐ │
│ │ Bearer per-user → PG       │  │ Photo (Vision), Voice (Whisper) │ │
│ └────────────────────────────┘  └─────────────────────────────────┘ │
│                                                                     │
│ ┌─ Tools API для агентов (новое, ~10 endpoint'ов) ──────────────┐   │
│ │ POST /api/agent/log_meal_text     POST /api/agent/log_meds    │   │
│ │ POST /api/agent/log_supplement    POST /api/agent/log_bp      │   │
│ │ POST /api/agent/log_symptom       GET  /api/agent/recent_meals│   │
│ │ GET  /api/agent/kb_value          GET  /api/agent/dashboard   │   │
│ │ GET  /api/agent/user_profile      POST /api/agent/regen_token │   │
│ │ JWT в Authorization, проверка по users.jwt_secret             │   │
│ └────────────────────────────────────────────────────────────────┘  │
│                                                                     │
│ ┌─ Dashboard generator (как сейчас) ─┐  ┌─ KB pipeline (новое) ─┐   │
│ │ /mc/{share_token} → HTML           │  │ Watcher GDrive → Vis. │   │
│ │ адаптивные блоки                   │  │ → knowledge_base.json │   │
│ └────────────────────────────────────┘  └───────────────────────┘   │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
              ┌────────────┼────────────┬──────────────┬─────────────┐
              ▼            ▼            ▼              ▼             ▼
     ┌──────────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
     │  nc-sasha    │ │ nc-nika  │ │nc-andrey │ │ nc-elen  │ │  …more   │
     │  pack:       │ │  pack:   │ │  pack:   │ │  pack:   │ │  scale   │
     │  bariatric   │ │  female- │ │  cardiac │ │  female- │ │  to 50+  │
     │              │ │  cycle   │ │          │ │  cycle   │ │          │
     │ CLAUDE.md    │ │CLAUDE.md │ │CLAUDE.md │ │CLAUDE.md │ │          │
     │ memory/      │ │ memory/  │ │ memory/  │ │ memory/  │ │          │
     │ skills/      │ │ skills/  │ │ skills/  │ │ skills/  │ │          │
     │ scheduled    │ │ scheduled│ │ scheduled│ │ scheduled│ │          │
     │ jobs         │ │ jobs     │ │ jobs     │ │ jobs     │ │          │
     │              │ │          │ │ +AFib-   │ │ +cycle-  │ │          │
     │              │ │          │ │  alert   │ │  track.  │ │          │
     └──────┬───────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────────┘
            │              │            │            │
            │  HTTP REST с JWT (per-user identity)
            │              │            │            │
            └──────────────┴────────────┴────────────┘
                                    │
                                    ▼
                  ┌────────────────────────────────────┐
                  │ PostgreSQL (Hetzner)               │
                  │ - users + cohort + container_id    │
                  │ - RLS policies на data-таблицах    │
                  │ - PG-роли hv_user_{id}             │
                  │ - audit_log триггеры на admin      │
                  │ - auto_backup.sh + GDrive snapshots│
                  └────────────────────────────────────┘
```

### Поток сообщения (текстовый запрос)

1. Пользователь пишет «выпил витамины» в `@health_vault_bot`.
2. Telegram → POST на `/telegram/webhook` (Python FastAPI).
3. Router читает `from.id=895655`, lookup `users WHERE telegram_id=895655` → `container_id='nc-sasha'`.
4. Router POST в `http://localhost:8001/agent/process` (внутренний endpoint контейнера) с payload.
5. Агент в `nc-sasha` обрабатывает: материализует разговор с pack:bariatric (CLAUDE.md + memory + skills), решает что сделать.
6. Агент вызывает skill `log-supplement` → tool-call `POST /api/agent/log_supplement` с JWT.
7. FastAPI проверяет JWT → user_id=895655 → подключается к PG через роль `hv_user_895655` → INSERT в `supplements_log`.
8. Tool-call возвращает успех агенту.
9. Агент формирует ответ («Записал. Сегодня ты принял 6 из 8 утренних. Лежишь ли что-то ещё?») и вызывает Telegram sendMessage с токеном `@health_vault_bot`.
10. Опционально: agent обновляет свою память («Sasha вечером пьёт меньше добавок чем должен, спросить почему»).

### Поток фото еды (без агента, как сейчас)

1. Фото → Telegram → router → определяет тип = photo → НЕ форвардит в агент, обрабатывает как сейчас (`telegram-bot/handlers/photo.py`).
2. Парсер еды (Claude Vision) → `nutrition_log` через существующий код.
3. Опционально: после записи router пингует контейнер юзера «у пользователя новая еда, посмотри если хочешь прокомментировать» (асинхронно, не в критическом пути).

### Поток ремайндера (proactive)

1. NanoClaw в `nc-andrey` имеет scheduled job: `08:00 ежедневно — напомнить про метформин`.
2. В 08:00 контейнер запускает skill `medication-reminder`.
3. Skill вызывает Telegram sendMessage с inline-buttons «Принял / Через 30 мин / Пропустил».
4. Кнопка нажата → Telegram callback_query → router → forward в `nc-andrey` → skill пишет в `medication_log` через `POST /api/agent/log_meds`.

## 5. Изменения в БД

### 5.1 Таблица `users` (расширение)

```sql
ALTER TABLE users ADD COLUMN cohort VARCHAR(20) DEFAULT 'external'
  CHECK (cohort IN ('owner', 'family', 'early_user', 'external'));
ALTER TABLE users ADD COLUMN container_id VARCHAR(50) NULL;
ALTER TABLE users ADD COLUMN container_port INTEGER NULL;
ALTER TABLE users ADD COLUMN pack_name VARCHAR(50) DEFAULT 'generic'
  CHECK (pack_name IN ('generic', 'cardiac', 'bariatric', 'female-cycle'));
ALTER TABLE users ADD COLUMN jwt_secret VARCHAR(64) NULL;
ALTER TABLE users ADD COLUMN encrypted_openai_key TEXT NULL;
ALTER TABLE users ADD COLUMN encrypted_anthropic_key TEXT NULL;
```

Существующие 3 пользователя получают:
- Александр: `cohort='owner', pack_name='bariatric'`
- Ника: `cohort='family', pack_name='female-cycle'`
- Андрей: `cohort='early_user', pack_name='cardiac'`

### 5.2 Row-Level Security

```sql
-- Создать роль для каждого активного пользователя
CREATE ROLE hv_user_895655 LOGIN PASSWORD '<random>';
-- ... аналогично для каждого

-- Включить RLS на data-таблицах
ALTER TABLE nutrition_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE supplements_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE weights ENABLE ROW LEVEL SECURITY;
ALTER TABLE activity_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE blood_pressure_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_settings ENABLE ROW LEVEL SECURITY;

-- Политика: видишь только свои строки (берём user_id из имени роли)
CREATE POLICY user_isolation ON nutrition_log
  USING (user_id = (substring(current_user, 9))::bigint);
-- ... аналогично для всех таблиц
```

Admin-роль `healthvault` (текущая) — не имеет RLS-ограничений, но любой её SELECT/UPDATE логируется в audit_log.

### 5.3 Audit log

```sql
CREATE TABLE audit_log (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ DEFAULT NOW(),
  db_user TEXT,                  -- кто запросил (роль)
  query_type TEXT,               -- SELECT / UPDATE / DELETE / INSERT
  table_name TEXT,
  affected_user_id BIGINT,       -- чьи данные затронуты (если можно вычислить)
  query_excerpt TEXT             -- первые 500 символов запроса
);

-- Триггер pg_audit или ручной log_statement = 'all' для admin-роли + парсинг
```

Деталь реализации (триггер vs `pg_audit` extension vs `log_statement`) — на уровне implementation plan.

### 5.4 Новые таблицы (Sprint 3, не Sprint 1)

```sql
CREATE TABLE medication_log (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT REFERENCES users(telegram_id),
  ts TIMESTAMPTZ NOT NULL,
  medication_name TEXT NOT NULL,
  dose_mg NUMERIC,
  status TEXT CHECK (status IN ('taken', 'skipped', 'delayed')),
  notes TEXT
);

CREATE TABLE symptom_log ( ... );  -- с зашифрованным notes (Sprint 3 С-уровень)
CREATE TABLE nicotine_log ( ... );
CREATE TABLE cycle_log ( ... );
```

## 6. NanoClaw-контейнеры

### 6.1 Структура pack'а

```
packs/cardiac/
  CLAUDE.md          ← system prompt: ты health-coach с фокусом на сердечный
                       ритм, AFib, ишемию, контроль АД, adherence к
                       антикоагулянтам/Метформину/Кораксану. Стиль общения:
                       уважительный, прямой, без алармизма, но настойчивый
                       по red flags.
  skills/
    log-meds/SKILL.md         ← инструкция «как логировать лекарства»
    log-bp/SKILL.md
    log-symptom/SKILL.md
    medication-adherence/SKILL.md  ← scheduled job spec
    AFib-alert/SKILL.md       ← red-flag triggers
  scheduled-jobs.json ← cron-like расписание ремайндеров для cohort
```

### 6.2 Per-user override

```
containers/nc-andrey/
  CLAUDE.md          ← опционально: override pack'а с конкретикой
                       (POAF после фундопликации 20.01.25, ICM Reveal Linq
                       29.04.26, не принимает Метформин 4 мес — addressing
                       priority)
  memory/            ← persistent volume mount
  env/
    JWT_SECRET=...
    PYTHON_API_URL=http://hv-api:8000   # имя сервиса в docker-compose сети
                                        # (либо bridge IP хоста — детали в impl plan)
    OPENAI_API_KEY=... (от users.encrypted_openai_key или системный)
```

### 6.3 Sprint 1 — какие packs готовы

**К 14.05:** только `pack:cardiac` (для Андрея). Остальные — Sprint 2.

## 7. Tools API

### 7.1 Список endpoint'ов (~10)

| Метод | Path | Что делает | Авторизация |
|-------|------|-----------|-------------|
| POST | `/api/agent/log_meal_text` | Логирует приём пищи из текста (агент уже распарсил) | JWT |
| POST | `/api/agent/log_supplement` | Логирует добавки | JWT |
| POST | `/api/agent/log_meds` | Логирует приём лекарств (Sprint 3 — таблица) | JWT |
| POST | `/api/agent/log_bp` | Логирует АД | JWT |
| POST | `/api/agent/log_symptom` | Логирует симптом / самочувствие | JWT |
| POST | `/api/agent/log_nicotine` | Логирует Никоретте (Sprint 3) | JWT |
| GET | `/api/agent/recent_meals?days=7` | Последние приёмы пищи | JWT |
| GET | `/api/agent/kb_value?key=hba1c` | Достать значение из KB пользователя | JWT |
| GET | `/api/agent/dashboard_summary` | Текстовая сводка с дашборда | JWT |
| GET | `/api/agent/user_profile` | Полный профиль (для агента, не для UI) | JWT |
| POST | `/api/agent/regenerate_health_token` | Self-serve regen HAE токена | JWT |

### 7.2 JWT-аутентификация

- `users.jwt_secret` — random per user, выдаётся при создании контейнера.
- В env контейнера: `JWT_SECRET=<value>`.
- Контейнер генерирует JWT с claims `{user_id, container_id, exp: now+1h}`.
- FastAPI middleware декодирует JWT, проверяет совпадение `user_id` с `container_id` (по таблице `users`), подключается к PG через роль `hv_user_{user_id}`.

## 8. Telegram routing

### 8.1 Webhook entry

```python
@app.post("/telegram/webhook")
async def telegram_webhook(payload: dict):
    from_id = payload["message"]["from"]["id"]
    user = db.query(User).filter_by(telegram_id=from_id).first()

    if not user:
        # Новый пользователь → онбординг wizard (handle_onboarding)
        return await handle_onboarding(payload)

    # Если фото / голос — обрабатываем как сейчас (existing handler)
    if "photo" in payload["message"] or "voice" in payload["message"]:
        return await legacy_handler(payload)

    # Иначе — форвардим в контейнер
    container_url = f"http://nc-{user.container_id}:{user.container_port}/agent/process"
    async with httpx.AsyncClient() as client:
        await client.post(container_url, json=payload, timeout=30.0)
```

### 8.2 Контейнер отвечает в Telegram сам

Контейнер вызывает Telegram Bot API (`sendMessage`) с токеном `@health_vault_bot` (передан через env). Не возвращает ответ через router — это упрощает архитектуру (router fire-and-forget).

## 9. Privacy boundary

### 9.1 Что защищено

| Уровень | Кто видит | Sprint |
|---------|-----------|--------|
| App-layer фильтр (текущее) | Контейнер пользователя видит только свои строки через RLS-роль | Sprint 1 |
| Audit log | Любой SELECT/UPDATE от admin-роли пишется в `audit_log` | Sprint 1 |
| Column encryption | `symptom_log.notes`, `cycle_log.notes`, `nicotine_log.notes`, `private_diary` зашифрованы ключом из контейнера | Sprint 3 |

### 9.2 Что НЕ защищено

- Root-доступ Александра к серверу (он admin Hetzner-инстанса). Это ограничение архитектуры, не ошибка дизайна.
- Перехват трафика между Telegram API и сервером (TLS, но Telegram CDN видит).
- Сохранность Никиного master key в её контейнере — если она потеряет доступ к контейнеру (volume corrupted), приватные заметки потеряны навсегда (Sprint 3).

### 9.3 Контракт с Никой (для разговора)

«Твои питание, вес, шаги — лежат в общей БД с RLS. Я как админ могу прочесть, но это залогируется и ты увидишь. Дневник симптомов, цикл, никотин — будут зашифрованы (Sprint 3) — даже я не смогу прочесть без твоего ключа.»

## 10. Спринт-план

### 10.1 Sprint 1 — до 14.05.2026 (10 дней)

**Цель:** Андрей с pack:cardiac в проде, существующие пользователи не сломались.

| Задача | Где | Эстимейт |
|--------|-----|----------|
| Миграция БД: `cohort`, `container_id`, `pack_name`, `jwt_secret`, `encrypted_*_key` | Python/Alembic | 0.5 д |
| Миграция БД: PG-роли + RLS-политики на 6 data-таблиц | SQL | 1 д |
| Миграция БД: `audit_log` + триггер | SQL | 1 д |
| 10 FastAPI endpoint'ов tools API + JWT middleware | Python | 2 д |
| Telegram router: чтение from.id, lookup, forward, legacy-bypass для photo/voice | Python | 1 д |
| Wizard `/start` (throwaway state-machine на aiogram) | Python | 1 д |
| `/regenerate_health_token` команда | Python | 0.5 д |
| Адаптивный dashboard (skip пустых блоков) | Python | 1 д |
| BotFather: `@health_vault_bot` токен + webhook URL | Manual | 0.5 ч |
| NanoClaw scaffold: один контейнер `nc-andrey`, pack:cardiac (CLAUDE.md по данным Андрея) | Node | 2 д |
| Базовые skills: log-meds (text), log-bp (text), query-kb, dashboard-summary | Node | 1.5 д |
| Docker compose обновление, deploy.sh адаптация | Infra | 0.5 д |
| Smoke-тест end-to-end: Андрей пишет → router → агент → tool → PG → ответ | All | 1 д |

**Резерв:** 0.5 дня на баги. Итого ~12.5 дней — натянуто на 10 рабочих дней.

**Минимум для 14.05 если Sprint 1 проседает:**
1. БД-миграции (cohort, container_id, container_port, pack_name, jwt_secret, RLS, audit_log) — обязательно.
2. Telegram router + 5 базовых tools API endpoint'ов (log_meal_text, log_supplement, log_bp, get_user_profile, get_dashboard_summary) — обязательно.
3. `nc-andrey` контейнер с pack:cardiac и базовыми скиллами — обязательно.
4. Wizard `/start`, `/regenerate_health_token`, адаптивный dashboard — желательно, но если режем — переносим в Sprint 2 (для них Андрей продолжает использовать существующие хендлеры).

### 10.2 Sprint 2 — 15–25.05.2026 (10 дней)

**Цель:** все 10 пользователей в проде, KB-pipeline, BYOK.

| Задача | Эстимейт |
|--------|----------|
| Packs: bariatric (Sasha), female-cycle (Nika, Elen), generic (остальные) | 2 д |
| Деплой контейнеров nc-sasha, nc-nika, nc-elen + 5 generic | 1 д |
| KB pipeline: GDrive watcher → Claude Vision → knowledge_base.json | 3 д |
| BYOK: encrypted_openai_key (libsodium), decrypt при старте контейнера, miniapp UI «введите ключ» | 1.5 д |
| Miniapp: страница «мой профиль / токен / dashboard / GDrive-папка» | 2 д |
| Резерв | 0.5 д |

### 10.3 Sprint 3 — после 25.05 (~2 недели)

**Цель:** медфункции и проактивность.

- Таблицы: `medication_log`, `symptom_log`, `nicotine_log`, `cycle_log` — 1.5 д
- NanoClaw scheduled jobs (built-in): ремайндеры с inline-buttons — 4 д
- Telegram callback_query → router → контейнер → log → audit — 1 д
- Column-level encryption для sensitive notes (Privacy уровня C) — 4 д
- PhenoAge per-user из knowledge_base.json — 2 д

### 10.4 Эпик отдельно (июнь+)

- MDT-консилиум (5–9 packs специалистов + GP-pack + PubMed tool).

## 11. Риски и митигации

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| 14.05 — натянутый дедлайн на Андрея | средняя | Резерв: к 14.05 у Андрея минимум — текущий бот + HAE-поток + dashboard. Агент догоняет в Sprint 2 если Sprint 1 проседает. |
| Кривая обучения Anthropic Agent SDK / NanoClaw для нас | средняя | Sprint 0 (3 дня): локальный hello-world контейнер до старта Sprint 1. Если SDK сложнее ожидаемого — fallback на pydantic-ai в Python. |
| Гетерогенный стек (Python + Node) — операционная сложность | низкая | Один Hetzner-сервер, Docker Compose оркестрирует, общий лог-pipeline. У нас уже есть docker-compose.yml для Postgres. |
| LLM-стоимость растёт линейно с пользователями | средняя | BYOK для технических (Андрей сам платит). Для остальных — лимиты в pack'е + Haiku-модель для рутинных tool-роутингов, Sonnet только для медицинских разборов. |
| Memory loss при крэше контейнера | низкая | Volume-mount memory/ → ежедневный rsync в `/Users/.../HealthVault/_backups_db/agent_memory/{user_id}/`. |
| BYOK key recovery если пользователь потерял доступ | низкая | encrypted_openai_key хранится в PG — пользователь может через miniapp заменить ключ заново. |
| RLS-политика блокирует легитимный admin-запрос | низкая | Admin-роль `healthvault` — superuser, RLS не применяется, только audit_log. Триггер пишет, не блокирует. |
| Privacy contract с Никой не выполнен (баг в RLS) | средняя | Smoke-тест: nc-nika вызывает GET /api/agent/recent_meals — должен вернуть только Никины. Pen-test: nc-sasha пробует подменить JWT user_id на 485132 — должен получить 403. |

## 12. Тестовая стратегия

### 12.1 Unit-тесты (Python)

- Существующая инфра pytest (`tests/`).
- Новые: для каждого tools API endpoint — happy path + JWT validation + RLS isolation.

### 12.2 Integration

- `tests/integration/test_agent_flow.py`:
  - Поднять `nc-test` контейнер с тестовым pack'ом.
  - Замокать Telegram → отправить сообщение → проверить PG-state.
- `tests/integration/test_privacy_isolation.py`:
  - `nc-nika` вызывает endpoint от имени user_id=895655 (Sasha) — должен 403.
  - `nc-nika` вызывает свой endpoint — успех.
- `tests/integration/test_audit_trail.py`:
  - Admin делает `SELECT * FROM nutrition_log WHERE user_id=485132`.
  - Проверить что в `audit_log` появилась запись.

### 12.3 Smoke в проде

- После Sprint 1 deploy: ручной чек end-to-end Андрея + регрессия Sasha (фото еды по-прежнему работает) + регрессия Ники (питание по-прежнему пишется).

## 13. Открытые вопросы / решения по умолчанию

| Вопрос | Default решение | Когда пересмотреть |
|--------|----------------|-------------------|
| CLAUDE.md authoring — кто пишет doctor-prompt? | Sprint 1: Александр пишет руками per user из шаблона pack'а. Sprint 2: пользователь правит через miniapp file editor. | После Sprint 1 retro |
| Resource limits per контейнер | 256MB RAM, 0.25 CPU. Тюн в Sprint 2 по факту нагрузки. | После 5+ контейнеров в проде |
| LLM роутинг внутри контейнера | По умолчанию Sonnet 4.6 для медицинских разборов, Haiku для tool-routing, Whisper для голоса. BYOK — то же что у пользователя. | После замера стоимости |
| Что делать если пользователь не отвечает на ремайндер 3 дня | Эскалация: писать ещё раз с другим текстом, потом — Александру в его pack как «Андрей пропустил 3 дня метформина». | Sprint 3 при реализации reminder engine |

## 14. Связь с существующими планами

- **`todo.md`**: пункт «🚀 Полноценный мультиюзер NutriLogBot» (стр. 510) частично закрывается этим спеком (cohort + privacy + per-user packs). После реализации обновить статус.
- **`docs/MULTI_USER_PLAN.md`**: исторический документ про подключение Ники, не противоречит этому спеку. Не удаляем — как контекст.
- **`docs/ONBOARDING_v2_apr26.md`**: документ для Андрея про текущую систему. После Sprint 1 пишем `ONBOARDING_v3_may26.md` с инструкцией для агентного режима.
- **`config/users.py`**: open registration уже есть, не меняем — добавляем cohort через миграцию.
- **chat1185 в Bitrix24:** результат брейншторма передаём Клоду Андрея отдельным сообщением — он тоже планировал часть этого (см. их `DOCTOR_PROMPT_FOR_HEALTH_VAULT_BOT.md` и `REMINDER_SCHEDULE.json`).

## 15. Что дальше

После approve этого спека → переключаюсь на skill `superpowers:writing-plans` и собираю implementation plan на Sprint 1 с конкретными файлами, миграциями, тестами и порядком merge'а.
