# Botkin Roadmap

> **Сегодня:** 07.06.2026.
> **FFF AI Tbilisi (28–31.05.2026)** — прошёл ✅ (был главной целью предыдущего спринта).
>
> Этот файл — высокоуровневая карта движения. Низкоуровневые таски — в Notion
> (`todo.md` убран из публичного репо 04.06.2026, коммит `fbb3aab`).
> Обновлять при каждой смене направления.
>
> ⚠️ **Актуализация 07.06.2026 (черновик, Igor):** ROADMAP не обновлялся с 24.05, за это время
> в `main` влилось ~160 коммитов. Ниже секция **DONE** приведена в соответствие с git-историей,
> а в **NOW/NEXT** проставлены фактические статусы. Текущие приоритеты **NOW** требуют
> подтверждения владельца — оперативный todo живёт в Notion, не здесь.

---

## 🎯 NOW — после FFF (июнь)

> Требует подтверждения владельца (источник истины — Notion). Ниже — то, что видно как
> открытое/в работе по git и issues на 07.06.

- [ ] **ВкусВилл MCP → BotkinClaw** — профиль-aware подбор продуктов + корзина. [issue #38, открыт 03.06]
- [ ] **Финальный рефактор имён HealthVault → Botkin** — БД, папки на сервере (`/root/healthvault`),
      legacy-инфра. Бренд переехал, инфра частично на старом имени. [из Notion-todo]
- [ ] **Переезд legacy-домена** `health.orangegate.cc` → `botkin.health`. [из Notion-todo]

---

## ⏭ NEXT — лето 2026

Долги и фичи, отложенные ради конференции.

- [ ] **BotkinClaw-агенты для всей семьи** — per-user `agent_system_prompt`. *Частично:* онбординг-пайплайн
      готов, подключены Андрей, Павел, Дмитрий, папа (май–июнь). Осталось довести промпты mama / Nika.
- [x] ~~**NanoClaw v0.2: write-tools**~~ — отменено вместе с NanoClaw. Write-tools (`log_meal_text`,
      `log_bp`, `log_supplement`, `edit_meal`, `delete_meal`) живут в `webhook/agent_tools_api.py`.
- [ ] **Per-user credentials в БД** — `garmin_email/password`, `apple_health_token` per user.
      *Частично:* Whoop OAuth (мультиюзер) сделан 04.06. Осталось Garmin/Apple per-user, Fitbit OAuth.
- [ ] **Google Health Connect** — интеграция для Android-юзеров (папа на Samsung). Решение:
      [`mcnaveen/health-connect-webhook`](https://github.com/mcnaveen/health-connect-webhook) — Kotlin APK,
      24 типа данных, POST на URL. На стороне Botkin — `telegram-bot/webhook/android_health.py` +
      эндпоинт `/android_health_v1`. Ждём готовности папы. Ресёрч:
      `docs/research/2026-05-22_android-health-connect-export-webhook.md`. [2-3 часа]
- [ ] **Локальные приватные потоки** — дневники family-cohort, Screen Time owner. Локальное хранение,
      личный Claude через MCP комбинирует серверные + локальные данные. Test case гибридного сетапа. [сессия]
- [ ] **Login-форма в админке** — вместо HTTP Basic. *Частично:* cookie-сессия «запомнить меня»
      добавлена 06.06; полноценную форму логина ещё нет.
- [ ] **Broadcast в админке** — массовая рассылка active-юзерам.
- [ ] **Bot health metrics** — uptime, webhook latency, последние ошибки.
- [ ] **Sync в Claude Code + PDF→KB pipeline** — отдельный интерфейс для владельца в IDE.
- [ ] **Health Reports** — авто-отчёты по здоровью: HTML по шаблону, `/report` в боте + BotkinClaw tool
      `generate_report`, доступ по JWT-ссылке, версии сохраняются, PDF = `window.print()` на клиенте.
      Стек: `services/report_generator.py` (matplotlib → base64 PNG → Jinja2 → HTML),
      таблица `health_reports`, эндпоинт `GET /r/{token}`. [3-5 дней]

### Продукт / бренд (из Notion-todo, проектного уровня)
- [ ] **Полноценный онбординг нового пользователя** — самостоятельная интеграция девайсов,
      Apple/Google Health, подгрузка анализов.
- [ ] **Локализация EN + HE** — сайт, интерфейс, отчёты (нужно для Игоря, Тель-Авив).
- [ ] **Лендинг / маркетинг** — доработать botkin.health (waitlist, Sponsor), обновить скриншоты,
      логотип, проектный email `hello@botkin.health`, донаты (Open Collective + GitHub Sponsors).
- [ ] **Anthropic Startups Program** — заявка на бесплатные API-кредиты (через VC-партнёра).

---

## 🌅 LATER — осень 2026

Архитектурные апгрейды, требующие отдельной сессии.

- [ ] **Local-first вычисления на устройстве** — тяжёлые пайплайны (PDF-парсинг, корреляции, инсайты)
      на iPhone/Mac юзера, а не на сервере. Сервер — «координатор данных + API», устройство — «AI-runtime»
      (личный Claude через MCP). Снижает стоимость сервера, повышает приватность. [по итогам Granola 16.05]
- [ ] **Cohort-aware BotkinClaw** — per-cohort системные промпты и tools (early_users + family vs public).
      [инфра Sprint 1a есть]
- [ ] **Self-serve onboarding** — публичная регистрация через сайт, не только инвайт в Telegram.
- [ ] **Audit log** — кто что менял (прозрачность при работе вдвоём с Андреем).
- [ ] **CGM (FreeStyle Libre 3 Plus)** — 2-недельный протокол интеграции с дашбордом.
- [ ] **Centenarian Decathlon** — функциональные тесты долголетия (Аттиа), квартальный лог в боте.
- [ ] **DunedinPACE через Lola Health** — заказан к FFF, дождаться результата и вывести на дашборд.

---

## 🚀 VISION — зима 2026 и дальше

Цели верхнего уровня, без сроков.

- **Открытый продукт** — paid tier (BYOK или подписка), когда расходы превысят $100/мес или станет 50+ юзеров.
  Сейчас open-source без коммерции (трек запущен 21.05: AGPL-3.0 + open-core позиционирование).
- **Доклад / выступление** — после FFF Tbilisi, потенциально другие конференции.
- **Семейный mesh** — у каждого свой бот, общая Knowledge Base, MCP-агент видит всю семью при разрешении.
- **API для клиник / wellness-программ** — managed deployment для B2B (бизнес-аудитория на лендинге).
- **Биологический возраст по семейному паттерну** — genealogy-aware pipeline (ключевое конкурентное
  преимущество, обсуждалось с экспертом female-health).

---

## ✅ DONE — прошлые недели

Хронологически. Чтобы было видно скорость и не повторять.

### 21 мая – 6 июня (после FFF: BotkinClaw в проде, биомаркеры, open-core)
Сводно по git (~160 коммитов). Ключевые темы:

- **BotkinClaw в проде** — единый `@Botkin_md_bot` отвечает на вопросы через Claude API (path X, #16),
  markdown→Telegram HTML, retry/fallback (Sonnet 4.5/4.6 ↔ Opus 4.8, выбор по стоимости),
  множество tools: `phenoage`, `recent_workouts`, `recent_trends`, `get_recent_supplements`,
  `get_user_settings`, `get_indoor_air`, `get_outdoor_weather`, write-эндпоинты (settings, анкета),
  `edit_meal`/`delete_meal` (P-001), `get_open_questions`. JWT устойчив к NULL container_id.
- **Биомаркеры — унификация pipeline** — единый канонический реестр `core/health/kb_schema.py`
  (алиасы + конверсия единиц с guard), `aggregate_biomarkers`, дашборд читает из Postgres
  (durable при rebuild), golden-regression тесты, PhenoAge, расширение реестра (CBC/коагуляция/гормоны/витамины).
- **Онбординг семьи** — CLI-оркестратор `scripts/onboard_family_user.py` + reusable pipeline
  (snapshot/rollback, persona-генератор, KB-валидатор, welcome-sender), подключены Андрей, Павел,
  Дмитрий, папа; Igor onboarding (`feature/igor-onboarding`).
- **Server-side независимость от Mac** — Postgres backfill workouts/sleep/HRV, `/sync pg_sync`.
- **Лендинг** — 30+ правок, AI-врач framing, реальные скриншоты дашборда, AGPL/open-core
  позиционирование, FAQ, redesign галереи, BotkinClaw на диаграмме архитектуры, миграция `/mc/` на домен.
- **Админка** — per-purpose LLM cost tracking, человекочитаемые лейблы, округление расходов,
  cookie-сессия «запомнить меня».
- **Open-core монетизация** — запуск трека: AGPL-3.0, README header под open-core.
- **CI / качество** — GitHub Actions (pytest + ruff, #33), night-shift skill + статанализ
  (bandit, vulture), worktrees для изоляции.
- **Безопасность / приватность** — вычистка PII и секретов из публичного репо (несколько проходов),
  gitleaks в pre-commit, фиксы из night-shift аудита, ssh-по-ключу вместо sshpass.
- **Whoop** — мультиюзерная OAuth-интеграция (sleep/recovery/HRV/strain), 04.06.
- **Бэкапы** — offsite в Google Drive + GFS-ротация + авто-тест восстановления, 06.06.
- **Еда** — логгер понимает относительную/явную дату (#37), фиксы роутера фото/текст/BP.

### 19–20 мая (NanoClaw → откат → BotkinClaw)
- 🔴 NanoClaw свёрнут 21.05: инфра (`/opt/nanoclaw`, OneCLI, systemd, docker-образы) снесена с Hetzner
  (−3.8 GB). См. [ADR-0002](architecture/decisions/0002-rejecting-nanoclaw-for-simpler-agent.md).
- 🟢 Решение: AI-врач = in-process handler в `@Botkin_md_bot` (BotkinClaw), tools через
  `webhook/agent_tools_api.py` (JWT+RLS). См. [ADR-0001](architecture/decisions/0001-nanoclaw-ephemeral-not-persistent.md).
- Ветка `feat/nanoclaw-agent-v0.1` НЕ мержится в main — оставлена как experimental/historical.

### 17–19 мая (server-side sync)
- 4 источника на сервере: weather, netatmo, garmin, zepp (direct API). Объединены в `sync_all.sh`,
  один cron 04:05 UTC. `/sync` команда в боте. Bind-mount всех .py-папок (deploy = scp + restart).
- 5 PR merged (#6–#11).

### 12–13 мая (ребрендинг + базовая инфраструктура)
- Ребрендинг HealthVault → Botkin (бот, README, CLAUDE.md, лендинг botkin.health).
- Webhook auto-register hotfix, удалён старый репо NutriLogBot, SemVer + RELEASING.md.
- Сообщения о миграции 4 active-юзерам, чистка MCP-конфига.

---

## 📌 Принципы поддержки этого файла

- **NOW** — то что в активной работе **на этой неделе**. Максимум 5-7 пунктов.
- **NEXT** — то что начнём **в течение месяца**. Должно быть честно достижимо.
- **LATER** — идеи без deadline, проверенные на ценность.
- **VISION** — куда движемся, без сроков.
- **DONE** — хронологически, для скорости видна.

При завершении пункта в NOW — перенести в DONE (с датой). Если NOW пустеет — взять из NEXT.
