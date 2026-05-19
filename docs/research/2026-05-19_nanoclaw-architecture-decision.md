# NanoClaw — архитектурное решение и история

**Дата:** 2026-05-19
**Автор:** Claude + Александр Лысковский
**Статус:** живой документ, обновлять при изменениях
**Связано:**
- `docs/superpowers/specs/2026-05-04-cohort-agents-design.md` — оригинальная спека
- `docs/superpowers/plans/2026-05-04-cohort-agents-sprint-1a.md` — Sprint 1a (выполнен)
- `docs/superpowers/plans/2026-05-06-cohort-agents-sprint-1b.md` — Sprint 1b (помечен OBSOLETE)

---

## TL;DR

- **Что такое NanoClaw:** open-source Node.js host-оркестратор от [@qwibitai](https://github.com/qwibitai/nanoclaw), MIT license, ~3,900 строк. Запускает **эфемерные spawn-контейнеры per session** (не persistent containers per user) с Claude Agent SDK внутри. Координация host ↔ container через SQLite inbound/outbound DB. Поддерживает Telegram, WhatsApp, Slack, Discord.
- **Решение 11.05.2026:** интегрировать с NanoClaw — но **позже**, после cleanup + multi-user hardening. Sprint 1b plan (persistent containers per user) помечен OBSOLETE.
- **Решение 19.05.2026:** при попытке снова поднять «agent container per user» (`botkin-agent:v0.1`) повторили obsolete подход. Откатили (см. секцию «Эпизод 19.05»). Новый Sprint 1b plan под правильную архитектуру — после FFF Tbilisi.

---

## 1. Что такое NanoClaw

**Репозиторий:** https://github.com/qwibitai/nanoclaw
**Лицензия:** MIT
**Стек:** Node.js (host), Bun (containers), SQLite, Claude Agent SDK

### Архитектурная модель

```
messaging app  →  host process (router)  →  inbound.db
                                             ↓
                                    container (Bun, Claude Agent SDK)
                                             ↓
                                          outbound.db
                                             ↓
                            host process (delivery)  →  messaging app
```

**Single Node host** управляет:
- Routing сообщений к сессиям (`src/router.ts`)
- Lifecycle контейнеров (`src/container-runner.ts`)
- Delivery ответов обратно в мессенджер (`src/delivery.ts`)
- Periodic maintenance (`src/host-sweep.ts`, каждые 60с — stale detection, scheduled tasks)

**Per-session containers** — эфемерные, spawn'ятся по запросу:
- Bun runtime + Claude Agent SDK
- Mount только разрешённых директорий
- Каждая сессия = своя пара `inbound.db` + `outbound.db` (single-writer, без contention)
- Polling SQLite вместо IPC/stdin

### Hierarchy (entity model)

`user → messaging group → agent group → session`

- **Agent group** — единица персистентности. У каждой:
  - Свой `CLAUDE.md` (system prompt)
  - Своя `memory/` (history across sessions)
  - Свой контейнер (spawn'ится при активности)
  - Свои custom mounts (что доступно агенту)

### Security модель

- Контейнеры **НЕ хранят** API ключи
- Креды injected через **OneCLI Agent Vault** на proxy-слое
- Policy enforcement централизованно

### Channels (multi-platform)

- Установка on-demand через `/add-<channel>` skills
- Native поддержка: Telegram, WhatsApp, Slack, Discord
- Webhook vs polling — depends on adapter implementation

---

## 2. История решений

### 04.05.2026 — Sprint 1a spec (cohort-agents-design)

В оригинальной спеке (см. §6 «NanoClaw-контейнеры») планировалось:

- **Persistent container per user** (`nc-sasha`, `nc-andrey`, `nc-nika`, ...)
- Pack-based архитектура: `packs/cardiac/`, `packs/bariatric/`, `packs/female-cycle/`
- Каждый pack = `CLAUDE.md` + `skills/` + `scheduled-jobs.json`
- Tool API: HTTP REST с JWT (`/api/agent/*` endpoints)
- Telegram router форвардит payload в контейнер по `users.container_id`

**Дедлайн:** 14.05 (Андрей получает Withings + Libre 2).

**Sprint 1a задачи (DONE):** колонки в БД (`cohort`, `container_id`, `container_port`, `pack_name`, `jwt_secret`), RLS-политики, JWT-auth, 8 endpoints в `/api/agent/*`, telegram_router, audit_log. Полностью реализовано на main к 04.05.

### 11.05.2026 — глубокое погружение в NanoClaw, разворот

После изучения [github.com/qwibitai/nanoclaw](https://github.com/qwibitai/nanoclaw) **обнаружили принципиальную разницу** с тем как мы планировали:

| Параметр | Наш план 04.05 | Реальный NanoClaw |
|---|---|---|
| Контейнеры | persistent per user | **ephemeral spawn per session** |
| Координация host ↔ container | HTTP + JWT | **SQLite inbound/outbound DB** |
| State между sessions | в контейнере | **в host-managed memory/** |
| Maintenance loop | нет | **host-sweep каждые 60с** |
| API credentials | в контейнере (env) | **никогда не в контейнере, через vault** |
| Lifecycle | docker-compose `restart: always` | **spawn on demand, sleep otherwise** |
| Один процесс | aiogram + FastAPI | **отдельный host orchestrator (Node)** |

**Sprint 1b plan помечен OBSOLETE** с комментарием:
> «Sprint 1b plan предлагал реализацию на Python Claude Agent SDK с docker-сервисом per-user (24/7). После изучения NanoClaw выяснилось, что правильная архитектура — host-процесс + эфемерные spawn-контейнеры per session.»

**Что выбрали 11.05:** не интегрировать с NanoClaw срочно (это полпереписи). Андрей онбордится через legacy путь (расширенный onboarding + multi-user dashboard). Возврат к агентам — после cleanup и multi-user hardening.

### 14.05.2026 — Андрей в проде без агента

Андрей и Ника подключены через расширенный legacy путь (HAE webhook, multi-user dashboard, sport-блок). Все ✅, без NanoClaw / cohort-agent.

### 19.05.2026 — эпизод повторного отклонения от плана

**Что произошло:**
- В свежей сессии 19.05 при работе над server-side sync миграцией всплыла тема NanoClaw из roadmap
- Claude (я) **не дочитал** `docs/superpowers/plans/2026-05-06-cohort-agents-sprint-1b.md` с пометкой OBSOLETE
- Построил `botkin-agent:v0.1` — Python FastAPI контейнер с Claude SDK, **persistent per user** (`botkin-agent-alex`)
- Это **точно тот OBSOLETE подход**, который мы отвергли 11.05
- Прежде чем замерили реальную работу с Telegram — пользователь сам спросил «А у нас уже развернут nanoclaw последней версии?»

**Что выяснили после вопроса:**
- Granola-транскрипт 16.05 упоминал «Monoclo» (вероятно, опечатка/слыхотворение для какого-то аналога), не NanoClaw
- Существующая спека и план 04–06.05 **явно отметили** что правильная архитектура — эфемерные spawn-контейнеры
- Наш `botkin-agent:v0.1` — обратный подход

**Что откатили:**
- `UPDATE users SET container_id=NULL, container_port=NULL WHERE telegram_id=895655` — Alex обратно на legacy aiogram
- `botkin-agent-alex` контейнер остановлен и удалён (компоуз-сервис закомментирован)
- `nanoclaw-agent/` директория помечена как experimental в README
- Ветка `feat/nanoclaw-agent-v0.1` **не мержится** в main — оставлена как историческое свидетельство

**Уроки:**
1. **Перед любой новой архитектурной работой** — прочитать ВСЕ `docs/superpowers/specs/` и `docs/superpowers/plans/`. Особенно с пометкой OBSOLETE — там понимание ЧТО не работает.
2. **Sprint 1b plan уже написан с верным TL;DR на верху** — header стал бы предупреждением, если бы Claude сначала открыл его.
3. **«Nanoclaw» в `requirements.txt` комментарии и Sprint 1a коде** — это исторический артефакт 04.05, не индикатор что текущая архитектура верна. Не повторять без проверки.

---

## 3. Что дальше — план под правильную архитектуру

Не приоритет до FFF Tbilisi (28–31.05.2026). После FFF:

### Sprint 1b (новый, переписать с нуля)

**Цель:** интегрировать настоящий NanoClaw как host-оркестратор для Botkin.

**Архитектура:**
- На Hetzner запускаем NanoClaw host-процесс (Node.js, отдельный контейнер `botkin-nanoclaw-host`)
- Telegram webhook продолжает идти на `healthvault_bot` (текущий aiogram); telegram_router определяет если для юзера должен быть агент → форвардит на NanoClaw host через локальный API/socket
- NanoClaw сам spawn'ит ephemeral container per session, использует SQLite для коммуникации
- Agent group per user (Alex / Ника / Андрей / Олег) с собственными `CLAUDE.md` + memory + custom mounts
- Tools у агента = наши `/api/agent/*` через OneCLI Agent Vault (credential injection)

**Open questions для нового плана:**
1. Запускать ли NanoClaw host в Docker или нативно на хосте? (NanoClaw expects macOS/Linux + Node.js 20+ + container runtime)
2. Как телеграм-router интегрируется с NanoClaw API? Есть ли у NanoClaw REST для inbound messages, или подключаем через `/add-channel` skill?
3. Где хранится агент-память — bind mount `/opt/botkin/nanoclaw/agents/`? Backup-стратегия?
4. Credential vault — нужен ли OneCLI на нашем сервере, или можно проще?
5. Стоимость API: у нас один общий `ANTHROPIC_API_KEY` или per-user BYOK как в Sprint 2 спеке?

**Не делать пока:**
- Не строить «свой Claude SDK runtime» с нуля — это уже сделали и откатили
- Не делать persistent containers per user — это явно отвергнутый подход

**Time estimate:** 2-3 дня под FFF Tbilisi если решим что NanoClaw нужен для демо. Иначе после FFF — 3-5 дней без спешки.

---

## 4. Артефакты которые НЕ удалять

- `docs/superpowers/specs/2026-05-04-cohort-agents-design.md` — спека всё ещё актуальна по большинству пунктов (RLS, JWT, tools API). Только §6 (NanoClaw containers) нужен пересмотр под эфемерные spawn.
- `docs/superpowers/plans/2026-05-04-cohort-agents-sprint-1a.md` — выполнено, осталось как историческая запись.
- `docs/superpowers/plans/2026-05-06-cohort-agents-sprint-1b.md` — **OBSOLETE**, но сохраняем как «история мышления».
- `nanoclaw-agent/` (моя реализация 19.05) — помечено DEPRECATED в README. Не удалять — образец того как НЕ надо.
- Ветка `feat/nanoclaw-agent-v0.1` — не мержить в main, оставить.
- В коде `webhook/jwt_auth.py`, `webhook/agent_tools_api.py`, `webhook/telegram_router.py` — всё ещё нужны для будущего Sprint 1b (правильного). RLS и tools API универсальны, не зависят от выбора NanoClaw vs custom.

---

## 5. Чек-лист для будущего Claude (или меня в следующей сессии)

При работе над cohort-agents / NanoClaw / "agent в Telegram":

- [ ] Прочитать **этот файл** целиком (`docs/research/2026-05-19_nanoclaw-architecture-decision.md`)
- [ ] Прочитать `docs/superpowers/specs/2026-05-04-cohort-agents-design.md` целиком
- [ ] Открыть `docs/superpowers/plans/2026-05-06-cohort-agents-sprint-1b.md` и увидеть OBSOLETE-предупреждение на верху
- [ ] **НЕ строить persistent container per user** — это отвергнутый подход
- [ ] При новой работе — сначала открыть GitHub NanoClaw, посмотреть текущую версию (репо может развиваться)
- [ ] **НЕ мержить** `feat/nanoclaw-agent-v0.1` в main — это experimental
