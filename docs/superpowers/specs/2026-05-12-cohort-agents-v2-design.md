# Botkin Cohort Agents v2 — Design Spec

**Дата:** 12 мая 2026
**Автор:** Claude (Александр approve)
**Статус:** утверждён, основа для следующих 2–3 спринтов
**Заменяет:** `2026-05-04-cohort-agents-design.md` (тот спек частично реализован — миграции БД, Tools API скелет, Telegram router — но NanoClaw-часть deprecated)

---

## 1. Зачем v2

Спек от 4 мая предполагал per-user NanoClaw Docker-контейнеры с Node.js + Anthropic Agent SDK, column-level encryption sensitive полей, per-user PG-роли и passphrase-based key management. Это работающее, но **сложное** решение.

После brainstorm 11.05.2026 с Александром модель радикально упростилась:

1. **Приватность через физическое разделение, а не через шифрование.** Сервер хранит ТОЛЬКО shared-данные. Приватное (КПТ-дневники, intimate notes) лежит у юзера на его маке. AI видит приватное только в личной сессии юзера в Claude Desktop, где локальные файлы подключаются параллельно с remote MCP.
2. **Conversational AI — в monolith Python**, не в per-user Docker-контейнерах. Один процесс, общая инфра, packs как файлы в репо. NanoClaw отложен — может оживить позже для отдельных юзеров когда понадобится compute-изоляция.
3. **MCP server** для Claude Desktop коллабораторов — даёт каждому read+write доступ к своим данным через personal token.
4. **Общий longevity KB** в репо — структурированная база знаний, доступная всем агентам.

Это упрощение убирает из 4-майского спека:
- Per-user Docker-контейнеры с Node.js (NanoClaw)
- Column-level encryption для symptom/cycle/nicotine/diary полей
- Per-user PG-роли + passphrase recovery codes
- BYOK (encrypted_openai_key/anthropic_key в БД)
- Pack-system в Docker-volumes

И **добавляет**:
- MCP server для Claude Desktop
- Conversational agent (с эвристикой) внутри Telegram-бота
- Структурированный longevity KB в `docs/longevity_kb/`
- Два типа токенов (HAE + MCP) с lifecycle management

---

## 2. Принятые решения (контракт)

| # | Решение | Альтернативы (отвергнуты) |
|---|---------|---------------------------|
| D1 | **Monolith Python для conversational agent.** NanoClaw — заморожен, может вернуться позже для отдельных юзеров. Pack-конфиги (`CLAUDE.md` per cohort, `skills/` per cohort) лежат в репо, читаются Python-агентом на лету при сообщении | NanoClaw сейчас (операционно тяжело, 50 контейнеров = 12 ГБ RAM на CCX13) |
| D2 | **Privacy через физическое разделение.** Сервер хранит только то что юзер сам отдал (shared). Приватное — у юзера локально, никогда не покидает его мак | Column-encryption на сервере (избыточно), per-user volumes в Docker (требует NanoClaw) |
| D3 | **MCP server `mcp.health.orangegate.cc`.** Каждый юзер прописывает в `claude_desktop_config.json` Botkin MCP с personal токеном. ~10 read+write tools | Direct HTTP API + curl (некрасиво), локальный CLI (требует установки) |
| D4 | **Два типа токенов, раздельные.** `health_token` (HAE webhook, узкий scope) + `mcp_token` (MCP server, широкий scope) | Универсальный токен (опасно — утечка одного = всё), один с capability-claims в JWT (overengineering) |
| D5 | **MCP tools — read + write.** Юзер из Claude Desktop может логировать еду/добавки/АД, обновлять заметки в своём KB | Только read (половинчатый UX, юзер вынужден переключаться на бот для логирования) |
| D6 | **Conversational agent в боте с эвристикой.** Структурированные сообщения (фото, голос, паттерны «съел X», «принял Y», числа АД) → текущий парсер. Открытые вопросы («как мне снизить ApoB?») → Claude API с user_context + pack + longevity_kb | Всегда LLM (~$30/мес для 5 юзеров, рост линейный), всегда парсер (нельзя задать вопрос боту) |
| D7 | **Общий longevity KB в `docs/longevity_kb/`.** Подключается в system-prompt агента + доступен через MCP-tool `get_longevity_reference(topic)` | Динамическое подтягивание из веба (нестабильно), только персональные KB (нет общей базы) |
| D8 | **Token lifecycle: бот + мини-апп + админ-дашборд.** Юзер сам выдаёт/перевыпускает/отзывает свои токены через бот и мини-апп. Админ видит статусы и может отозвать в критических случаях | Только через админа (плохо для self-serve), только через бот (нет визуального инструмента) |
| D9 | **mcp_access_log → v1.1.** В MVP не логируем каждый вызов MCP. Добавим когда юзеров станет 10+ для прозрачности | В MVP (overhead на старте) |
| D10 | **Без staging-сервера пока.** PR → review → merge → deploy в продакшен. Юзеров мало, откат быстрый | Отдельный staging-CCX11 (~5€/мес) — преждевременно |

