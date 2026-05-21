# Botkin Project: Status & Roadmap

> **💡 Context**: Этот файл — единый источник правды о состоянии проекта. Начинай работу с чтения этого файла.

---

## 🔧 Архитектурные долги (отложено — пересмотрим когда поднакопится)

- [ ] **HealthVault → Botkin: финальный рефактор имён.** Бренд переехал 12.05.2026, но внутри инфры/кода старое имя осталось. Делается одним блоком, не по кускам — иначе будут гонки между обновлёнными и старыми частями. *Добавлено 20.05.2026.*

  **5 шагов (с downtime ~5-10 мин):**
  1. **Имя БД на сервере** `healthvault` → `botkin`: `pg_dump healthvault | psql botkin` на Hetzner, обновить `DATABASE_URL` в `.env.production`, перезапустить bot. Старую БД оставить на неделю, потом DROP.
  2. **Папка на сервере** `/opt/healthvault` → `/opt/botkin`: остановить systemd-сервис, `mv`, обновить unit-file path, cron-задачи, nginx vhost, `deploy.sh` на маке. Symlink `/opt/healthvault → /opt/botkin` на пару недель для обратной совместимости.
  3. **Dev-контейнер postgres** `healthvault_postgres_dev` → `botkin_postgres_dev` в `docker-compose.dev.yml`. Compose-project (`healthvault`) НЕ трогать — потеряем volume и данные dev-БД. `docker compose -f docker-compose.dev.yml down && up -d` — имя обновится, volume сохранится.
  4. **MCP-сервер** `scripts/mcp/healthvault_mcp.py` → `botkin_mcp.py` + обновить `~/Library/Application Support/Claude/claude_desktop_config.json` (MCP-сервер `healthvault` → `botkin`). MCP отвалится на момент правки конфига, нужен restart Claude Desktop.
  5. **Code references** в ~30 файлах (`database/`, `config/`, `core/`, `telegram-bot/`, `scripts/`): имена переменных, log-строки, комментарии, ENV-переменные `HEALTHVAULT_*` → `BOTKIN_*` если есть. Find-replace + smoke-тест бота локально + прогон тестов.

  **План проверки (smoke):** `/sync` отрабатывает · бот отвечает на /start · `/dashboard` показывает данные · бэкап в новой папке создаётся.

  **Не трогать в этом рефакторе:** `data/backups/healthvault_backup_*.sql` (история), GD-папка `FamilyHealth/` (по дизайну остаётся HealthVault — см. CLAUDE.md), `.claude/worktrees/` (Claude Code сам прибирает).

  **Долг от 20.05.2026 (мелкий, не блокер):** в 6 скриптах захардкожен путь `/Users/alexlyskovsky/HealthVault/...` через старый симлинк: `tests/smoke_test.py`, `scripts/analysis/bp_correlations.py`, `scripts/apple-health/{process_export,_execute_update,_run_processing,update_apple_health}.py`. Симлинк `~/HealthVault` пришлось восстановить рядом с `~/Botkin`, чтобы скрипты не сломались. В рамках финального рефактора — заменить на `Path.home() / "Botkin" / ...` или относительные пути от `__file__`, и снести симлинк `~/HealthVault`.
