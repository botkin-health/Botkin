# Plan: NanoClaw Agent Bot — phases 4+

> Phase 1-3 — выполнено 20.05.2026, см. STATUS.md.
> Этот файл — что делать дальше, в каком порядке, с какими acceptance.

## Сейчас работает (baseline)

@BotkinAgent_bot принимает сообщения, агент Alex отвечает по контексту из `groups/alex/CLAUDE.local.md`, может вызывать 7 tools через MCP-server `botkin`:
- Read: `get_user_profile`, `get_dashboard_summary`, `get_recent_meals`, `get_kb_value`
- Write: `log_meal_text`, `log_bp`, `log_supplement`

Память между сессиями работает (Claude SDK session persistence).

## Phase 4 — Доводка для FFF Tbilisi (до 28.05)

### 4.1 Полировка ответов (нужно тестирование)

Запустить серию тест-вопросов и оценить качество:
- «Как я в этом месяце?»
- «Что у меня с давлением?» (вероятно `kb_value` не имеет такого ключа — нужно проверить)
- «Я ел сегодня курицу и рис, запиши»
- «Какие у меня анализы крови были последние»
- «Какой риск ССЗ у меня в моём возрасте?»

Acceptance: 5/5 вопросов → агент даёт осмысленный ответ с реальными данными.

### 4.2 Расширить tools API (если выявит тесты 4.1)

Добавить в `webhook/agent_tools_api.py` недостающие endpoints:
- `get_recent_bp(days)` — последние замеры АД из `blood_pressure_logs`
- `get_sleep_summary(days)` — сон из `activity_log` или плоских файлов Apple Health
- `get_supplements_history(days)` — что и когда принимал
- `get_food_summary(date)` — детальный день еды
- `get_biomarkers_latest` — свежие анализы крови (KB)
- `get_family_health_context` — папин и мамин risk-факторы (из FamilyHealth/, если допустимо)

Каждый новый endpoint + tool в MCP server `groups/alex/skills/botkin/server.ts`.

### 4.3 Demo-скринкаст

Записать 2-минутное видео:
1. `/start` в @BotkinAgent_bot
2. Спросить «как мои дела»
3. Залогировать давление голосом или текстом
4. Спросить контекст «какие у меня семейные риски»
5. Показать что в @Botkin_md_bot отдельно работает food logging через фото

## Phase 5 — После FFF (июнь)

### 5.1 Per-user CLAUDE.local.md для семьи

Создать agent groups «papa», «mama», «nika» с per-user health context:
- `ncl groups create --name "Papa" --folder "papa"` (с правильным `ag-` ID!)
- INSERT в `container_configs` с дефолтными значениями
- `POST /api/agents` в OneCLI с identifier=agent_group_id
- Написать `groups/papa/CLAUDE.local.md` с контекстом папы (из `FamilyHealth/Павел Храпкин — Здоровье/`)
- Сгенерить JWT для папы (user_id=papa_telegram_id, container_id=`nanoclaw-papa`, ...)
- Скопировать MCP server config из Alex'а, заменить BOTKIN_JWT
- Создать `messaging_groups` + wiring когда папа напишет первое сообщение в @BotkinAgent_bot

**Open question:** один бот @BotkinAgent_bot для всей семьи или по боту на юзера? Сейчас messaging-group привязан к `telegram:<chat_id>`, так что один бот может обслуживать всех — wiring per-chat. Скорее один бот.

### 5.2 Write tools polish

Сейчас агент может логировать но осторожно — нужно настроить промпт чтобы он чаще предлагал «записать?» а не молча действовал. Также:
- Voice→text: NanoClaw сам не принимает voice, нужно либо парсить ввод как голосовое в Telegram adapter, либо ждать пока @Botkin_md_bot пришлёт текст
- Photo еды: то же — пока агент не работает с photo. Может перенаправлять «фото шли в @Botkin_md_bot для точного парсинга»

### 5.3 Subagents и долгие задачи

NanoClaw v2 поддерживает subagent spawning. Можно сделать:
- Утренний summary («что у тебя за вчера»)
- Анализ долгих трендов (corr вес ↔ ккал за месяц)
- Quarterly check-in («сравни этот месяц с прошлым»)

### 5.4 Memory polish

NanoClaw сохраняет per-session memory. Можно добавить explicit memory tools (`save_to_memory`, `recall_memory`) или использовать MCP memory server.

## Phase 6 — Vision (осень 2026)

См. `CLAUDE.md` → Vision-секция. Гибридная архитектура: server + local MCP.

## Tech debt (всё что нужно когда-нибудь почистить)

| Что | Приоритет | Решение |
|---|---|---|
| chown через systemd timer 30 сек — не идеально, лаг | низкий | Использовать inotify-tools, или запустить NanoClaw под uid 1000 (нужен docker group), или запатчить NanoClaw на post-create chown |
| JWT TTL 1 год хранится в plain ENV — не лучший вариант | средний | Положить в OneCLI vault как secret типа `botkin-agent`, MCP server читает из OneCLI |
| Ключ Anthropic API передан в чат у Alex (см. историю) | НИЗКИЙ — Alex решил не менять | Со временем ротация |
| Docker `healthvault_bot` healthcheck падает (pgrep not found) | низкий | Отдельный spawn-task уже создан |
| Диск 90% (3.7 GB free) — постепенно растёт | средний | Регулярный prune (cron weekly) |
| Mac install nanoclaw-spike остался в `~/nanoclaw-spike` | низкий | Можно удалить, но не мешает |
| `ncl groups create` создаёт «неправильный» UUID — мы делали ручкой UPDATE и chown | средний | PR в upstream nanocoai/nanoclaw чтобы create использовал `ag-` префикс |
| `~/.onecli/credentials/lyskovsky@gmail.com.json` cache — должен ротироваться при смене ключа | низкий | Документ для ротации |

## Когда папа онбордится

Шаги (см. также Phase 5.1):
1. Получить от папы Telegram username/chat_id (когда он сам напишет в @BotkinAgent_bot, мы получим)
2. `ncl groups create` → ручной фикс ID → container_configs → OneCLI agent → CLAUDE.local.md → wiring
3. JWT для папы по его user_id из healthvault.users
4. Скопировать `groups/papa/skills/botkin/` (тот же MCP server template, новый JWT)
5. CLAUDE.local.md под папу — более простой, без техдеталей, упор на BP / медикаменты / симптомы
6. Контекст из `FamilyHealth/Павел Храпкин — Здоровье/PROFILE.md`

## Открытые вопросы (для Alex)

См. `QUESTIONS_FOR_ALEX.md` в этой же папке.