---

## 3. Архитектура

### 3.1 Топология

```
┌─────────────────────────────────────────────────────────────┐
│ СЕРВЕР (Hetzner berlin.orangegate.cc, общий)                │
│                                                             │
│  ┌─ Postgres ────────────────────────────────────────────┐  │
│  │ shared-данные ВСЕХ юзеров:                            │  │
│  │ • питание, добавки, вес, BP, sleep, HRV               │  │
│  │ • профили (users, user_settings)                      │  │
│  │ • biomarkers (knowledge_base entries уже в БД)        │  │
│  │ • тренировки (Garmin/Apple Watch HR-сэмплы)           │  │
│  │                                                       │  │
│  │ Что НЕ хранится: КПТ-дневники, intimate notes,        │  │
│  │ private symptom journals — всё у юзера локально       │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌─ Google Drive watcher ────────────────────────────────┐  │
│  │ Наблюдает за shared-папками юзеров:                   │  │
│  │   Botkin/{Имя} — Здоровье/                       │  │
│  │ + FamilyDocs/{Имя} — Документы/                       │  │
│  │ Конвертирует PDF/JPEG → knowledge_base.json           │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌─ Telegram-бот @health_vault_bot ──────────────────────┐  │
│  │ 1. Структурированные данные (фото, голос, "съел X")   │  │
│  │    → парсер LLM → INSERT в БД (как сейчас)            │  │
│  │ 2. Открытые вопросы ("как снизить ApoB?")             │  │
│  │    → Conversational agent (D6) → ответ в Telegram     │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌─ Tools API ─────────┐  ┌─ MCP server ────────────────┐  │
│  │ /api/agent/* (Python│  │ /mcp/* (FastMCP-based)       │  │
│  │ внутренний агент    │  │ для Claude Desktop юзеров    │  │
│  │ ходит сюда)         │  │ Auth: mcp_token              │  │
│  └─────────────────────┘  └──────────────────────────────┘  │
│                                                             │
│  ┌─ HAE webhook ───────┐  ┌─ Admin dashboard /admin/ ────┐  │
│  │ Apple Health Auto   │  │ HTTP Basic, только Alex       │  │
│  │ Export → server     │  │ Управление юзерами, токенами  │  │
│  │ Auth: health_token  │  │                               │  │
│  └─────────────────────┘  └───────────────────────────────┘  │
│                                                             │
│  ┌─ Packs (в репо: packs/{cohort}/) ────────────────────┐   │
│  │ packs/generic/CLAUDE.md     ← system prompt          │   │
│  │ packs/cardiac/CLAUDE.md     ← Андрей                 │   │
│  │ packs/bariatric/CLAUDE.md   ← Александр              │   │
│  │ packs/female-cycle/CLAUDE.md← Ника, Элен             │   │
│  │ packs/{cohort}/skills/*.md  ← additional tools/logic │   │
│  │ packs/{cohort}/reminders.json ← scheduled jobs       │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─ docs/longevity_kb/ ─ общий KB для всех агентов ────┐   │
│  │ biomarkers/        ← нормы возраст-пол, динамика     │   │
│  │ protocols/         ← Attia, Sinclair, Patrick guides │   │
│  │ medications/       ← Метформин, статины, etc         │   │
│  │ topics/            ← longevity, sleep, exercise...   │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                          ▲
                          │ HTTPS + mcp_token
                          │
        ┌─────────────────┴───────────────────────┐
        │                                         │
        ▼                                         ▼
┌──────────────────────┐                ┌──────────────────────┐
│ Мак Олега            │                │ Мак Ники             │
│ Claude Desktop Code  │                │ Claude Desktop Code  │
│                      │                │                      │
│ MCP servers:         │                │ MCP servers:         │
│ • healthvault (rem.) │                │ • healthvault (rem.) │
│ • filesystem (local) │                │ • filesystem (local) │
│                      │                │                      │
│ Локально:            │                │ Локально:            │
│ ~/CBT-journal/       │ ← приват       │ ~/Private-Health/    │ ← приват
│                      │                │                      │
│ Через Google Drive:  │                │ — (не пользуется     │
│ shared папка         │ ← shared       │   shared GDrive)     │
└──────────────────────┘                └──────────────────────┘
```