- [ ] **Метрика Z2/Maffetone aerobic baseline** — сейчас в `data/z2_baseline.json` (append-only JSON, см. `scripts/analysis/z2_baseline.py`). Когда наберётся 5-10 точек — перенести в PostgreSQL как таблицу `sport_metrics` (user_id, date, activity_id, pace_at_target_hr, avg_hr, distance, kpi_type). Сделать поддержку мульти-юзер для сравнения Z2-прогресса между пользователями. *Добавлено 16.05.2026.*
- [ ] **Чистка БД и data/** от лишнего — пользовательский запрос «потом постепенно архитектуру БД офистим от лишнего» (16.05.2026). Пройтись по таблицам PostgreSQL + папке `data/`, найти устаревшие/неиспользуемые объекты (например `apple_health_steps_daily.json` стал ловушкой после починки парсера — нужен свежий XML для перепарса; есть ли мусор в `nutrition_log` от тестов; etc.). Сделать инвентаризацию + чистку.

---

## 💰 OSS-монетизация и community (стратегия open core)

**Контекст (21.05.2026):** После разбора плейбука Anthropic «The Founder's Playbook» выбрана стратегия H4+H5 — open core для tech-биохакеров (бесплатно, brand+distribution+R&D) + русскоязычный B2C SaaS на botkin.health/cloud (первая платная аудитория). Цель — выйти за 24-36 мес на $3-8k/мес выручки, достаточной для найма part-time backend + саппорт. Референс-модель: **Home Assistant + Nabu Casa**.

### Запуск (на этой неделе — июнь 2026)

- [x] **AGPL-3.0-or-later лицензия** — `LICENSE`, `NOTICE`, секция в `README.md`, поля в `pyproject.toml`. Dual-licensing: AGPL для community + commercial license по запросу (lyskovsky@gmail.com). *Сделано 21.05.2026.*

- [ ] **Open Collective: настроить публичный Collective для Боткина** — *добавлено 21.05.2026.*
  - **Зачем:** прозрачное финансирование OSS-проекта, видимые донаты + видимые расходы. Это продаёт sustainability community.
  - **Fiscal host:** [Open Source Collective](https://opencollective.com/opensource) (501(c)(6) в США, принимает OSI-approved лицензии = AGPL подходит). Не нужно своё юр.лицо.
  - **Стоимость:** 5% платформенный fee + 10% fiscal host fee + ~3% Stripe = **~18% с каждого доната**. Цена за отсутствие бухгалтерии и юр.формальностей.
  - **Tier'ы (планируемые):**
    - ☕ Supporter $5/мес — имя в README
    - 🌟 Patron $25/мес — голос в feature voting + early access
    - 💎 Sustainer $100/мес — name в credits на botkin.health
    - 🏢 Sponsor $500/мес — logo на сайте
  - **Юрисдикция:** ✅ разблокировано — израильский паспорт + USD foreign-currency sub-account в Discount Bank (Israel) уже открыт (см. CLAUDE.md). Stripe Connect / GitHub Sponsors / Open Collective работают напрямую без обходов.
  - **Шаги:**
    1. Зарегистрироваться на opencollective.com **с израильским адресом и паспортом** (не РФ), создать Collective «Botkin» (описание, миссия, лого)
    2. Подать заявку в Open Source Collective как fiscal host (нужна ссылка на GitHub repo с AGPL)
    3. Ждать одобрения (3-10 дней)
    4. После approve — настроить tier'ы, привязать Stripe Connect с Discount Bank USD-счётом, опубликовать
    5. Добавить кнопку «Sponsor» на botkin.health
  - **Примеры посмотреть:** [opencollective.com/babel](https://opencollective.com/babel) ($300k+/год), [opencollective.com/standardnotes](https://opencollective.com/standardnotes), [opencollective.com/forgejo](https://opencollective.com/forgejo)
  - **Время на setup:** ~2-3 часа активной работы + 3-10 дней ожидания approval.

- [ ] **GitHub Sponsors параллельно с Open Collective** — *добавлено 21.05.2026.*
  - **Зачем:** технари (= H4) уже живут на GitHub, для них «Sponsor» кнопка прямо в репо — путь наименьшего сопротивления. Best practice — подключить обе платформы: GitHub Sponsors для технических контрибьюторов, Open Collective для прозрачности + не-технарей.
  - **Стоимость:** **0% fee** (GitHub субсидирует, по крайней мере до конца 2026) + Stripe processing ~3%. Дешевле Open Collective на ~15 п.п.
  - **Что даёт сверху OC:**
    - Кнопка «Sponsor» прямо в шапке GitHub-репо
    - Запись в файле `.github/FUNDING.yml` — GitHub автоматически показывает её на каждой странице
    - Sponsor badge у юзеров рядом с именем — социальный сигнал
    - Matched funding программа (GitHub иногда удваивает первые $5k для новых maintainer'ов)
  - **Tier'ы (mirror с Open Collective для консистентности):**
    - ☕ Supporter $5/мес — имя в README
    - 🌟 Patron $25/мес — голос в feature voting + early access к новым фичам
    - 💎 Sustainer $100/мес — name в credits на botkin.health + monthly office hours (групповой звонок)
    - 🏢 Sponsor $500/мес — logo на botkin.health + dedicated Slack/Telegram support
    - One-time donations включены — не все хотят подписку
  - **Юрисдикция:** ✅ разблокировано — израильский паспорт + израильский банк. GitHub Sponsors официально поддерживает Israel в списке payout-стран, Stripe Connect работает напрямую.
  - **Шаги:**
    1. github.com/sponsors → "Become a sponsored developer" → заполнить профиль (bio, photo, why I'm building Botkin) — ~30 мин
    2. Привязать payout method (Stripe Atlas / Payoneer / Wise USD) — ~15 мин
    3. Дождаться approval (обычно 1-3 дня, иногда до недели)
    4. После approve — настроить tier'ы, написать welcome message
    5. Создать `.github/FUNDING.yml` в репо Botkin с двумя ссылками (GitHub + Open Collective):
       ```yaml
       github: [Lyskovsky]
       open_collective: botkin
       ```
    6. Добавить кнопку «Sponsor» на botkin.health (та же что Open Collective, второй CTA)
  - **Примеры посмотреть** (топовые solo-maintainer'ы):
    - [github.com/sponsors/sindresorhus](https://github.com/sponsors/sindresorhus) — ~$45k/год, JS open source
    - [github.com/sponsors/calebporzio](https://github.com/sponsors/calebporzio) — $30k+/мес, Livewire/Alpine.js
    - [github.com/sponsors/evanw](https://github.com/sponsors/evanw) — Evan Wallace, esbuild
    - [github.com/sponsors/yyx990803](https://github.com/sponsors/yyx990803) — Evan You, Vue.js
  - **Время на setup:** ~1 час активной работы + 1-3 дня ожидания approval.

- [ ] **CLA Assistant для будущих контрибьюторов** — *добавлено 21.05.2026.*
  - **Зачем:** без подписанного CLA код внешних контрибьюторов остаётся AGPL и нельзя re-license в commercial. Это убивает dual-licensing модель.
  - [cla-assistant.io](https://cla-assistant.io/) — бесплатный GitHub App, контрибьютор подписывает CLA одним кликом на первый PR.
  - **Срочность:** надо включить **до публичного анонса** (до первого внешнего PR).
  - Шаги: установить GitHub App + написать текст CLA (стандартный Apache 2.0 ICLA подходит, минимальные правки).

- [ ] **`BUSINESS.md` в корне проекта** — *добавлено 21.05.2026.*
  - Зафиксировать стратегию: open core, выбранные сегменты H4 (OSS tech-biohackers) + H5 (русский B2C SaaS), AGPL + dual-licensing, монетизация по слоям, ключевые риски, метрики успеха.
  - Это «scope freeze» из плейбука — без него через месяц забудем что договаривались, и начнётся scope creep.

### Следующая фаза (месяц 1-3)

- [ ] **Bring-your-own-key (BYOK)** для Claude/OpenAI в боте — снимает с фаундера риск масштабирования AI-расходов. Юзер сам платит за свои токены через свой API-key. Технари H4 это любят (privacy-first + я-плачу-только-за-себя).

- [ ] **Customer discovery интервью** (10×H4 + 10×H5 за 2-3 недели) — past-behavior вопросы, не предсказательные. Outreach через HN/Reddit/Twitter (H4) + личную сеть (H5). См. план в разборе плейбука от 21.05.2026.

- [ ] **Лендинг botkin.health** — одностраничник: что это, для кого, GitHub link, waitlist для Cloud, кнопки Sponsor (GitHub + Open Collective). Нужен к моменту outreach в интервью.

### Средняя фаза (месяц 3-6)

- [ ] **Hosted SaaS — botkin.health/cloud** ($5-15/мес, русский B2C → H5) — turnkey версия для не-технарей. Multi-tenant в проде (RLS уже есть!), billing через ЮKassa (RU) + Stripe (intl), регистрация, OAuth-подключения.

- [ ] **Premium-фичи с license-key** в self-host — model Standard Notes. Advanced PDF парсинг с medical NER, family vault > 3 человек, премиум коннекторы (Mi Body CN3, специфичные русские лабы). $39 lifetime / $4/мес.

### Дальняя фаза (год 1+)

- [ ] **Bounty platform (Polar.sh)** — пользователи скидываются на конкретные фичи, contributor делает, фича попадает в OSS.

- [ ] **B2B sponsorships от concierge-клиник** (упрощённая H2) — $200-500/мес за white-label. Прямой контакт через Илью Мутовина (Singularity Club).

### Что НЕ делаем (anti-scope)

- ❌ Никаких VC-раундов до month 12+ — open core путь несовместим с venture pressure
- ❌ Никаких хроников/диабетиков как первый сегмент — регуляторный риск без MD-партнёра (см. H3 в разборе)
- ❌ Никакого корпоративного wellness/страховых — другая ДНК продукта
- ❌ Никаких новых фич для self под H4/H5 запросы вне scope — scope freeze в `BUSINESS.md`

---

## 🛠 Админ-дашборд (мульти-юзер инфраструктура к 50 чел)

**Контекст (10.05.2026):** В мае-июне 2026 хотим вырасти с 4 до 5–10 юзеров (семья + early_users) и до 50 после доклада на конференции. Нужна минимальная инфра управления.

### MVP (10.05.2026) — реализовано
- [x] **HTML-дашборд `/admin/`** на FastAPI, HTTP Basic Auth (`ADMIN_PASSWORD` из .env), тёмная тема
- [x] Раздел **Пользователи**: таблица, объёмы данных (meals/supps/weights/bp), действия (блок/разблок, смена cohort)
- [x] Раздел **Сервер**: размер Postgres, топ-таблиц, /opt/healthvault и /opt/backups
- [x] Раздел **Бэкапы**: список + кнопка «Сделать бэкап сейчас»

### v1 (до 50 юзеров — июнь 2026)
- [ ] **🏃 Sport-блок мульти-юзер: HR-сэмплы от любого источника** (контекст 11.05.2026 — после рефакторинга compute_aerobic_base.py)
  - **Проблема:** алгоритм и формулы (`compute_zone_boundaries(age)`, Maffetone-зоны, threshold-trap detection) уже мульти-юзер ready, но execution single-user. Нужен **source-agnostic** backfill — у owner — Garmin, у early-users — Apple Watch (через Apple Health → HAE → server), будут **Fitbit / Google Fitbit Air** (Google анонсировал бюджетный аналог Whoop — [wylsa.com](https://wylsa.com/google-predstavila-byudzhetnyj-analog-whoop/), массовый сегмент), Whoop, Polar
  - **Поддерживаемые источники (приоритет):**
    | Источник | Аудитория | API для HR-сэмплов |
    |---|---|---|
    | **Garmin** | owner (готово) | `get_activity_details(aid)` — 1-сек HR |
    | **Apple Watch** | **early-users** | HAE webhook workouts payload — HR time-series в JSON |
    | **Google/Fitbit Air** | будущая массовая аудитория | Fitbit Web API `/activities/heart/intraday` (1-сек / 5-сек, требует personal app scope) ИЛИ Google Health Connect (Android) |
    | Whoop | premium-сегмент | Whoop API `/cycle/{id}/strain` |
    | Polar | редко | Polar AccessLink API |
  - **3 направления:**
    1. **Per-user credentials в БД** — у `User` уже есть `garmin_email`/`garmin_password`. Для Apple Health: флаг `apple_health_enabled` + storage связи по user_id. Для **Fitbit/Google: OAuth refresh_token + access_token (`fitbit_oauth_token`, `fitbit_token_expires`)** — Fitbit OAuth2 PKCE flow с auto-refresh. Для Whoop/Polar — аналогичные поля под OAuth-токены, когда появится спрос
    2. **Server-side scheduled backfill** — cron-задача на сервере, проходит по списку active-юзеров, для каждого вызывает соответствующий fetcher (garmin/apple/fitbit/whoop) и считает Maffetone-зоны. Сейчас `sync_all_data.sh` бежит на моём Mac под Alex'а — вынести в сервер-side scheduled job (Hetzner cron или Celery)
    3. **Source-abstracted HR-fetcher** — интерфейс `get_workout_hr_samples(user, activity_id) → [hr_per_second]`. Реализации: `GarminFetcher` (есть), `AppleHealthFetcher` (читать из HAE workouts payload), **`FitbitFetcher`** (Fitbit Web API + OAuth refresh, поддержка Fitbit Air когда выйдет), `WhoopFetcher`, `PolarFetcher`. Storage HR-кеша: переезд с `data/garmin/activities/*.json` на `data/hr_cache/{user_id}/{source}_{activity_id}.json`
  - **Особенности Fitbit/Google Fitbit Air:**
    - Fitbit Air — анонсирован Google 2025, дешевле Whoop, целит в массовый сегмент → будет много пользователей
    - HR-сэмплы доступны через Fitbit Web API endpoint `/1/user/-/activities/heart/date/{date}/1d/1sec.json` (1-second resolution, intraday)
    - Требует пометки «Personal application» в Fitbit developer console (intraday не для public apps)
    - Google постепенно мигрирует Fitbit на Google Health Connect — нужно следить за изменением API в течение 2026
  - **Acceptance:** early-users открывают `/dashboard` → видят свой sport-блок с Maffetone-зонами по своему возрасту (180-Y), HR-биннингом из их Apple Watch тренировок, и теми же предупреждениями (Z3-trap, polarized verdict, и т.п.). Пользователь с Fitbit Air подключает Fitbit аккаунт через OAuth → получает тот же dashboard. compute_aerobic_base.py больше не запускается с моего Mac.
- [ ] **Login-форма вместо HTTP Basic** — куки-сессия, можно «выйти», красивее на мобиле
- [ ] **Broadcast** — отправить всем active family/early_user одно сообщение через Telegram, с подтверждением
- [ ] **Per-user view** — клик на юзера → его подробная страница (графики веса/калорий, последняя активность, лекарства, расходы)
- [ ] **Bot health**: uptime, p50/p99 webhook latency, последние 20 ошибок (читать из docker logs или централизованно)
- [ ] **Расписание бэкапов** — cron на сервере, ежедневно в 04:00 UTC, хранение 30 дней, копия на Hetzner Storage Box
- [ ] **Rate limiting на админ-эндпоинты** — fail2ban или middleware (защита от перебора пароля)
- [ ] **Audit log** — кто что когда менял (для прозрачности при работе с коллабораторами)
- [ ] **Команда `/setup`** — уже работает в боте, добавить кнопку «отправить юзеру /setup» в админке

### v2 (когда юзеров 30+, отдельный спринт)
- [ ] **Per-user учёт токенов LLM**: миграция `llm_usage(id, user_id, model, prompt_tokens, completion_tokens, cost_usd, ts, purpose)`, декораторы `@track_llm` на все вызовы OpenAI/Anthropic, бэкфилл из логов где возможно
- [ ] **Графики расходов** — total/месяц, по моделям, по юзерам, по типам запросов (food parsing / agent / dashboard generation)
- [ ] **Алерты** — Telegram-уведомление админу при ошибках бота / превышении дневного budget по токенам / падении сервиса
- [ ] **Health-score юзера** — кто активно пользуется, кто пропал, чтобы понимать retention
- [ ] **Self-serve onboarding для new users** — публичная регистрация через website, не только через Telegram

### Известные ограничения MVP
- HTTP Basic виден в URL только при первом входе (не каждом запросе), но на мобиле каждый раз спрашивает пароль если cookie очищен — login-форма решит
- Бэкап делается через `pg_dump` из контейнера бота — потребует postgres-client в образе (см. ниже Dockerfile)
- Ничего не автоматизируется: расписание бэкапов делается руками или из админки

---


---

> 💡 **Личные цели здоровья** (анализы, биомаркеры, био-возраст, CGM, тренировки)
> вынесены из публичного репо в `~/FamilyHealth/Александр Лысковский — Здоровье/personal-roadmap-2026-05.md`
> (19.05.2026 — приватность)

---

## 🛠 Технический долг

- [ ] **📧 Отдельный email для проекта Botkin** (12.05.2026): завести почтовый ящик под домен `botkin.health` (например, `hello@botkin.health` или `contact@botkin.health`) с редиректом на `lyskovsky@gmail.com`. На лендинге сейчас везде указан личный `lyskovsky@gmail.com` — заменить на проектный, когда будет готов. Cloudflare Email Routing — самый простой вариант, бесплатно, домен уже на Cloudflare.
- [ ] **Уборка на проде Hetzner — две инсталляции HealthVault в разных директориях** (12.05.2026): На сервере одновременно живут `/opt/healthvault/` (НАСТОЯЩИЙ деплой — refactored код, bind-mount'ы кода в контейнер, webapp + admin роуты) и `/root/healthvault/` (урезанная копия — старый плоский `core/`, нет webapp/, нет admin/, image-based COPY кода). Compose project «healthvault» в какой-то момент оказался ассоциирован с обоими config-files одновременно (`docker compose ls` показывал две строки). Прецедент: 12.05.2026 при миграции токена @HealthVault_bot → @Botkin_md_bot — Claude по ошибке отредактировал `.env` и `docker-compose.prod.yml` в `/root/healthvault/`, пересобрал контейнер оттуда и затёр настоящий из `/opt/`. Результат: бот ответил на /start (минимально), но webapp и admin 502'ились. Откатили обратно на `/opt/healthvault/`. **Что сделать:** (1) удалить `/root/healthvault/` целиком если он не нужен, либо ясно зафиксировать его назначение; (2) проверить что только ОДИН docker-compose активен; (3) задокументировать в `docs/DEPLOYMENT.md` правильный путь для deploy.sh — сейчас в скрипте `SERVER_PATH="/opt/healthvault"`, но в коде встречаются ссылки на `/root/healthvault`. Возможно есть ещё параллельные обломки — пройтись по `/`, `/root`, `/opt`, `/srv` и зачистить.
- [ ] **Telegram MCP `send_file` не работает из этого проекта**: `mcp__telegram-mcp__send_file` отбивает любой путь как "Path is outside allowed roots". Проверены: путь в проекте (Google Drive CloudStorage), `~/`, `/tmp`, `/private/tmp`, `~/telegram-mcp/`, симлинки — всё отвергается. Конфиг MCP в `~/Library/Application Support/Claude/claude_desktop_config.json` передаёт `/Users/alexlyskovsky/Desktop` и `/Users/alexlyskovsky` как allowed roots, но Claude Code переопределяет их через `session.list_roots()` и видимо даёт только cwd проекта — а в нём путь с кириллицей («Мой диск») не матчится. Workaround: скопировать файл в `~/Downloads/` и приложить вручную. Починить: либо изменить кейс `_path_is_within_root` в `~/telegram-mcp/main.py` чтобы сравнивал через NFC-нормализацию, либо выключить client-roots override чтобы CLI-config работал.
- [ ] **iPhone Screen Time — починить импорт**: данные показывают 11–18 мин/день вместо реальных нескольких часов — явно неполный импорт из ActivityWatch. Biome-данные через `aw-import-screentime` не подтягиваются после 30.03.2026. Разобраться: (1) проверить статус ActivityWatch на iPhone, (2) попробовать `aw-import-screentime` вручную и посмотреть что возвращает, (3) возможно нужен новый экспорт Biome или другой источник. Нужно для корреляций экранного времени со сном/стрессом/HRV.
- [ ] **Баг с таймзонами: «вчера» считается от UTC, не от МСК**: Бот на сервере работает в UTC. Если написать «вчера завтрак» в 00:15 МСК (= 21:15 UTC предыдущего дня), бот считает «вчера» от UTC-даты и записывает на день раньше. Решение: хранить `timezone` в `user_settings` (по умолчанию `Europe/Moscow`), использовать при парсинге «вчера/сегодня» в `handlers/text.py`. Реальный кейс: 12.04.2026, завтрак субботы попал на пятницу. Исправлено вручную через UPDATE.
- [ ] **Баг с медиагруппами (photo albums)**: При отправке нескольких фотографий разом (альбом) бот их не склеивает через `MediaGroupMiddleware` (гонка состояний или `update` не содержит `media_group_id` сразу). Фотки обрабатываются по одной, из-за чего LLM-Router не видит весь объем и недосчитывает граммовки. Временно отправляем фото по одной.
- [x] **Круговой импорт** `core/nutrition.py` ↔ `core/llm_food_processor.py`: Исправлено 22.03.2026. `llm_food_processor.py` оказался мёртвым кодом (337 строк, никогда не вызывался — `nutrition.py` содержала локальную копию). Удалён. Circular import устранён.
- [x] **Реорганизация `scripts/`**: Выполнено 22.03.2026. Структура: `scripts/import/` (11), `scripts/analysis/` (3), `scripts/backfill/` (2), `scripts/util/` (9), `scripts/archive/` (2 мёртвых). `sync_all_data.sh` обновлён.
- [x] **Реорганизация `core/`**: Выполнено 22.03.2026. Подпакеты: `core/food/` (4), `core/llm/` (2), `core/vision/` (5), `core/health/` (6), `core/infra/` (3). Proxy-модули на старых путях для 100% обратной совместимости (38 внешних импортов не трогались).
- [x] **Удалить `database/repository.py`**: помечен как deprecated (legacy psycopg2). Удалён 2026-03-21 (zero imports подтверждено).

---

## 💡 Идеи для улучшений (оценены, решили пока не делать)

- 💤 **Gyroscope — поставить и пощупать**: [gyrosco.pe](https://gyrosco.pe) — один из лучших визуальных дашбордов для трекинга здоровья. Тёмная тема, Health Score 1–100, агрегация 20+ источников (Apple Watch, Garmin, Oura, вес, сон). Интересен как UI-референс для будущего визуального интерфейса Botkin. Поставить приложение на iPhone, подключить Apple Health / Garmin, посмотреть как они визуализируют данные — что понравится, то взять в наш дашборд.

- 💤 **Supplement reminders — APScheduler (v2)**: UI и DB для напоминаний о добавках готовы (Telegram Mini App). Нужно добавить APScheduler: `pip install apscheduler`, при старте бота читать всех пользователей с `supplement_reminders_enabled=True`, создавать cron job на каждого через `AsyncIOScheduler`. При изменении настроек через `/api/settings` — перезагружать job. Файлы: `telegram-bot/bot.py` (scheduler init), новый `telegram-bot/scheduler.py` (job functions).
- 💤 **Telegram Mini App v2 — дни недели для добавок**: Разные добавки в разные дни (например, Псиллиум только в будни). Добавить поле `days: [0..6]` в JSONB supplements. Slot-группы в UI — выбор дней недели.
- 💤 **Утренний брифинг**: тоггл в UI уже есть (задизейблен «Скоро»). Отправлять утром: сон за ночь, HRV, Body Battery, план добавок на день. Зависит от APScheduler.

> **Контекст**: стоимость API ~$8.50/мес при текущей нагрузке (~12 сообщений/день). Оптимизации ради экономии не окупаются — дороже написать код.

- ❌ **Двухуровневый роутер** (local classifier → LLM только для неоднозначного): сэкономил бы ~$4/мес. Не окупается при текущем объёме. Пересмотреть если нагрузка вырастет в 10х.
- ❌ **Кэш LLM-ответов** (SHA256 по промпту, TTL 24ч): имеет смысл если одинаковые завтраки каждый день. Нужен Redis — overkill для личного бота.
- ❌ **Переезд с OpenAI на Claude**: цена та же, риск регрессий в поведении. Нет смысла без другой причины.
- 💤 **Vision → сразу результат без вопроса**: убрать лишний round-trip «опишите блюдо» — GPT-4o Vision сразу отдаёт результат с порогом уверенности. Улучшит UX фото. Сделать когда надоест описывать.
- ✅ **Few-shot примеры в промпте меню**: добавлены 5 примеров разных форматов (PDF-меню, Яндекс.Еда, фото ресторана, меню ккал/100г, бизнес-ланч) в SYSTEM_PROMPT. Каждый пример с NOTE и ключевым правилом. (`core/llm/router.py`)
- ✅ **Автобэкап PostgreSQL**: реализовано — cron ежедневно 04:17 UTC, ротация 14 бэкапов, скрипт `/opt/healthvault/scripts/auto_backup.sh`.
- 💤 **Сессия: аудит и рефакторинг NutriLogBot** (запланирована 22.03.2026): Провести полную ревизию распознавания КБЖУ. Включает: (1) Исправить промпты GPT — добавить якорные калорийности для частых продуктов, fiber, алкоголь в drinks. (2) Post-validation на сервере — флагать невозможные плотности. (3) **Стратегический вопрос**: стоит ли вообще парсить ответ GPT своим кодом, или лучше отправлять всё сообщение пользователя (текст/фото) напрямую в LLM с Structured Outputs (Pydantic-схемой) и получать сразу готовый JSON: `{food, amount_g, cal, protein, fats, carbs, fiber, alcohol_drinks}`. Плюсы: меньше кода, LLM сама разбирается с контекстом, новые поля добавляются в схему за секунду, ошибки парсинга исчезают. Минусы: полная зависимость от LLM, нет контроля на уровне кода, дороже по токенам если промпт длинный. Возможно мы уже близки к этому (Structured Outputs через Pydantic уже есть в `core/llm_models.py`) — нужно оценить gap.
- ✅ **Pre-commit хуки** (ruff + ruff-format + check-ast + detect-private-key): `.pre-commit-config.yaml` создан, `pyproject.toml` с конфигом ruff. Автофикс 1449 нарушений, найдены реальные баги (дубликат `save_photo`, дубль ключей словаря). Хуки активны в `.git/hooks/`.
- 💤 **RescueTime** (продуктивность за компом): поставить полноценный RescueTime вместо самописного Chrome History. Даст категоризацию по приложениям, productivity score, goals. Chrome History удалён (дублировал Screen Time, не использовался).
- ✅ **Улучшение точности КБЖУ в NutriLogBot**: (1) Добавлена таблица CALORIC DENSITY ANCHORS в промпт — 15 продуктов с правильными ккал/100г (масло 748, брокколи 34, куриная грудка 165, креветки 95 и др.). (2) Добавлено правило #11: проверять плотность 0.1–9 ккал/г. (3) Post-validation `cal_per_100g > 1000` уже был в `core/food/nutrition.py`, теперь покрыт регрессионным тестом. (`core/llm/router.py`, `tests/test_caloric_density_check.py`)
- 💤 **Мультипользовательский Botkin (второй пользователь)**: user_id=2 уже есть в БД. Нужно распространить всю инфраструктуру анализа и синхронизации. **Устройство**: выбрать между Garmin Venu 3S или Oura Ring Gen 3. **Что нужно сделать:** (1) `sync_all_data.sh` — добавить синхронизацию для второго аккаунта. (2) `scripts/analysis/progress_chart.py` — параметр `--user`. (3) `/dashboard` — показывать потоки для обоих или с переключением. (4) `scripts/analysis/` — параметризовать по `user_id`. **Настройки:** добавить галочку `show_calorie_budget_bar` (по умолчанию `True`) в `user_settings`, проверять в `format_budget_line()` / `cmd_day()`.
- 💤 **Mission Control — мобильная адаптация**: Сейчас дашборд рассчитан только на десктоп (viewport=1440). Нужно: (1) meta viewport → device-width, (2) grid-3/grid-6 → 1-2 колонки на мобиле, (3) charts → меньше высота, (4) блок "Неделя в цифрах" (несколько stat-плашек: вес Δ, сон, HRV, тренировки, ккал avg) — быстрый инсайт без скролла, (5) переключатель диапазона "2W / 1M / All" на charts. Приоритет: сначала читаемость на iPhone, потом ширина от 375px.
- 💤 **Telegram Mini App — панель настроек бота**: Открывается кнопкой `/settings` прямо внутри Telegram (как Кошелёк, TON). Технология: Telegram Web App API — обычный HTML/CSS/JS, хостится на нашем сервере (`health.orangegate.cc/webapp/`), открывается через `WebAppButton`. Авторизация бесплатная — Telegram передаёт `initData` с подписанным `user_id`, бот проверяет HMAC. **Архитектура:** (1) новая таблица `user_settings` в PostgreSQL: `user_id`, `show_calorie_budget_bar bool`, `daily_calorie_target_override int`, `macro_targets jsonb`, `supplement_reminders bool`, `morning_briefing bool`, `language varchar`. (2) FastAPI endpoint `GET/POST /api/settings` на сервере — читает/пишет `user_settings`. (3) Static Web App: `telegram-bot/webapp/index.html` — форма с тогглами, сохраняет через fetch к API. (4) В BotFather добавить `Menu Button` с URL webapp. **Что включить в настройки v1:** `show_calorie_budget_bar` (для Ники), целевой вес и дата дедлайна, напоминания о добавках (вкл/выкл + время), язык интерфейса. **Что добавить позже:** макро-цели, утренний брифинг, вечерний чекин, тема оформления. **Трудозатраты:** ~4-6 часов на MVP (таблица + API + одностраничный веб-интерфейс). **TODO:** перенести туда же профиль из `/profile` — блок «Профиль» с полями: дата рождения, рост, пол, целевой вес + дата. Сделать визуально: карточка «Мой профиль» как первый раздел Mini App. API endpoint уже есть (`GET/POST /api/profile`), нужно только добавить раздел в webapp.
- 💤 **CGM-датчик глюкозы** (FreeStyle Libre / Supersapiens): непрерывный мониторинг глюкозы 24/7 на 14 дней. Клеится на плечо, данные в телефон. Новый поток данных для Botkin — реакция на еду, скачки сахара, связь глюкозы со сном и стрессом. ~5000-7000₽ за сенсор, достаточно 1-2 раза в год. Нужно: купить сенсор, написать импорт данных в Botkin (LibreLink API или CSV-экспорт).
- 💤 **InBody / DEXA-сканирование состава тела**: точный анализ жира, мышц, воды и костей по сегментам тела. Умные весы Zepp дают ±3-5% погрешность, InBody/DEXA — эталон. Делать раз в 3 мес. InBody ~2000₽ в фитнес-клубах, DEXA ~5000₽ в клиниках. Данные добавить в `data/weights/body_composition_scans.json` для сравнения с Zepp и отслеживания реального прогресса.
- 💤 **Утренний брифинг в Telegram** *(идея: WellAlly, Ларьяновский)*: каждое утро в 08:00 бот отправляет 4-7 предложений — не пересказ цифр, а клиническое суждение. Данные: сон (Garmin), стресс/HRV, вчерашние шаги, восстановление (Body Battery). «Правило молчания»: агент молчит если данных нет. Модель: Haiku для сбора + Sonnet для синтеза. Файл: `docs/ai_context/reference_wellally_blueprint.md` — полный blueprint.
- 🔴 **Голосовой дневник дня — единый сценарий (без MVP-шага с цифрой)** *(уточнение пользователя 26.04.2026)*

  > **Решение пользователя 26.04:** пропустить промежуточный MVP-шаг с командой `/energy N` (не интересно цифру писать) и сразу делать **голосовую заметку каждый вечер** с описанием: как прошёл день, что важного, что отметил для себя в здоровье и психологии.
  >
  > **Сейчас не реализуем — только зафиксировано в todo.** Делать когда дойдут руки и появится желание.

  ### Концепция

  **Один ритуал, одно касание:** в 21:00 бот напоминает → жмёшь «🎙» → говоришь 30-120 секунд → всё остальное делает pipeline. Никаких форм, кнопок 1-10, дополнительных команд.

  ### Pipeline (на готовом стеке NutriLogBot)

  1. **Whisper / Gemini** транскрибация голосового сообщения (уже работает в боте для еды).
  2. **Haiku** с Pydantic-схемой извлекает структурированные поля + сохраняет сырой транскрипт + ссылку на oga-файл.

  ### Структура одной записи (`daily_journal` в PostgreSQL)

  ```json
  {
    "date": "2026-04-26",
    "energy_score": 7,                         // 1-10, LLM выводит из тона/слов
    "mood": "positive|neutral|negative",
    "stress_level": 4,                          // 1-10
    "sleep_subjective": 8,                      // если упоминалось
    "events": ["travel:spb", "social:family_dinner", "work:focused"],
    "physical_symptoms": ["cold_starting"],
    "psychology_notes": ["прокрастинация после звонка с N", "тревога вечером"],
    "wins": ["finished_phenoage_calc"],
    "concerns": ["мама опять не пьёт лекарства"],
    "raw_transcript": "Сегодня созвонился...",
    "voice_url": "data/media/journal/2026-04-26.oga"
  }
  ```

  Ключевое: LLM извлекает `energy_score`, `mood`, `stress_level` **из голоса автоматически**, пользователю не нужно их называть.

  ### Что это даёт (insights, недоступные сейчас)

  - **Раннее обнаружение** — упоминание простуды → HRV-провал через 1-2 дня (окно профилактики).
  - **Корреляции со стресс-метками** — «дни stress_level >7 → −12% HRV, +алкоголь, −0.7 ч сна». Сейчас этих корреляций нет — нет субъективных данных.
  - **Travel-аннотации** — «перелёт в Питер» автоматически объясняет провалы шагов/HRV. Дашборд перестаёт «лгать» провалами без контекста.
  - **Месячный дайджест Sonnet** — «За март упоминал стресс 8 раз, простуду 1, перелётов 2. Главная корреляция: travel → −18% сна. Главный win: 12 дней без алкоголя».
  - **Психологический слой** — отслеживать паттерны прокрастинации/тревоги/мотивации, которых сейчас в проекте нет вообще.
  - **Субстрат для агентного MDT-консилиума** — превращает «AI читает цифры и гадает» в «AI читает цифры + картину мира пользователя».

  ### Корреляции с объективными данными (V3 — главное зачем это всё)

  - Скрипт `scripts/analysis/correlate_journal_with_objective.py` — раз в неделю/месяц считает корреляции `daily_journal.{stress, mood, energy} × {hrv, sleep_hours, weight, alcohol_drinks, hr_resting, body_battery}` с детрендом и контролем размера выборки.
  - Mission Control: новый блок **«Subjective × Objective»** — таблица топ-10 корреляций с N дней, r, p-value, человекочитаемой подписью.
  - Триггеры: если упоминание простуды → бот через 5 дней спрашивает «выздоровел?», чтобы точно поставить точку «recovered» в timeline. Аналогично для travel, illness, exam, deadline.

  ### Mission Control — новый блок «Дневник»

  - Мини-плашка с last-3-days (короткие выжимки).
  - Цветовая шкала mood/stress по дням за месяц.
  - Top-3 события месяца (по частоте упоминания: «работа», «семья», «здоровье»).

  ### Privacy

  - Голосовые в `data/media/journal/` (gitignore), личный журнал — **НЕ** шарить с Никой/Андреем/семьёй.
  - Команда `/journal delete YYYY-MM-DD` для удаления конкретного дня.
  - Транскрипты тоже не индексируются для других пользователей (фильтр по user_id в запросах).
  - Опция «удалить всё старше N месяцев» — если переживаешь за хранение.

  ### Реализация (когда соберёшься делать)

  - [ ] Миграция Postgres: таблица `daily_journal` (поля выше).
  - [ ] Handler `/journal` в `telegram-bot/handlers/` — принимает голосовое или текст. Запускает Whisper → Haiku.
  - [ ] APScheduler-job: 21:00 ежедневно отправляет напоминалку с inline-кнопкой «🎙 записать».
  - [ ] LLM-промпт + Pydantic схема для извлечения структуры (опираться на паттерн NutriLogBot Structured Outputs). В схему включить поле `city` — если в тексте упомянут другой город («я в Челябинске», «прилетел в Питер»), LLM извлекает название. При сохранении записи: если `city != Москва` → добавлять в `LOCATION_OVERRIDES` в `weather.py` и перезапускать погодный скрипт для этой даты. Это решает проблему командировок без VPN/GPS.
  - [ ] Скрипт корреляции `scripts/analysis/correlate_journal_with_objective.py`.
  - [ ] Mission Control: новый iframe-блок «Дневник».
  - [ ] Опционально: команды `/journal show YYYY-MM-DD`, `/journal delete YYYY-MM-DD`, `/journal month <month>` (текущий месяц как digest).

  **Без давления:** пропустить можно, streak-shaming не делать. Бот не злится, не настаивает.

  **Trade-off с Apple Notes / другими тулами:** ты уже частично делаешь нечто подобное в голове или в Notes. Преимущество интеграции в Botkin — это **корреляции с объективными данными**. Notes этого не дают.
- 💤 **Агентный слой (MDT-консилиум)** *(идея: WellAlly, Ларьяновский)*: 5-9 AI-специалистов (кардио, эндокринолог, нутрициолог, пульмонолог, психиатр...) еженедельно анализируют данные каждый по своему домену. GP-агент синтезирует в один отчёт. PubMed API для обоснования выводов. Модели: специалисты на Haiku (параллельно), GP на Sonnet. Первый опыт с агентным слоем — сделать как учебный проект.
- 💤 **Task lifecycle → Apple Reminders** *(идея: WellAlly, Ларьяновский)*: задачи из AI-отчётов автоматически попадают в Apple Reminders через AppleScript, с polling каждые 3ч для синка обратно. Закрыл в Reminders → закрылось в БД. Заменит ручное ведение todo.md и Apple Notes.
- ✅ **Apple Health → автоимпорт** (готово 02.05.2026): Заменён ручной XML-экспорт на автоматический ежедневный пайплайн через [Health Auto Export](https://apps.apple.com/app/health-auto-export-json-csv/id1115567069) ($24.99 lifetime). iOS-приложение раз в сутки шлёт POST на `/apple_health_v2` с 17 метриками: шаги, дистанция, активные ккал, этажи, пульс (avg/min/max + resting), АД (Omron), походка (скорость/длина шага/двойная опора/асимметрия), вес/жир/мышцы (Mi-весы), VO2max, частота дыхания. Адаптер `_hae_to_daily_payloads()` в `telegram-bot/webhook/apple_health.py` группирует метрики по датам и upsert'ит в `activity_log`/`blood_pressure_logs`/`weights`. Старый Shortcut-путь (POST `/apple_health` v1) оставлен для обратной совместимости. Изначальная идея — пост Ларьяновского, комментарий Мальцева.
- 💤 **USDA FoodData Central — валидация КБЖУ** *(идея: аудит QS-экосистемы)*: Подключить бесплатный API USDA (fdc.nal.usda.gov) для post-validation КБЖУ от GPT. После того как GPT оценил блюдо, сервер проверяет калорийную плотность по справочнику USDA для основных ингредиентов. Если расхождение >30% — флагать и переспрашивать. Пример: GPT сказал «брокколи 150г = 270 ккал», USDA говорит 34 ккал/100г → флаг. API бесплатный, без ключа для базовых запросов. **Файлы:** `core/food/nutrition.py` (добавить post-check), новый `core/food/usda_client.py`.
- 💤 **OpenFoodFacts — штрихкод-сканер** *(идея: аудит QS-экосистемы)*: Пользователь отправляет фото штрихкода в Telegram-бот → бот распознаёт баркод (через python-barcode или GPT Vision) → запрос к OpenFoodFacts API (ru.openfoodfacts.org, бесплатно, без ключа) → возвращает точные КБЖУ + состав с упаковки. Для упакованных продуктов это точнее GPT, потому что данные с этикетки. Российские продукты есть, покрытие растёт. **Что нужно:** (1) Распознавание штрихкода из фото (pyzbar или GPT). (2) Запрос к OFF API по баркоду. (3) Fallback на GPT если продукт не найден. **Файлы:** новый `core/food/barcode_scanner.py`, хэндлер в `telegram-bot/handlers/`.
- ✅ **Клетчатка (fiber) в NutriLogBot**: GPT-модель при анализе фото/текста еды считает калории, белки, жиры, углеводы — но **не оценивает клетчатку**. Поле `fiber` есть в схеме items (jsonb), но заполнено только в 1 из 467 записей. **Что нужно:** добавить в system prompt LLM-роутера (`core/llm_router.py` или промпт в `core/llm_food_processor.py`) явное требование оценивать fiber (г) для каждого продукта. Также добавить fiber в totals-агрегацию (`core/nutrition.py`). **Зачем:** клетчатка влияет на сытость, скорость пищеварения, задержку воды и уровень сахара — важна для корреляций с весом, сном и стрессом. Без неё нельзя проверить гипотезу «больше клетчатки → лучше сон / стабильнее вес».

---

## 🧪 Система тестирования промптов LLM

> **Контекст**: В проекте есть два вида тестов. Обычные unit-тесты (`tests/`) покрывают Python-логику без вызова API — они быстрые и используют моки. LLM prompt тесты (`scripts/test_llm_prompt.py`) — вызывают реальный GPT/Gemini и проверяют что промпт ведёт себя правильно. Это нужно потому что при изменении промпта поведение LLM может непредсказуемо измениться.

### ✅ Вариант А — автозапуск в deploy.sh (РЕАЛИЗОВАН, фев 2026)

При каждом `./deploy.sh` автоматически запускается `scripts/test_llm_prompt.py` внутри боевого контейнера (Шаг 5/5). Если тест падает — деплой завершается с предупреждением ❌, бот при этом уже работает.

**Как добавить новый тест при фиксе промпта:**
1. Воспроизвести баг — записать: текст запроса, что ответил LLM (плохо), что должен ответить (хорошо).
2. Добавить кейс в `TEST_CASES` в `scripts/test_llm_prompt.py`:
   - `bad_value` — значение которое было до фикса (регрессия)
   - `calories` — диапазон ожидаемых значений после фикса
3. Запустить тест локально перед деплоем: `source venv/bin/activate && python scripts/test_llm_prompt.py`
4. Задеплоить — тест запустится автоматически.

**Запуск вручную:**
```bash
# Все тесты на сервере:
ssh root@116.203.213.137 'docker exec healthvault_bot python /app/scripts/test_llm_prompt.py'

# Только регрессионные:
ssh root@116.203.213.137 'docker exec healthvault_bot python /app/scripts/test_llm_prompt.py --tags regression'

# Деплой без LLM тестов (если API временно недоступен):
./deploy.sh --skip-llm-tests
```

### [ ] Вариант Б — Full E2E через Telegram Bot API (PLAN)

**Проблема с Вариантом А:** он тестирует только `core/llm_router.py` напрямую — Python вызов. Не тестирует Aiogram handlers (`telegram-bot/handlers/`), middleware, FSM state, кнопки подтверждения и сохранение в БД. Баги в этих слоях тесты не поймают.

**Идея Варианта Б:** создать отдельного тест-пользователя в Telegram и БД. Отправлять ему сообщения через Bot API, читать ответы бота через Telegram Bot API (long polling или getUpdates), проверять текст ответа, нажимать кнопки «Сохранить», проверять что запись появилась в БД, потом удалять её.

**Что нужно для реализации:**
1. **Тест-пользователь**: зарегистрировать второй Telegram-аккаунт (или использовать тестовый номер), добавить в БД как полноценного юзера через `database/crud.py`.
2. **Отправка сообщений через Bot API**: `POST /bot{TOKEN}/sendMessage` c `chat_id` тест-юзера.
3. **Чтение ответа бота**: `GET /bot{TOKEN}/getUpdates` — читать ответы бота на сообщение тест-юзера.
4. **Эмуляция нажатия кнопки**: `POST /bot{TOKEN}/answerCallbackQuery` после получения `callback_query` в ответе.
5. **Проверка в БД**: `SELECT * FROM nutrition_logs WHERE user_telegram_id = {test_user_id} AND date = today` — убедиться что запись появилась.
6. **Cleanup**: `DELETE FROM nutrition_logs WHERE user_telegram_id = {test_user_id}` после каждого теста.
7. **Скрипт**: `scripts/e2e_telegram_test.py` — запускается отдельно от деплоя (дольше, требует сети).

**Примерный тест-кейс:**
```
Отправить: "150 грамм гречки"
Ожидать: бот ответил с кнопками [✅ Сохранить] [❌ Отмена], калории ~510 ккал
Нажать: ✅ Сохранить
Проверить: запись появилась в nutrition_logs с calories≈510
Cleanup: удалить запись
```

**Когда делать:** когда появятся регрессии в handlers (сейчас их нет, Вариант А достаточен).


---

## 📜 История (ключевые вехи)

**Январь 2026**
- ✅ **Создание MVP**: Локальный запуск бота, базовый учет калорий и витаминов.
- ✅ **Первый Сервер**: Деплой на российский хостинг, настройка Docker.

**Февраль 2026**
- ✅ **Переезд в Нидерланды**: Миграция на VDSina (NL) для обхода блокировок OpenAI/Gemini.
- ✅ **Голосовой Ввод**: Подключение транскрибации (Whisper/Gemini) для логирования голосом.
- ✅ **Интеграция Garmin**: Синхронизация шагов, сна и активных калорий.
- ✅ **Масштабирование**: Расширение диска сервера (10GB → 40GB) для стабильности.
- ✅ **База Данных**: Запуск PostgreSQL, частичная миграция (Витамины, Еженедельные отчеты).
- ✅ **Исправление Логики**: Фикс подсчета итоговых калорий и веса продуктов.
- ✅ **Обслуживание**: Очистка сервера в РФ. Устранение дублей.
- ✅ **Рефакторинг**: Удалён мёртвый код и сломанные импорты.
- ✅ **Миграция в БД**: Питание и веса из JSON перенесены на сервер; сон из Garmin sleep, вес carry-forward для полного покрытия по дням.

**Март 2026**
- ✅ **Dashboard v2**: 17 потоков данных с колонками «Записей» и «Статус». Алкоголь как отдельный поток (drinks). Нормы частоты по каждому потоку (ежедневно/еженедельно/ежеквартально).
- ✅ **Корреляции КБЖУ**: Полный анализ влияния питания на вес, сон, стресс. Детренд для исключения ложных корреляций. Находки: алкоголь — фактор №1 для дневного веса (+0.6 кг), жиры ухудшают сон (r=−0.33).
- ✅ **Метеозависимость**: Анализ 75 дней — подтверждена умеренная чувствительность к перепадам атм. давления (r=+0.30 на АД).
- ✅ **Автобэкап БД**: Cron на сервере, ежедневно 04:17 UTC, ротация 14 бэкапов.
- ✅ **Circular import починен**: `llm_food_processor.py` — мёртвый код (337 строк). Удалён. Circular dependency устранена.
- ✅ **Реорганизация scripts/**: 28 файлов → 5 подпапок (import/, analysis/, backfill/, util/, archive/).
- ✅ **Реорганизация core/**: 22 модуля → 5 подпакетов (food/, llm/, vision/, health/, infra/) с proxy-модулями для обратной совместимости.
- ✅ **iPhone Screen Time**: Починен (aw-import-screentime + import_activitywatch), данные до текущего дня.
- ✅ **OAuth токены**: Унифицированы в `data/cache/tokens.json`.
- ✅ **Chrome History**: Удалён (дублировал Screen Time). RescueTime в планах.

---

## 🔗 Аналоги и вдохновение

> Ссылки на посты, проекты и блюпринты людей, которые делают похожее.

- **OpenHealth** (3.7k stars): https://github.com/OpenHealthForAll/open-health — AI health assistant, multi-LLM (LLaMA/GPT/Claude), local-first, парсинг анализов. Ближайший open-source аналог WellAlly.
- **Garmin-Grafana** (2.4k stars): https://github.com/arpanghosh8453/garmin-grafana — InfluxDB + Grafana для Garmin. Форк с Claude AI: https://github.com/saarbyrne/garmin-grafana-n8n
- **Open Wearables** (551 stars): https://github.com/the-momentum/open-wearables — универсальное API для всех носимых устройств в единую схему.
- **QS Ledger** (1k stars): https://github.com/markwk/qs_ledger — 20+ источников данных, Jupyter-ноутбуки для корреляций. Mark Koester (QS community).
- **Exist.io**: https://exist.io — коммерческий, но open API + движок корреляций между потоками (сон × продуктивность, погода × настроение). Эталон для нашей аналитики.
- **Welltory**: https://github.com/Welltory — опубликованная HRV-методология, открытые PPG-датасеты, wavelet-анализ. Полезно для валидации наших HRV-данных.
- **Nightscout** (2.4k stars): https://github.com/nightscout/cgm-remote-monitor — CGM в облаке. Пригодится когда купим FreeStyle Libre.
- **awesome-quantified-self** (2.6k stars): https://github.com/woop/awesome-quantified-self — полный каталог QS-экосистемы.
- **Singularity Club** (€10K/год): https://singularityclub.tech — коммерческий longevity-консьерж. WHOOP/Oura + анализы + геном + AI copilot + менеджер. Интересное: верификация добавок (NSF/USP/ConsumerLab), n=1 эксперименты, friction design. У нас уже есть ~80% их функций бесплатно.
- **Саша Ларьяновский — WellAlly** (март 2026): https://www.facebook.com/share/p/1KrK9dpCkD/?mibextid=wwXIfr — пост + blueprint в первом комментарии. Blueprint скачан в `docs/ai_context/reference_wellally_blueprint.md`. Архитектура: 9 MDT-специалистов + GP-агент + вечерний чекин + утренний брифинг + PubMed + Apple Reminders. За 14 часов гуманитарием. Ключевые идеи для нас: утренний брифинг, вечерний чекин, агентный слой, task lifecycle.

---
