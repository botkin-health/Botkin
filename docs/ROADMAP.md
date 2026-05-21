# Botkin Roadmap

> **Главная цель на сейчас:** показать проект на **FFF AI Tbilisi 28–31.05.2026**.
> **Сегодня:** 19.05.2026 — осталось **9 дней**.
>
> Этот файл — высокоуровневая карта движения. Низкоуровневые таски — в `todo.md`.
> Обновлять при каждой смене направления.

---

## 🎯 NOW — спринт до FFF Tbilisi (19–28 мая)

Что обязательно успеть, чтобы был осмысленный демо на конференции.

### Стабильность (must)
- [x] Server-side sync всех 4 источников (weather, netatmo, garmin, zepp)
- [x] Cron-задачи объединены в `sync_all.sh`
- [x] `/sync` команда в боте (admin)
- [x] Bind-mount всех .py-папок (деплой через `scp`)
- ⏸ ~~Zepp reauth~~ — отложено. Вес тянется через Apple Health → HAE → server, висцеральный жир стабилен. Не до выходных как минимум, возможно вообще откажемся от Zepp.

### AI-врач: BotkinClaw — упрощённая схема вместо NanoClaw

🔴 **NanoClaw свёрнут 21.05.2026.** Инфра (`/opt/nanoclaw`, OneCLI, systemd-юниты, docker-образы) полностью снесена с Hetzner. Освобождено 3.8 GB. См. [ADR-0002](architecture/decisions/0002-rejecting-nanoclaw-for-simpler-agent.md) и [project STATUS](projects/2026-05_nanoclaw-agent-bot/STATUS.md).

🟢 **BotkinClaw:** AI-врач = in-process handler внутри `@Botkin_md_bot` (aiogram), прямой вызов Anthropic Messages API через `core/agent_chat.py:ask_agent`, история в Postgres, tools — переиспользуем работающий `webhook/agent_tools_api.py` (JWT+RLS, **18 endpoints** на 21.05). Один бот для всех пользователей, без отдельной контейнерной инфры. Имя — игра слов NanoClaw → BotkinClaw, бот сам играет роль «контейнера» в JWT-контракте.