### 3.2 Кто видит что

| Источник данных | Видит owner (Alex) | Видит AI юзера в боте | Видит AI юзера в Claude Desktop |
|---|---|---|---|
| Питание из бота | ✅ (через админ-дашборд если family/early_user) | ✅ | ✅ через MCP |
| Добавки/лекарства из бота | ✅ | ✅ | ✅ |
| Apple Health / Garmin | ✅ | ✅ | ✅ |
| Shared KB (`Botkin/Имя — Здоровье/`) | ✅ если расшарено | ✅ | ✅ |
| **Private KB на маке юзера** | ❌ никогда | ❌ (бот не видит) | ✅ через локальный filesystem MCP |
| **КПТ-дневник на маке** | ❌ никогда | ❌ | ✅ через локальный filesystem MCP |
| Общий longevity KB | ✅ (репо) | ✅ через system-prompt | ✅ через MCP-tool |

---

## 4. Tokens & Access

### 4.1 Два типа токенов

| Поле в `users` | Назначение | Scope | Когда выдаётся |
|---|---|---|---|
| `health_token` | Apple Health Auto Export webhook | Write метрики из Apple Health (steps, weight, BP, etc) | На онбординге автоматически |
| `mcp_token` | Claude Desktop MCP server | Read+write всех данных юзера в БД + KB | По запросу юзера через `/mcp_token` |

Каждый — длинная случайная строка (32 байта hex). Хранится в plain в БД (не хэш — нам нужно сравнить по equality, не bcrypt, как с паролем). HTTPS защищает в транспорте.

### 4.2 Lifecycle

**Юзер через бот:**
```
/health_token         — показать текущий
/health_token rotate  — перевыпустить (старый недействителен)
/mcp_token            — показать текущий (или выдать если не было)
/mcp_token rotate     — перевыпустить
/mcp_token revoke     — отозвать (старый недействителен, новый не выдан)
```

**Юзер через мини-апп:**
Вкладка «Настройки» → секция «🔑 Токены»:
- Apple Health (HAE): статус, кнопки [Показать] [Перевыпустить]
- MCP (Claude Desktop): статус, кнопки [Выпустить] / [Показать] [Перевыпустить] [Отозвать]
- При нажатии «Показать»/«Выпустить» — токен показывается один раз с инструкцией скопировать

**Админ через дашборд:**
В таблице юзеров новая колонка **🔑 Tokens** — индикатор «HAE ✅ · MCP ✅». Клик раскрывает действия:
- Перевыпустить HAE / Перевыпустить MCP
- Отозвать MCP / Отозвать оба
- Все действия с confirmation modal

### 4.3 База данных

```sql
-- mcp_token уже добавляется в этом спеке
ALTER TABLE users ADD COLUMN mcp_token VARCHAR(255) NULL;
ALTER TABLE users ADD COLUMN mcp_token_issued_at TIMESTAMPTZ NULL;

-- health_token уже существует (был в Sprint 1 04.05)
-- health_token_issued_at — добавляем для симметрии
ALTER TABLE users ADD COLUMN health_token_issued_at TIMESTAMPTZ NULL;
```

### 4.4 Что НЕ в MVP

- **mcp_access_log** (D9): логирование каждого вызова MCP с user_id, ip, tool_name, ts. → v1.1
- **Expiry-policy для токенов** (auto-revoke после N дней без активности) → v1.1

---

## 5. MCP server

### 5.1 Endpoint и стек

- **URL:** `https://mcp.health.orangegate.cc` (новый subdomain через Cloudflare → Hetzner)
- **Стек:** FastMCP (Python) — поверх существующего FastAPI-приложения
- **Auth:** Bearer `mcp_token` в Authorization header

Mini-MCP servers могут быть реализованы как отдельный FastAPI router (`webhook/mcp_server.py`) и работать в том же процессе что и бот.

### 5.2 Tools (MVP, ~12 штук)

**Read tools:**

| Tool | Параметры | Возвращает |
|---|---|---|
| `get_my_profile` | — | Имя, возраст, пол, рост, вес, диагнозы (из chronic_conditions), текущие лекарства, BMR, цель, активность |
| `get_my_meals` | `days=7, include_items=true` | Приёмы пищи с КБЖУ |
| `get_my_supplements` | `days=7` | Лог добавок и лекарств |
| `get_my_weights` | `days=90` | Замеры веса/жира/мышц с источником |
| `get_my_bp` | `days=30` | Систолическое/диастолическое/пульс |
| `get_my_activity` | `days=30` | Шаги, активные ккал, HR покоя, сон |
| `get_my_dashboard_summary` | — | Текстовая сводка с mc-дашборда (главные KPI) |
| `read_my_kb` | `section=null` | Содержимое `knowledge_base.json` shared-папки |
| `query_my_kb` | `query` | Полнотекстовый поиск по shared KB |
| `get_longevity_reference` | `topic` | Содержимое `docs/longevity_kb/{topic}.md` |

**Write tools:**

| Tool | Параметры | Что делает |
|---|---|---|
| `log_meal` | `description, items, time` | Запись в `nutrition_log` |
| `log_supplement` | `name, dose, time, slot` | Запись в `supplements_log` |
| `log_bp` | `systolic, diastolic, pulse, time` | Запись в `blood_pressure_logs` |
| `log_weight` | `weight_kg, body_fat, time` | Запись в `weights` |
| `update_my_profile` | `field, value` | Обновить smoking_status, chronic_conditions, и т.д. |

### 5.3 Конфиг для юзера

После выпуска токена бот шлёт сообщение:

```
✅ MCP-токен выдан.

Скопируй блок ниже и добавь в свой Claude Desktop конфиг:

📂 ~/Library/Application Support/Claude/claude_desktop_config.json

{
  "mcpServers": {
    "healthvault": {
      "type": "http",
      "url": "https://mcp.health.orangegate.cc",
      "headers": {
        "Authorization": "Bearer hvmcp_xxxxxxxxx..."
      }
    }
  }
}

Перезапусти Claude Desktop. После этого в чате с Claude:
"какие у меня тренды веса за месяц"
"что я ел вчера на ужин"
"какая моя норма витамина D"
```

### 5.4 Auth-flow

1. Claude Desktop → POST `https://mcp.health.orangegate.cc/tools/list` с `Authorization: Bearer hvmcp_xxx`
2. FastMCP middleware: lookup `users WHERE mcp_token = $1` → если None → 401, иначе сохранить `user_id` в request state
3. Tools API: каждый tool принимает payload, в начале — фильтр `WHERE user_id = $current_user`
4. Возвращает данные **только этого юзера**, юзер физически не видит чужое

---

## 6. Conversational agent в Telegram

### 6.1 Эвристика (D6)

При входящем сообщении:

```python
def classify_message(msg) -> str:
    if "photo" in msg or "voice" in msg:
        return "structured"  # → existing food parser
    text = msg.get("text", "")
    if STRUCTURED_PATTERN.match(text):  # "съел X", "принял Y", "АД 120/80", "/log_*"
        return "structured"
    if text.startswith("/"):
        return "command"  # → command handler
    return "open_question"  # → conversational agent
```

`STRUCTURED_PATTERN` — простой regex/keyword-matcher (можно итеративно улучшать). При false-positive (юзер задал вопрос, попало в structured) — парсер вернёт «не понял», тогда fallback в conversational.

### 6.2 Conversational pipeline