**Прогресс 21.05.2026:** model bump до Sonnet 4.6, JWT-контракт устойчив к NULL container_id, добавлены tools `get_weight_history`, `get_body_measurements`, `get_day_summary`, `get_indoor_air`, `get_outdoor_weather`, `get_user_settings`, `recent_workouts` теперь multi-user safe (DB fallback). TypingMiddleware для нативного индикатора. E2E ping-pong проверен 32 запросами на 2 юзерах. См. [AI_CHANGELOG](ai_context/AI_CHANGELOG.md#2026-05-21).

**TODO к FFF:** SPEC для BotkinClaw (документация архитектуры), решение по `@BotkinAgent_bot` (revoke или keep), обновление `users.agent_system_prompt` (убрать упоминания NanoClaw), provisioning `jwt_secret` для Нiki/Олег/Pavel.

### Demo-подготовка под FFF
- [ ] **Demo-сценарий** — последовательность: `/start` → лог еды → `/sync status` → `/day` → дашборд через `/share`. Записать скринкаст 2 мин. [полдня]
- [ ] **Story для FFF** — рассказ как это построено для семьи (4 active юзера, server-side sync, мульти-юзер дашборд, переезд с Mac на сервер за 2 дня).

### Биомаркеры под FFF (need)
- [ ] **PhenoAge калькулятор** — после майских анализов (15.05). Биологический возраст = одна цифра на дашборде, понятная без объяснений. [1 день]
- [ ] **DunedinPACE через Lola Health** — заказ теста сейчас, результат к FFF не успеет, но факт «уже в работе» — это сама по себе хорошая история на конференции.
- [ ] **Sport-блок мульти-юзер** — early-users видят свои HRV/Maffetone-зоны на дашборде (сейчас только Alex). [1-2 дня, см. `todo.md` v1-секция]

### Полировка (nice)
- [ ] **`/sync` для не-admin** — early-users могут запускать свои источники (требует per-user creds в БД). [1 день]
- [ ] **Sync в Claude Code + PDF→KB pipeline** — отдельный интерфейс для меня лично в IDE. Низкий приоритет, можно отложить в NEXT. [1 день]

---

## ⏭ NEXT — после FFF (июнь)

Долги и фичи, которые отложили ради конференции.

- [ ] **BotkinClaw-агенты для всей семьи** — per-user `agent_system_prompt` для papa / mama / Nika. (Старый план в NanoClaw-проекте устарел — см. ADR-0002.)
- [x] ~~**NanoClaw v0.2: write-tools**~~ — Отменено вместе с NanoClaw. Write-tools (`log_meal_text`, `log_bp`, `log_supplement`) переживают в `webhook/agent_tools_api.py` и переиспользуются BotkinClaw.
- [ ] **Per-user credentials в БД** — `garmin_email/password`, `apple_health_token` per user, OAuth для Fitbit/Whoop. [2-3 дня]
- [ ] **Google Health Connect** — интеграция для Android-юзеров (папа на Samsung). 2 подхода: Health Sync app или свой APK. [1-2 дня]
- [ ] **Локальные приватные потоки** — дневники family-cohort, Screen Time owner. Хранятся локально, личный Claude пользователя через MCP подцепляется к Botkin-серверу и комбинирует серверные данные с локальными приватными. **Test case для гибридного сетапа** «сервер + локально». [сессия]
- [ ] **Login-форма в админке** — вместо HTTP Basic (см. `todo.md`).
- [ ] **Broadcast в админке** — массовая рассылка active-юзерам.
- [ ] **Bot health metrics** — uptime, webhook latency, последние ошибки.
- [ ] **Sync в Claude Code + PDF→KB pipeline** — отдельный интерфейс для меня лично в IDE (перенесено из NOW).

---

## 🌅 LATER — лето 2026

Архитектурные апгрейды, требующие отдельной сессии.

- [ ] **Local-first вычисления на устройстве** — тяжёлые пайплайны (PDF-парсинг, корреляционный анализ, генерация инсайтов) выполняются локально на iPhone/Mac юзера, а не на сервере. Сервер — «координатор данных + API», устройство — «AI-runtime» (личный Claude через MCP). Снижает стоимость серверной части, повышает приватность. [по итогам Granola 16.05]
- [ ] **Cohort-aware BotkinClaw** — пользователи в когортах (early_users + family, посторонние = public). Per-cohort системные промпты и доступные tools. [Sprint 1a инфра уже есть]
- [ ] **Self-serve onboarding** — публичная регистрация через сайт, не только через приглашение в Telegram.
- [ ] **Audit log** — кто что менял (для прозрачности при работе вдвоём с Андреем).
- [ ] **CGM (FreeStyle Libre 3 Plus)** — 2-недельный протокол интеграции с дашбордом. [`todo.md`]
- [ ] **Centenarian Decathlon** — функциональные тесты долголетия (Аттиа), квартальный лог в боте.

---

## 🚀 VISION — осень 2026 и дальше

Цели верхнего уровня, без сроков.

- **Открытый продукт** — paid tier (BYOK или подписка) когда расходы превысят $100/мес или станет 50+ юзеров. Сейчас open-source без коммерции.
- **Доклад / выступление** — после FFF Tbilisi, потенциально другие конференции (Welltory-style aud).
- **Семейный mesh** — у каждого свой бот в семье, общая Knowledge Base, MCP-агент видит всю семью при разрешении.
- **API for клиник / wellness-программ** — managed deployment для B2B клиентов (упоминается на лендинге как business audience).
- **Биологический возраст по семейному паттерну** — Genealogy-aware pipeline (главное конкурентное преимущество, обсуждалось с экспертом female-health).

---

## ✅ DONE — прошлые недели

Хронологически. Чтобы было видно скорость и не повторять.

### 12–13 мая (ребрендинг + базовая инфраструктура)
- Ребрендинг HealthVault → Botkin (бот, README, CLAUDE.md, лендинг botkin.health)
- Webhook auto-register hotfix
- Удалён старый репо NutriLogBot
- SemVer (v0.4.0, v0.5.0) + bump-скрипт + RELEASING.md
- Сообщения о миграции отправлены 4 active-юзерам
- MCP-конфиг почищен (healthvault удалён, instagram токен зашит, garmin реавторизован)

### 17–19 мая (server-side sync)
- 4 источника на сервере: weather, netatmo, garmin, zepp (direct API mode)
- Объединены в `sync_all.sh`, один cron в 04:05 UTC, единый лог
- `/sync` команда в боте: `/sync`, `/sync <source>`, `/sync status`
- Bind-mount всех .py-папок (deploy = scp + restart, без docker cp)
- `lnetatmo` в requirements.txt (hotfix после force-recreate)
- 5 PR merged (#6, #7, #8, #9, #10 ROADMAP, #11 NanoClaw roadmap update)

### 19 мая (NanoClaw попытка → откат → research)
- 🔴 Построен `botkin-agent:v0.1` (Python FastAPI + Claude SDK, persistent per user) — повторил obsolete-подход из 11.05
- 🛠 Заметили проблему когда Alex дважды не получил ответа от бота на `привет, кто ты?`
- 🔧 Webhook chain repair: добавлен port 8081 в `docker-compose.prod.yml` (потерян при `--force-recreate` 18.05)
- ↩️ Полный откат: контейнер `botkin-agent-alex` удалён, image удалён, сервис закомментирован, ALEX_JWT_SECRET убран
- 📄 Создан [ADR-0001](architecture/decisions/0001-nanoclaw-ephemeral-not-persistent.md) — полная история решений (04.05 → 11.05 → 19.05) + правила «как не повторить»
- 📌 Ветка `feat/nanoclaw-agent-v0.1` НЕ мержится в main — оставлена как experimental/historical

### 19–20 мая (NanoClaw правильный deploy → Phase 1-3 ✅)
- 🟢 Поднят NanoClaw v2.0.64 на Hetzner (`/opt/nanoclaw/`, systemd)
- 🟢 OneCLI vault (Anthropic key + per-agent token gateway)
- 🟢 Telegram long-polling adapter, agent group "Alex"
- 🟢 MCP server "botkin" с 7 tools → реальные данные Alex из Postgres через JWT
- 🟢 Health context CLAUDE.local.md (семейный анамнез, текущие цифры, цели)
- 🟢 Auto-chown systemd timer (фикс readonly-db после restart)
- 📄 Документация в [`docs/projects/2026-05_nanoclaw-agent-bot/`](projects/2026-05_nanoclaw-agent-bot/): STATUS, SPEC, PLAN, QUESTIONS_FOR_ALEX

---

## 📌 Принципы поддержки этого файла

- **NOW** — то что в активной работе **на этой неделе**. Максимум 5-7 пунктов.
- **NEXT** — то что начнём **в течение месяца**. Должно быть честно достижимо.
- **LATER** — идеи без deadline, проверенные на ценность.
- **VISION** — куда движемся, без сроков.
- **DONE** — хронологически, для скорости видна.

При завершении пункта в NOW — перенести в DONE (с датой). Если NOW пустеет — взять из NEXT.