```
open_question
  ↓
[load context]
  ├── pack:{user.pack_name}/CLAUDE.md  (system prompt)
  ├── user.profile (имя, возраст, диагнозы, лекарства, рост, вес, цель)
  ├── recent_data (последние 7 дней питания, добавок, веса)
  ├── shared_kb (knowledge_base.json юзера)
  └── longevity_kb (только заголовки секций, full на запрос)
  ↓
[Claude API call] (Sonnet, max_tokens=800)
  ↓
[response → Telegram sendMessage]
```

Pack используется чтобы агент знал контекст cohort'а: «ты health-coach для пациента с шизотипическим расстройством», «ты health-coach для пациента после фундопликации», etc.

### 6.3 Cost-control

- Sonnet 4 для conversational → ~$0.005/сообщение
- При 5 юзерах × 10 conversational сообщений/день = $0.25/день = ~$7.5/мес
- При 30 юзерах × 10 = $1.5/день = ~$45/мес — приемлемо

Включаем prompt caching (Anthropic SDK): pack-prompt и longevity_kb headers кэшируются между запросами, юзер-context — нет.

---

## 7. Packs

### 7.1 Структура

```
packs/generic/
  CLAUDE.md          ← общий health-coach prompt
  reminders.json     ← пусто (нет специфичных напоминаний)
  skills/            ← пусто

packs/cardiac/
  CLAUDE.md          ← фокус на ССЗ, AFib, контроль АД, adherence к антикоагулянтам
  reminders.json     ← {"08:00": "напомнить про Метформин"}
  skills/
    afib-alert.md
    bp-tracking.md

packs/bariatric/
  CLAUDE.md          ← фокус на потерю веса, поздний демпинг (Sasha-specific)
  reminders.json     ← {"21:00": "напомнить про вечерние добавки"}

packs/female-cycle/
  CLAUDE.md          ← фокус на цикл, гормоны, связь с весом/настроением
  reminders.json     ← привязка к фазе цикла
```

### 7.2 Какой pack у кого

- **Alex** → bariatric
- **Nika** → female-cycle
- **Andrey** → cardiac
- **Oleg** → новый pack `mental-health` (F21+ADHD контекст, без галлюциногенов, наблюдение за побочками психофармы)
- Дальше — `generic` по умолчанию, owner вручную меняет через админ-дашборд

### 7.3 Поле в БД

`users.pack_name` уже существует (CHECK constraint `IN ('generic','cardiac','bariatric','female-cycle')`). Нужно расширить:

```sql
ALTER TABLE users DROP CONSTRAINT users_pack_name_check;
ALTER TABLE users ADD CONSTRAINT users_pack_name_check
  CHECK (pack_name IN ('generic','cardiac','bariatric','female-cycle','mental-health'));
```

---

## 8. Longevity KB

### 8.1 Структура `docs/longevity_kb/`

```
docs/longevity_kb/
  README.md                    ← оглавление, как структурировано
  biomarkers/
    apo-b.md                   ← нормы, целевые, как снижать
    ldl.md
    fasting-glucose.md
    hba1c.md
    vit-d.md
    ferritin.md
    homocysteine.md
    crp.md
    ...
  protocols/
    attia-medicine-3-0.md      ← резюме книги, ключевые тезисы
    sinclair-longevity.md
    levine-phenoage.md
    bredesen-recode.md
  medications/
    metformin.md               ← механизм, дозировка, побочки, longevity-данные
    rapamycin.md
    statins.md
    glp1-agonists.md
  topics/
    sleep.md
    zone-2-cardio.md
    strength-training.md
    fasting.md
    sauna.md
    cold-exposure.md
```

### 8.2 Источники наполнения

- Сейчас уже есть `docs/LONGEVITY_BENCHMARKS.md` — реструктурировать по этой схеме
- AI-generated drafts по каждой теме (через Perplexity или Claude с web search) с ручной проверкой
- Сноски на первоисточники (PubMed PMID, книги, подкасты)

### 8.3 Доступ

- В боте: при conversational сообщении подключается **в system-prompt** только заголовки секций. Если агент видит что нужны детали — вызывает tool `get_longevity_reference(topic="apo-b")` и получает полный текст
- В MCP: tool `get_longevity_reference` доступен напрямую юзеру через Claude Desktop

### 8.4 Версионирование

Просто git. Pull request → review → merge. Юзеры с GitHub-доступом (Олег, Андрей, Ника, я) могут предлагать правки.

---

## 9. Privacy model

### 9.1 Контракт с юзерами

Для каждого юзера в `users.kb_status`:

| kb_status | Что значит |
|---|---|
| `shared` | Папка `Botkin/{Имя} — Здоровье/` в общем Google Drive. Alex как admin видит. AI агента видит. Используется во всех расчётах. |
| `private` | Юзер хранит свой KB **на своём маке**. Сервер не видит. AI агента видит только в личной Claude Desktop сессии юзера через локальный filesystem MCP. Логи и аналитика в боте работают без этого KB. |
| `none` | KB не подключен. Только данные из бота и интеграций. |

`private` юзеры теряют:
- KB-секции в их mc-дашборде (которые требуют knowledge_base.json) — будут пустыми или «KB не подключен»
- KB-based reminders («через 6 мес после ЭКГ — повторить»)

Это **осознанный trade-off**: больше приватности ↔ меньше функций сервер-side. Юзер компенсирует это богатой Claude Desktop сессией.

### 9.2 Что физически на сервере для private-юзеров

Только:
- Логи бота (питание, добавки, вес, АД) — это **они сами туда положили через бот**
- Apple Health / Garmin данные — синкаются по их собственному решению через личные токены
- Профиль (имя, возраст, диагнозы из chronic_conditions, лекарства) — заполнен ими на онбординге

Всё это — **их же осознанный input**. Если они не хотят делиться весом — могут не логировать.

### 9.3 RLS (минимальная)

Sprint 2 (после MVP): добавить базовый RLS:

```sql
-- Один app-роль hv_app, использует session variable
ALTER TABLE nutrition_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_isolation ON nutrition_log
  FOR ALL TO hv_app
  USING (user_id = current_setting('app.user_id', TRUE)::bigint);
-- ... аналогично для weights, supplements_log, bp, activity_log
```

В коде Tools API / MCP server:
```python
db.execute(text("SET LOCAL app.user_id = :uid"), {"uid": user.telegram_id})
```

Это защищает от ошибок в бизнес-логике (юзер случайно увидел чужие данные через баг в SQL). Не защищает от admin SELECT (Alex имеет суперюзер-доступ).

### 9.4 Audit log

Sprint 2: триггер на admin-роль `healthvault` (мой PG-юзер):

```sql
CREATE TABLE audit_log (
  id BIGSERIAL PRIMARY KEY,
  ts TIMESTAMPTZ DEFAULT NOW(),
  db_user TEXT,
  query_type TEXT,
  table_name TEXT,
  affected_user_id BIGINT,
  query_excerpt TEXT
);
```

Любой SELECT/UPDATE от admin-роли логируется. Юзеры могут запросить аудит «что Alex смотрел в моих данных».

---

## 10. Спринт-план

### 10.1 Sprint 4 — MCP server + tokens (12–22.05.2026, 10 дней)

| Задача | Файлы | Эстимейт |
|---|---|---|
| Миграция БД: `mcp_token`, `mcp_token_issued_at`, `health_token_issued_at` | `database/models.py` | 0.5 д |
| `webhook/mcp_server.py` — FastMCP scaffold с 12 tools | новый файл | 2 д |
| Bot-команды: `/health_token`, `/mcp_token` (show/rotate/revoke) | `telegram-bot/handlers/tokens.py` | 1 д |
| Mini-app UI: вкладка «Настройки» → секция «🔑 Токены» | `webapp/index.html` + `webhook/profile_api.py` | 1.5 д |
| Admin dashboard: колонка Tokens + действия | `webhook/admin.py` | 1 д |
| Cloudflare DNS: `mcp.health.orangegate.cc` → Hetzner | manual | 0.5 ч |
| Nginx/Caddy config для нового субдомена | сервер | 0.5 д |
| Smoke-test: Alex прописывает MCP в Claude Desktop, проверяет 12 tools | manual | 1 д |
| Документация: `docs/MCP_SETUP_GUIDE.md` (как юзеру подключить) | новый | 0.5 д |
| Buffer | — | 2 д |

**Итого:** 10 рабочих дней.

### 10.2 Sprint 5 — Conversational agent + packs (23.05–02.06)

| Задача | Эстимейт |
|---|---|
| `packs/generic/CLAUDE.md` + 4 cohort packs (cardiac, bariatric, female-cycle, mental-health) | 2 д |
| `pack:mental-health` для Олега (F21 + ADHD context) | 0.5 д |
| Эвристика `classify_message` + интеграция в `telegram_router.py` | 1 д |
| Conversational pipeline (load context → Claude API → response) | 2 д |
| Prompt caching через Anthropic SDK | 0.5 д |
| Тестирование на 5 active юзерах | 1 д |
| Migration: расширить pack_name CHECK до 5 значений (+mental-health) | 0.5 д |
| Buffer | 2 д |

### 10.3 Sprint 6 — Longevity KB + RLS (03–13.06)

| Задача | Эстимейт |
|---|---|
| Реструктурировать `docs/LONGEVITY_BENCHMARKS.md` → `docs/longevity_kb/` (biomarkers/protocols/medications/topics) | 1.5 д |
| AI-drafts по 20 самым нужным секциям (apo-b, ldl, fasting, sleep, etc) с ручной редактурой | 3 д |
| MCP tool `get_longevity_reference` + интеграция в conversational pipeline | 1 д |
| RLS policies на 6 data-таблицах | 1 д |
| Audit log table + триггер | 1 д |
| Smoke-test privacy isolation | 1 д |
| Buffer | 1.5 д |

### 10.4 v1.1 (после Sprint 6, по запросу)

- `mcp_access_log` для прозрачности (D9 deferred)
- Auto-expiry политики токенов
- Per-user reminder engine (scheduled jobs из reminders.json в pack'е)

### 10.5 Отложено (NanoClaw, может вернуться)

NanoClaw-инфра остаётся в БД схеме как resered columns (`container_id`, `container_port`). Может оживить когда:
- Юзеру нужна compute-изоляция (BYOK с приватным ключом)
- 30+ юзеров и общая Python-инстанция начинает тормозить
- Кому-то нужна совершенно отдельная среда (custom skills, sensitive computation)

К тому моменту инфра уже зрелая — добавить один контейнер для одного юзера, оставив остальных в monolith.

---

## 11. Что нужно от пользователей

### 11.1 От Alex (owner)

- Approve этого спека
- Дать домен `mcp.health.orangegate.cc` через Cloudflare (займусь сам когда дойдёт до Sprint 4)
- Решить: помещаем `docs/longevity_kb/` в публичный репо или приватный (KB не содержит persona data, может быть public)

### 11.2 От Олега, Ники, Андрея (коллабораторы)

- Прочитать Sprint 4 раздел этого спека
- При выходе MCP server — попробовать подключить к Claude Desktop
- Прислать feedback что не хватает в tool'ах

### 11.3 Для new юзеров (mom, dad, остальные)

- Никаких действий до Sprint 5. Текущий бот продолжает работать.
- После Sprint 5 — могут общаться с ботом как с health-coach (open вопросы).

---

## 12. Риски и митигации

| Риск | Митигация |
|---|---|
| MCP-token утечёт (вставлен в config-файл который попал в git) | Юзер ротирует через `/mcp_token rotate`. В мини-апп предупреждение «не коммить config файлы». Long-term: добавить ip-whitelist в админке |
| Conversational agent даст вредный медицинский совет | (a) Pack-prompt включает явную инструкцию «не давай диагнозы, не меняй назначения врача, при red flags → 'свяжись с врачом'»; (b) Все сообщения логируются, можно проверить пост-фактум; (c) Юзеры взрослые и подписаны на использование AI |
| Стоимость LLM растёт быстрее ожидаемой | (a) Эвристика D6 минимизирует LLM-вызовы; (b) Prompt caching снижает на 90% повторных контекстов; (c) v1.1 — лимиты на conversational сообщения в день per cohort |
| Юзеры путают MCP и HAE токены | (a) Бот при выдаче явно говорит «это для Claude Desktop» / «это для Apple Health»; (b) Разные форматы префиксов: `hvmcp_*` vs `hvhae_*` (или `hvt_*` legacy) |
| Olег не подключит MCP — спек впустую | Олег уже коммитит в репо, Claude Desktop активно использует — высокая вероятность что подключит. Если нет — MCP всё равно нужен Андрею и Нике |

---

## 13. User Documentation

### 13.1 Цель

Юзерам (Олег, Ника, Андрей, родители, будущие конференционные пользователи) нужен **сайт-гайд** который объясняет:
- Что такое Botkin и кто за этим стоит
- Как пользоваться ботом, mini-app, dashboard
- Как подключить Apple Health (HAE setup)
- Как подключить Claude Desktop MCP (для коллабораторов)
- Что приватно, что shared, как управлять токенами
- FAQ — типичные затыки

### 13.2 Источник — Markdown в репо

`docs/user_guide/ru/` — 9 файлов markdown, версионируются в git, легко править через VS Code или GitHub веб-интерфейс. Структура:

```
docs/user_guide/
  ru/
    README.md              ← index, навигация
    architecture.md        ← общая картинка + Mermaid
    telegram-bot.md
    mini-app.md
    dashboard.md
    apple-health.md
    mcp-claude-desktop.md
    knowledge-base.md
    security.md
    faq.md
  screenshots/
    README.md              ← список нужных скринов
    miniapp-diary.png
    miniapp-supps.png
    admin-dashboard.png
    ...
```

При расширении на en — добавляется `docs/user_guide/en/` с теми же файлами.

### 13.3 Хостинг — `healthvault.orangegate.cc`

Новый поддомен — публичный сайт-визитка + гайд + блог потом. Раздельно от `health.orangegate.cc` (приложение для машин) и `mcp.health.orangegate.cc` (MCP API).

**Стек:** Cloudflare Pages с auto-deploy из ветки `master`, директория `docs/user_guide/`. Конвертация markdown → HTML через **MkDocs Material** (популярный, тёмная тема, поиск, mobile-friendly, Mermaid поддержка из коробки).

Альтернатива: пишем минимальный FastAPI endpoint `/docs/` в существующем приложении с markdown-it-py + Mermaid.js. Меньше зависимостей, но больше работы. Если Cloudflare Pages + MkDocs быстро поднимается — идём туда.

### 13.4 Auth — гибрид

| Часть | Доступ |
|---|---|
| Общие разделы (Welcome, Архитектура, Бот, Mini-app, Dashboard, Apple Health, KB, FAQ) | Публично, без auth. Можно индексировать поисковиками. |
| Персональные подстановки (твой mcp_token в примере config, твой share_token в ссылке на dashboard) | Через мини-апп — там есть «Скопировать готовый конфиг» с подставленными данными |

То есть **markdown в репо — публичный**, не содержит чужих данных. Персонализация делается в мини-апп (по факту юзер сам подставляет свой токен из бота в шаблон).

### 13.5 Скриншоты

С разрешения Александра — все скрины из его данных (он публикует свои показатели открыто). Список нужных в `docs/user_guide/screenshots/README.md`. Часть уже есть (из чатов в Telegram), часть надо сделать в Sprint 4.

### 13.6 Точки входа

| Откуда | Как |
|---|---|
| **Telegram-бот** | Команда `/docs` или `/help` → бот шлёт ссылку `https://healthvault.orangegate.cc/ru/`. В welcome-сообщении после `/start`. При выпуске MCP/HAE токенов |
| **Mini-app** | Footer: «📖 Гайд / FAQ» — открывается во встроенном WebView Telegram |
| **Admin dashboard** | Шапка: «📖 User Guide» — для меня |
| **GitHub репо** | README.md в корне ссылается на гайд |

### 13.7 В Sprint 4 — что делаем

| Задача | Эстимейт |
|---|---|
| Markdown-исходники 9 разделов | ✅ **уже готово** (12.05) |
| Cloudflare DNS: `healthvault.orangegate.cc` | 0.5 ч |
| Cloudflare Pages setup: auto-deploy `docs/user_guide/` через MkDocs Material | 0.5 д |
| Скриншоты (по списку в `screenshots/README.md`) | 0.5 д |
| Команда `/docs` в боте | 0.5 ч |
| Ссылка в Mini-app footer | 0.5 ч |
| Ссылка в Admin dashboard header | 0.5 ч |

Итого +1.5 дня к Sprint 4 (раньше было 10 → теперь 11.5).

---

## 14. Готовность

После approve этого спека → переключаюсь на skill `superpowers:writing-plans` и пишу implementation plan для Sprint 4 с детальными файлами/тестами.
