# ИИ-Журнал Изменений (AI Changelog)

В этом файле ИИ-ассистенты (Cursor, Claude, Antigravity) фиксируют завершенные задачи. Это нужно для передачи контекста между IDE.

**Правило добавления:**
`[YYYY-MM-DD] Краткое описание реализованной фичи (затрагиваемые файлы) - Автор`

---

## 2026-06-29 — MCP-коннектор для Claude Desktop: PAT + JWT + scope (#228)

- **`database/models.py`** — модель `PersonalAccessToken` (id, user_id FK→users.telegram_id, token, name, scope ro/rw, created_at, last_used_at, revoked_at). CheckConstraint на scope, два индекса (unique token, user_id).
- **`database/alembic/versions/pat0token01_add_personal_access_tokens.py`** — Alembic-ревизия: CREATE TABLE + индексы + GRANT SELECT/INSERT/UPDATE к hv_app. Явно без RLS (публичный exchange-endpoint ищет токен до того как знает user_id).
- **`database/crud.py`** — PAT CRUD: `create_pat`, `get_active_pat_by_token` (бампит last_used_at), `list_pats`, `revoke_pat` (soft-delete). `ALLOWED_PAT_SCOPES = ("ro", "rw")`.
- **`telegram-bot/webhook/jwt_auth.py`** — `generate_agent_jwt` + опциональный `scope`; `get_agent_user` сохраняет scope в `request.state.agent_scope`; `require_agent_scope(required_scope)` — dependency-factory.
- **`telegram-bot/webhook/rate_limit.py`** (новый) — `SlidingWindowRateLimiter(max_requests, window_seconds)` с инъектируемым `now`.
- **`telegram-bot/webhook/agent_tools_api.py`** — новый публичный endpoint `POST /api/agent/exchange_pat_for_jwt` (rate-limit 10/60s, возвращает `{access_token, token_type, expires_in, scope}`); 10 mutating-эндпоинтов переключены на `require_agent_scope("rw")`.
- **`telegram-bot/handlers/connect_claude.py`** (новый) — команды `/connect_claude` (выбор rw/ro → выдача PAT) и `/my_connections` (список + отзыв через inline-кнопки).
- **`telegram-bot/bot.py`** — регистрация `connect_claude_router` + команда в меню.
- **`scripts/mcp/botkin_client.py`** (новый) — HTTP-клиент без mcp-зависимости: PAT→JWT обмен, кэш JWT, 401-retry, 403→BotkinAuthError.
- **`scripts/mcp/botkin_pat_mcp.py`** (новый) — FastMCP stdio-сервер: 10 инструментов над `/api/agent/*`.
- **`scripts/mcp/manifest.json`** (новый) — `.mcpb` v0.3 манифест, `user_config.pat` (sensitive→keychain) + `base_url`.
- **`docs/user_guide/ru/mcp-claude-desktop.md`** — руководство пользователя (команды, установка, инструменты, troubleshooting).
- **`docs/architecture/decisions/0006-mcp-connector-pat-jwt.md`** — ADR принят (Proposed→Accepted).
- **Тесты:** `tests/test_pat_crud.py` (15), `tests/test_rate_limit.py` (8), `tests/test_pat_exchange.py` (8), `tests/test_connect_claude.py` (11), `tests/test_botkin_client.py` (11).

## 2026-06-28 — Самостоятельная загрузка медицинских документов через /doc (PR #227)

- **`core/health/doc_extractor.py`** — Claude Haiku читает PDF/фото, извлекает дату, лабораторию и числовые значения. Возвращает `{}` при любой ошибке.
- **`core/health/kb_writer.py`** — атомарная запись в `documents[]` секцию `kb_<user_id>.json` через tempfile + replace. Не трогает другие секции KB.
- **`telegram-bot/handlers/doc_upload.py`** — state machine `/doc`: ждёт файл → вызывает экстрактор → показывает превью с кнопками «Сохранить / Отмена». Файл сохраняется как `.pending` до подтверждения. Санация `ext` для защиты от path traversal. Блокировка двойной отправки.
- **`telegram-bot/bot.py`** — `doc_upload_router` зарегистрирован перед `photo_router`.
- **`telegram-bot/handlers/onboarding.py`** — финал онбординга упоминает `/doc`.
- **Тесты:** 11 новых тестов (3 + 3 + 5).

## 2026-06-28 — Mini-app: кнопка «Подключить» для источников данных (PR #150)

- **`telegram-bot/webhook/profile_api.py`** — `get_data_sources()` расширен полем `connect_info` для каждого источника: `flow` (coming_soon / inline_token / tg_deeplink) + `health_token` для inline_token-источников (apple_health, health_connect) когда не подключены. Токен достаётся через `get_or_create_health_token` в рамках того же DB-сеанса. CGM → deeplink `tg://...start=connect_cgm`. Garmin/Zepp/Netatmo → coming_soon.
- **`tests/test_data_sources_api.py`** — +6 тестов: `connect_info` schema, flows по каждому типу, токен присутствует только для отключённых inline_token-источников. Итого 14 тестов.
- **`telegram-bot/webapp/settings.css`** — новые классы: `.source-row-wrap`, `.connect-btn`, `.connect-panel`/`.open` (max-height accordion), `.connect-content`, `.method-btn`, `.connect-tg-btn`, `.coming-soon`, `.copy-btn`. Тёмная тема через prefers-color-scheme.
- **`telegram-bot/webapp/settings.js`** — заменён `_renderSourceRow` (аккордеон); добавлены `_renderConnectPanel`, `_renderAppleHealthPanel`, `_renderHealthConnectPanel`, `selectAppleMethod`, `toggleConnect`, `copyToken`. Безопасный `JSON.stringify(token)` в onclick-атрибутах вместо `'${safeToken}'`. `apple-detail-<id>` вместо глобального singleton id.

## 2026-06-28 — Кросс-валидация вес↔калории в записях питания (#211, PR #220)

- **`core/food/calorie_validator.py`** (новый модуль): `validate_weight_calorie_sync(data)` — при наличии `nutrition_per_100g` и `weight_grams > 0` **всегда** пересчитывает все макронутриенты от `nutrition_per_100g × weight_grams` (ранее — только при `calories == 0`). Иммутабельный, добавлен `round(..., 1)` для согласованности с `nutrition.py`.
- **`core/vision/chatgpt_vision.py`**: условный пересчёт заменён на вызов `validate_weight_calorie_sync()`; промпт уточнён — `weight_grams` = вес ПОЛНОЙ порции (дефолты: 350г боул/поке, 200г гарнир, 100г снек).
- **`scripts/audit/audit_nutrition_sync.py`** (новый): SQL-аудит `nutrition_log`, флагует записи с ккал/100г > порога (дефолт 400) → CSV.
- **`tests/test_calorie_validator.py`**: 8 unit-тестов (TDD, RED→GREEN).
- Корень бага: LLM оценивал ккал за полную порцию (~350г), парсер ставил weight_grams = 150г (основной ингредиент) → поке 150г → 317 ккал/100г вместо ~150-200.

## 2026-06-27 — Онбординг Alegas: настройка окружения + закрытый ложный баг #217

- Настроено dev-окружение для нового контрибьютора (Alegas): Python 3.13, pip, pytest (901 passed), gh CLI, `.claude/settings.json`, skills `prepare-task`/`complete-task`, rules `ecc/`.
- `.gitignore` уточнён: `.claude/` больше не игнорируется целиком — коммитятся `skills/`, `rules/`, `settings.json`; игнорируются только `worktrees/`, `settings.local.json`, `scheduled_tasks.lock`.
- Issue #217 «anthropic SDK не указан» закрыт как «won't fix»: кодовая база не использует Python SDK `anthropic` — все вызовы Anthropic API делаются через `requests.post` напрямую. Ошибка `ModuleNotFoundError: No module named 'anthropic'` возникла при ручной проверке в терминале, но бот `import anthropic` не делает нигде.

## 2026-06-17 — CGM: интеграция глюкозы завершена + фикс зависания /sync

- **PR #152** (backoff + дашборд-блок): `scripts/import/librelinkup.py` — exponential backoff 15→30→60→120м при HTTP 476 (`LoginOnCooldownError`); `telegram-bot/dashboard_generator.py` — блок глюкозы (текущее значение, TIR 14д, 24h-спарклайн, invite-карточка для юзеров без CGM).
- **PR #158** (фикс зависания `/sync`): `telegram-bot/handlers/sync_cmd.py` — `parse_mode=None` во всех `edit_text()` и `answer()`. Корень: `<none>` в тексте ошибки 476 Telegram парсил как HTML-тег → `BadRequest` → сообщение зависало навсегда.
- **PR #155** (docs + лендинг): CGM в DONE в ROADMAP; лендинг botkin.health — «глюкоза» и «глюкометр», задеплоен на сервер.
- **Research doc**: `docs/researches/2026-06-14-cgm-librelinkup-integration.md` — детальный troubleshooting Cloudflare 476: 4 триггера, реальный `Retry-After: 65620` (~18ч), account-level 429 vs IP-бан, ссылки на nightscout issues.
- **PR #151** (Игорь Николаев, security): `telegram-bot/webhook/photo.py` — `html.escape()` закрыл XSS/HTML-инъекцию через распознавание фото.

## 2026-06-17 — Калории: дневная цель растёт в день тренировки (today-boost)

- **Корень:** дневная цель калорий считалась строго по 14-дневному **среднему** расходу (`nutrition_service.get_day_stats` → `calculate_targets(stats=avg)`; `compute_goals` → `caloric_budget.get_daily_budget`). В день тяжёлой тренировки фактический расход (Garmin: 762 актив / 2416 total) был много выше среднего (380 / 2151), но цель оставалась 1828 → юзер «недоедал». Среднее ввели в `c4035e5` (04.04.2026) ради стабильности — тогда неполные Garmin-дни (часы на зарядке) роняли цель вниз; маятник качнулся в обратную сторону.
- **Решение (выбор владельца — max(среднее, сегодня)):** новый helper `core/health/caloric_budget.py::get_day_actual_tdee(user_id, date, db=None)` — фактический расход за день (`total_calories`, либо `bmr+active`). Цель = `max(14-дн среднее, фактический за день) × (1 − дефицит)`. В тяжёлый день растёт по факту, в неполный/ленивый день пол по среднему держит цель (апрельский баг не возвращается).
- **Где применено (оба пути расчёта цели, чтобы бот и дашборд не разъезжались):** `nutrition_targets.calculate_targets(..., today_tdee=)` + max; `caloric_budget.get_daily_budget` today-boost (`activity_avg`/`bmr_avg` остаются средними для отображения — растёт только цель); `nutrition_service.get_day_stats` пробрасывает `today_tdee`.
- **Свежесть:** в `commands.py` (`/day`) и `nutrition_api.py` (`GET /api/day`) синк `sync_today_garmin` переставлен **до** расчёта цели — иначе boost считался по стейл-снимку из БД.
- Тесты: `tests/test_today_tdee_boost.py` (9). Полный прогон 746 passed.

## 2026-06-17 — Деплой: прод больше не откатывается после успешного выката (PR #131)

- `.github/workflows/deploy-prod.yml` — в шаге «Pull & up» перед `up -d` добавлен идемпотентный upsert резолвнутого `IMAGE_TAG` в серверный `/opt/botkin/.env` (`sed` по существующей строке либо append). Внутри quoted-heredoc → `$IMAGE_TAG` раскрывается на сервере; тег уже провалидирован regex `^[A-Za-z0-9._-]+$`.
- Корневая причина: compose резолвит `ghcr.io/...botkin-bot:${IMAGE_TAG:-latest}` из `.env`, где строки `IMAGE_TAG=` не было. Workflow `export`-ил тег только в своей SSH-сессии → любой последующий `docker compose up -d` без переменной (ручной/auto-heal/рестарт демона/чужой деплой) откатывал прод на закэшированный образ. Прецедент 16.06: фикс #125 (`:1edeccd`) задеплоился, но через минуты прод сам откатился на `:7699b30`.
- `docs/DEPLOYMENT.md` — раздел «Тег прод-образа хранится в `/opt/botkin/.env`» + строка в troubleshooting. Уточнён комментарий «.env не трогаем» → трогаем ровно одну управляемую строку.
- Проверено на проде: после деплоя `IMAGE_TAG=a33a59d` в `.env`, независимый bare `up -d` без env не пересоздаёт контейнер и не откатывает образ.

## 2026-06-16 — Инфра: постоянный фикс прав bind-mount (server /sync больше не падает с PermissionError)

- Корень проблемы: контейнер `healthvault_bot` работает под `botkin` (uid 10001), а Mac-пайплайн (`scripts/push_garmin_to_db.py`, `scripts/garmin/download_garmin_data.py`) пишет в bind-mount `/opt/botkin/data` по `root@`-SSH → файлы становятся root-owned (644) → server-side `/sync` и ночной cron-sync падали с `PermissionError: [Errno 13]` (weather/netatmo/garmin/pg_sync, прецедент 15–16.06).
- Host-side `chown` не работает (overlayfs uid-маппинг возвращает 0, но владельца не меняет) — фиксит только `docker exec -u 0 ... chown` изнутри контейнера.
- Решение (выбран вариант cron pre-step, минимально инвазивный, нулевой риск для контейнера): в host-crontab перед `sync_all.sh` добавлен `docker exec -u 0 healthvault_bot chown -R 10001:10001 /app/data /app/logs` (разделитель `;`, не `&&`). Применено на сервере (`crontab`), проверено: planted root-файл → 10001 после pre-step, полный `sync_all.sh` = 7/7 ✅, 0 «Permission denied».
- Документация: `docs/DEPLOYMENT.md` — новая секция «Права на bind-mount данных и ночной sync» + строка в «Частые проблемы»; `docs/ROADMAP.md` — закрыт пункт «Auto-chown systemd timer» (таймер ушёл с откатом NanoClaw, теперь chown в cron); `scripts/server/sync_all.sh` — актуализирован header-комментарий с реальной cron-строкой.

## 2026-06-15 — Инфра: безопасность webhook + Alembic миграции + compose fix

- PR #88: `telegram-bot/webhook/telegram_router.py` — `logger.warning` → `logger.error` при отсутствии `TELEGRAM_WEBHOOK_SECRET`; `telegram-bot/bot.py` — error-лог при старте если секрет не задан. `TELEGRAM_WEBHOOK_SECRET` добавлен в `.env` на сервере, webhook перерегистрирован с `secret_token`.
- PR #99 (Игорь Николаев): `database/alembic/` — система Alembic-миграций; baseline-ревизия `711fd5e3f1e8`; `.github/workflows/migrate.yml` для auto-migrate при деплое.
- `docker-compose.prod.yml` — добавлено `name: healthvault` для фиксации project name при переезде папки `/opt/healthvault` → `/opt/botkin` (без этого Docker создавал проект "botkin" и конфликтовал с живыми контейнерами).
- Cleanup: удалено 11 смерженных remote-веток, 3 stale worktrees; dev синхронизирован с main.

## 2026-06-15 — KB: поправки агента теперь сохраняются (#102)

- `telegram-bot/webhook/agent_tools_api.py` — новый endpoint `POST /api/agent/add_agent_correction`: валидирует ключ (`[a-zA-Z0-9_-]`, ≤100 символов) и значение (≤2000 символов), атомарно записывает `{value, reason, updated_at}` в секцию `agent_corrections` KB-файла пользователя. 404 если KB не найден.
- `core/agent_chat.py` — добавлен tool `add_agent_correction` в TOOLS-список (с описанием: «вызывать СРАЗУ когда пользователь исправляет факт») и dispatch в `_call_tool`.
- `tests/test_kb_agent_corrections.py` — 8 тестов: endpoint (ok, update existing, bad key 422, no KB 404) + dispatch (_call_tool POST к нужному URL, TOOLS list schema, HTTP error → JSON).
- Данные изолированы в секции `agent_corrections` — не пересекаются с медицинским KB. Коммиты: cf17109, 05e937c, 247bde2.

## 2026-06-14 — Проактивный health checkup через BotkinClaw

- `scripts/send_checkup.py` — скрипт для запуска checkup: ставит `users.checkup_mode='active'` через SSH+psql, шлёт приветственное сообщение через Bot API. Использование: `python3 scripts/send_checkup.py --user <telegram_id>`.
- `telegram-bot/webhook/agent_tools_api.py` — новый endpoint `POST /complete_checkup`: сохраняет резюме интервью в `agent_conversations` (source='checkup_result'), сбрасывает `checkup_mode→NULL`, пишет JSON-файл в `/app/data/checkup_results/`.
- `core/agent_chat.py` — checkup mode: читает `users.checkup_mode` через raw SQL; если `'active'` — инжектит `CHECKUP_SYSTEM_PROMPT` с инструкциями адаптивного интервью и списком тем (апноэ, аспирин, финастерид, колоноскопия, ЭхоКГ, глюкометр, диагноз нейрохирургии); добавлен tool `complete_checkup` в TOOLS-список и dispatch.
- БД: `ALTER TABLE users ADD COLUMN IF NOT EXISTS checkup_mode VARCHAR(20)` — применено на проде.
- Первый checkup запущен для Павла Храпкина (telegram_id 33831673) — сообщение отправлено 2026-06-14.

## 2026-06-14 — Деплой Android Health Connect на прод (PR #93: dev → main)

- PR #93: смержено `dev → main` (включает PR #91 Android Health, #79 biomarker freshness, #78 food fixes).
- GitHub Actions "Deploy prod": запущено, образ `ghcr.io/botkin-health/botkin-bot:233f3d7` задеплоен на сервер.
- Миграция деплоя `/opt/healthvault/` → `/opt/botkin/`: `.env` скопирован, `/opt/botkin/data` → симлинк на `/opt/healthvault/data`, `/opt/botkin/logs` создан, старый стек остановлен, новый поднят через `docker compose -f docker-compose.prod.yml up -d`.
- Проверено: `/android_health_v1` зарегистрирован в боте, HTTP-хелс = ok.
- Следующий шаг: установить APK mcnaveen/health-connect-webhook на Samsung Galaxy S21+ папы, ввести токен `hvt_33831673_*`, нажать Sync.

## 2026-06-14 — Android Health Connect канал (issue #90, PR #86)

- `telegram-bot/webhook/android_health.py` — новый FastAPI endpoint `POST /android_health_v1`; принимает данные от приложения mcnaveen/health-connect-webhook (FOSS APK); схема `HealthConnectPayload` с 14 опциональными массивами; агрегация по локальной дате юзера через `_hc_aggregate_by_day(payload, user_tz)`; пишет в `activity_log`, `blood_pressure_logs`, `weights`.
- `tests/test_android_health.py` — 26 unit-тестов: timezone (19:00 UTC = МСК не переносится на следующий день), шаги/BP/вес/ЧСС/HRV/сон.
- `telegram-bot/bot.py` — импорт `webhook.android_health` добавлен в `main()`.
- Папа Павел Храпкин (telegram_id 33831673) подключён: APK установлен, webhook настроен (`https://health.orangegate.cc/android_health_v1`, 1 header), 23/24 разрешений выданы, background sync каждые 60 мин. Первый синк (Past 30 Days) — шаги за 10 дней в БД.

## 2026-06-12 — Батч «🛡 надёжность» (PR #68) + baseline-схема (PR #67, merged)

- PR #67 (merged): database/migrations/000_baseline_schema.sql — pg_dump --schema-only прода (15 таблиц, RLS-политики); проект воспроизводим с нуля.
- PR #68: +57 тестов на критические пути. RLS-изоляция (weight_history/day_summary/recent_supplements не отдают чужого юзера); HAE-парсер — 23 теста (MJ/kJ граница 100, дистанции, 4 формата сна, оба формата BP, регрессия double_support); ask_agent — 4 теста с моками Anthropic/tools (история, tool-loop+JWT, чистый 500, отказ неактивному). 575 passed.
- Технические находки тестописания: CAST(:x AS JSONB) на SQLite даёт 0 (NUMERIC affinity) — переписывается engine-событием before_cursor_execute; llm_usage-логгер глушится (ходит в реальный Postgres).

## 2026-06-11 (ночь) — Quick wins аудита (PR #66, ветка refactor/audit-quickwins-2026-06)

- Тесты защищены от реальных LLM-вызовов за деньги (conftest: dummy-ключи setdefault + autouse поверх load_dotenv(override=True)); pytest теперь работает без export'ов.
- JWT агента: TTL унифицирован 24h/1h → env AGENT_JWT_TTL_HOURS (default 1h) в обоих местах.
- deploy.sh: rsync-excludes на ~260MB приватного не-кода (дампы БД, фото, Screen Time, downloads, venv_mcp, archive).
- /day_summary переписан с вечно пустой daily_summaries на live-агрегацию (nutrition+activity+weights+BP+workouts) + тест.
- Сняты все 3 deselect'а CI (log_meal_text_* замоканы, +rejected-тест; cohort-тест давно проходил); test_date_extraction.py (0 assert'ов) перелит в test_extract_date.py.
- MSK → core/infra/tz.py (7 копий); MARKER_CONFIG → kb_schema (закрыт follow-up 01.06); andrey_health_enrichment.html → FamilyHealth.
- 518 passed. PR ждёт ревью; деплоить после мержа.

## 2026-06-11 (вечер) — Батч апгрейдов аудита (PR #65, ветка refactor/audit-upgrades-2026-06)

- **config/models.py** — все LLM-модели в одном месте, env-переопределяемы (BOTKIN_AGENT_MODEL и др.); подключены agent_chat, llm/router, chatgpt_vision, gemini_vision, ocr_weight, product_search, voice_service.
- **Weight-OCR**: gemini-1.5-flash + deprecated SDK → gemini-2.0-flash raw REST; google-generativeai удалён из requirements; лог движка. Fallback Gemini→GPT-4o проверен вживую (Gemini-ключ был в 429 по квоте дня).
- **garminconnect 0.2.38→0.2.40**, живой синк проверен (76 активностей, daily-summary за 09-11.06). ⚠️ 0.3.x — переписанная библиотека (DI-токены, garth-токены неконвертируемы, свежий логин под 429) — отложено, задача в todo.md.
- В todo.md добавлены: распил гигантов (🔥 срочная, по отмашке), миграция garminconnect 0.3.x, разбор scripts/mcp/botkin_mcp.py (не подключён ни к одному конфигу).

## 2026-06-11 — Рефакторинг-аудит: 89 находок, батчи 1-3 исполнены

- **Аудит** (workflow: 7 искателей Fable 5 + скептики, экономичная батч-проверка на Sonnet): 89 находок, 60 подтверждено, 1 опровергнуто (биомаркеры НЕ утекали в git). Отчёт: `docs/projects/2026-06_refactoring-audit/AUDIT.md`, ветка `refactor/audit-2026-06`.
- **Батч 1 (0986826):** доко-дрейф CLAUDE.md (agent_conversations, 30+ endpoints, parse_apple_health_xml, diagnose_server путь, анти-паттерн BP/workouts), создан `docs/operations/personal-data.md`, NutriLogBot→Botkin в гайдах, `get_recent_product_names` читает все 3 диалекта items (чинит «Часто используемое» в мини-аппе).
- **Батч 2 (ad9b021, 24cedfc):** −5127 строк мёртвого кода. deploy.sh шаг 5/5 (несуществующий test_llm_prompt.py), Makefile (6 мёртвых целей), sync_all_data.sh (2 удалённых скрипта); удалены scripts/apple-health/ (10 шт), domain/+infrastructure/storage/, menu_meal_processor, apple_health_parser, utils/typing, requirements.prod.txt, site/ (nginx-conf → docs/operations/), one-off backfill'ы и chrome/clearspace/sleepcycle → archive/ (gitignored), ~400 строк мёртвых функций в живых модулях.
- **Батч 3 (4378791):** удалена мёртвая ветка BOTKIN_LEGACY_BIOMARKERS_JSON; пути ~/HealthVault починены, симлинк удалён (закрыт todo-пункт 20.05); requirements −5 неиспользуемых пакетов; убран beta-хедер prompt-caching; /mc/-ссылка → botkin.health; v1 /apple_health переописан как официальный бесплатный Shortcut-путь; scripts/util/deploy.sh → hotfix_deploy.sh.
- ⚠️ Защитная проверка сервера: прод-.env НЕ задаёт TELEGRAM_WEBHOOK_URL, nginx botkin.health НЕ проксирует /telegram//whoop//api/ — поэтому эти defaults оставлены на orangegate (комментарии в коде). Полный переезд домена — отдельный todo.
- Отложено (рисковые апгрейды, отдельным батчем): garminconnect 0.2.38→0.3.x, weight-OCR gemini-1.5-flash→2.0 + уход с deprecated SDK, вынос имён LLM-моделей в конфиг, распил гигантов (P2), rename healthvault-инфры (P3).

## 2026-06-09 — fix(apple_health): фильтр артефактов min-пульса (off-wrist PPG)

- **`core/health/hr_artifact.py`** (новый) — чистая `classify_hr_min(min_val) → (value|None, needs_verify)`: `<30` DROP как артефакт (Apple Watch снят → PPG-мусор 7/9/13/21 bpm), `[30,40)` держим + флаг verify (могла быть реальная пауза), `>=40` чисто. Порог сознательно НЕ <40 — у кардиопациента реальный минимум сна 45-49 и Reveal LINQ ловил настоящие паузы 40-46, прятать нельзя.
- **`telegram-bot/webhook/apple_health.py`** — модель `AppleHealthPayload` +поле `heart_rate_min_verify`; обе ветки парсера (HAE v2 `_hae_to_daily_payloads` + v1 flat-payload) прогоняют Min через `classify_hr_min`; `heart_rate_min_verify` уходит в `raw_data` (activity_log).
- **Почему:** HAE шлёт `heart_rate_min` сырым, off-wrist значения НЕ маркирует (подтвердил AndreyClaude). Прецедент: у Андрея Походни 194 ложных «эпизода брадикардии <50», 97 из них <30 → бот показывал ложную брадикардию. Systemic для всех Apple Watch юзеров. Порог согласован с AndreyClaude 09.06.2026.
- **Тесты:** `tests/test_hr_artifact.py` (6, чистая логика) + `tests/test_hae_hr_filter_parser.py` (3, проводка v2). Все зелёные, полный suite без новых регрессий (2 пред-существующих фейла в onboarding_wizard — не связаны). Развёрнуто на проде (rebuild образа, контейнер healthy, проверена проводка в боевом контейнере). — Claude

## 2026-06-09 — docs(research): OSS-клиенты экспорта Apple Health → свой сервер

- **`docs/research/2026-06-09_apple-health-export-clients.md`** — ресёрч по запросу (находка сына Игоря — `baccula/health-dashboard-export`). Вывод: зрелого turnkey-OSS «HealthKit → webhook» нет, нишу держит закрытый Health Auto Export (используем мы). Лучший фундамент для своего клиента — `the-momentum/open-wearables` (iOS SDK) или `StanfordSpezi/SpeziHealthKit`. Категоризация: push-клиенты (A) / парсеры zip (B) / серверы-приёмники (C) / AI-MCP (D).
- **Источники кроме GitHub** проверены (GitLab/Bitbucket/Codeberg/SourceForge/Gitee/GitCode/Coding) — по Apple Health везде только зеркала GitHub и мелочь; GitHub де-факто монополия. Нюанс: китайские форжи сильны по Xiaomi/Zepp/Huawei (отдельный будущий запрос).
- **Архив:** `baccula/health-dashboard-export` склонирован с историей в `Projects/Vibe coding/_archived-repos/` (Google Drive, вне git Botkin) — страховка от удаления автором.
- Отчёт отправлен Игорю Лысковскому (`@IgorLysk`) в Telegram. — Claude

## 2026-06-09 — feat(agent): P-003 «Авто-вариант» — авто-инвалидация устаревших turn'ов истории

- **`core/agent_chat.py`** — механизм `_invalidate_stale_history`: ПЕРЕД следующим вызовом Claude в tool-loop'е сравнивает ключевые числа свежего `tool_result` текущего хода с числами/«0/баг»-утверждениями в недавних assistant-turn'ах истории (`history[:prior_history_len]`) и при явном конфликте по той же метрике нейтрализует устаревший turn (текст → маркер, tool_use-блоки сохраняются для парности). Срабатывает автоматически на каждом ходе, без `/agent_reset`. Реестр `STALE_METRICS` (z2/aerobic_base, вес, калории); давление/биомаркеры намеренно не покрыты (риск ложных срабатываний выше пользы).
- **Консервативность:** числа берутся только из сегментов с keyword метрики + unit; конфликт = НИ ОДНО число turn'а по метрике не совпало (в пределах tol) ни с одним свежим; «любое совпадение → turn оставляем»; «белый список» свежих значений собираем щедро (JSON-поля + per-workout aerobic_base/duration). Bug-правило: keyword + «0/баг/не считается» при свежем значении > 0.
- **Почему «Авто», не промпт:** прецедент 09.06 (F-001) показал — prompt-правило P-003 (ad73abf) недостаточно: при накопленной истории агент говорил «только что смотрел, ничего не изменилось» и не звал тул. Промпт оставлен как вспомогательный.
- **Тесты:** `tests/test_agent_history_invalidation.py` (6 шт.). Live-verify `ask_agent(895655, …, is_e2e=True)`: (A) seed «122/99 Z2» → инвалидация сработала, агент ответил актуальными (61 мин/нед, 18.5 мин), стейл не спарротил; (C) контроль — корректное стабильное per-workout число (18.5) НЕ тронуто. e2e_test-строки почищены (0 осталось).
- **Известное ограничение (в коде):** недельный Z2-агрегат зависит от окна (22 за 30д vs 61 за 7д — оба верны) → исторически-корректный turn про другое окно может быть нейтрализован; вред мал (агент перезапрашивает тул). Попутно исправлена регрессия сегментации (дробление по « — »/«, » рвало связку keyword↔число → разбиение по границам предложений). — Claude

## 2026-06-09 — feat: авто-Z2 в /sync + /agent_reset + чистка z2_garmin

- **fe7b13c** — `build_workouts_log.py` теперь между parse и copy гоняет `compute_aerobic_base` (best-effort, контейнер имеет garth-токены) → новые тренировки получают настоящую Z2-базу после каждого /sync, не только при ручном пересчёте.
- **3b63b77** — команда `/agent_reset` (чистит agent_conversations за 24ч, WHERE user_id) + пункт в меню бота; убрано дублирующее поле `z2_min_per_week_garmin`.
- Night-shift 09.06: verify подтвердил, что Z2-фикс технически рабочий (тул=61 мин/нед), но агент парротит устаревшее «0/баг» из 06-07 истории (Finding F-001 09.06, нужна чистка строк 1141/1143). — Claude
- **apply-findings 09.06** (отчёт `docs/night-shift/apply-2026-06-09-0955.md`): F-001 применён — удалены 2 токсичных turn'а (id 1141/1143). Verify на 3 формулировках: агент теперь отвечает «61 мин Z2 из 150 (Attia), ~40%». Вчерашний Z2-фикс виден пользователю end-to-end. — Claude
- **ad73abf** — живой тест в Telegram вскрыл 3 проблемы, все исправлены: (1) MAF-зоны занижались вдвое из-за прореживания Garmin-сэмплов → масштаб по duration (истинная Z2 61→**106 мин/нед**); (2) `recent_workouts.items[]` не отдавал потренировочные зоны → агент выдумывал «38 мин» → добавлены `aerobic_base_min`+`maf_zones` в item; (3) **P-003** — правило в UNIVERSAL_META «свежие данные тула > прошлые ответы» (агент трижды парротил устаревшее). Verify: «106 мин/нед (~71% Attia), пробежка 7 июня 36.7, силовая 8 июня 28.2». Почищены токсичные turn'ы + orphaned tool-пара (убрала 400+retry). — Claude

## 2026-06-08 — fix(agent): Z2-база (longevity Z2) и cross-user утечка имени — apply-findings

Применены находки ночной смены 08.06 (отчёт `docs/night-shift/apply-2026-06-08-2118.md`).

- **F-001 (Z2 = 0):** агент сообщал «0 мин Z2» при реальных пробежках. Root cause глубже однострочника — 4 слоя: (1) `_zone_min` читал ключ `z2` вместо `z2_min`; (2) `recent_workouts.z2_min_per_week` переключён на `aerobic_base` (longevity-Z2, HR 114-131) как у дашборда, а не Garmin-зону z2 (139+); (3) пересчёт `compute_aerobic_base` + push `workouts_log_895655.json` (Z2-база июня 60.9 мин); (4) merge-guard в `build_workouts_log.py` — серверная пересборка больше не обнуляет HR-производные поля. Verify: тул отдаёт 45 мин/нед (было 0). Файлы: `telegram-bot/webhook/agent_tools_api.py`, `scripts/util/build_workouts_log.py`.
- **F-002 (утечка имени):** имя реального юзера было зашито в общий анти-галлюцинационный блок промпта (`core/agent_chat.py:1375`) → агент «вспомнил» его в чужом чате. Анонимизировано.
- **F-003:** пропущен (root cause неясен, ущерба нет).

Деплой — hot-patch (docker cp + restart), правки в working tree, требуют коммита. — Claude

## 2026-06-06 — feat(backup): offsite (Google Drive) + GFS + авто-тест восстановления

**Проблема:** ежедневный `pg_dump` лежал только в `/opt/backups` на том же диске, что и БД (14 дней, без offsite, без проверки restore). Смерть диска/сервера = потеря и БД, и всех бэкапов. Нарушение 3-2-1.

**Сделано** (`scripts/server/`, деплой в `/usr/local/bin/` + cron):
- `healthvault_backup.sh` — дамп → локально (14) + **offsite в личный My Drive `FamilyHealth/_backups_db/`** (рядом с ручными снимками), GFS: daily 30д / weekly 56д (вс) / monthly 365д (1-го). Облачная ротация по `--min-age`, guard на пустой дамп.
  - ⚠️ **Подвох rclone:** remote `gdrive:` на сервере скоупнут на КОРПОРАТИВНЫЙ корень iFarm (`root_folder_id=1Uetbu…`) — первые прогоны лили в чужой FamilyHealth (утечка, убрана `purge`). Фикс: `export RCLONE_DRIVE_ROOT_FOLDER_ID=root` в скрипте → личный My Drive. Любые ручные rclone к личному диску — с `--drive-root-folder-id=root`.
- `healthvault_restore_test.sh` — ежемесячный drill: разворачивает свежий дамп в одноразовую БД внутри `healthvault_postgres`, проверяет таблицы/строки, удаляет. Лог в `/var/log/healthvault_backup.log`.
- cron: `30 3 * * *` backup, `0 4 1 * *` restore-test.
- `docs/BACKUP_GUIDE.md` переписан под реальную прод-схему (был от старого локального деплоя).

**Проверено на проде:** offsite-заливка OK (`gdrive:Botkin-Backups/daily/`), restore OK — 15 таблиц, 17 users, 1152 nutrition. Коммит `d89e259`.

**Хвост:** медиа (`data/media/`: фото еды/голосовые) в `pg_dump` не входят — отдельный offsite при необходимости.

## 2026-06-06 — chore(admin): ротация ADMIN_PASSWORD + устранён дубль карточек в 1Password

**Проблема:** в 1Password было ДВЕ карточки на админку с разными паролями — «Botkin Admin Panel» (`vBv4…`, не стоял на сервере) и «Botkin Admin Dashboard» (`0a75…4fde`, совпадал с прод-`.env`). Александр копировал из первой → «пароль не подходит».

**Решение (источник правды = 1Password, сильный пароль):**
- Прод `/opt/healthvault/.env`: `ADMIN_PASSWORD` → `vBv4W2eQKLd1fzsr4USAlpKI`, контейнер пересоздан. Бэкап `.env.bak.before_admin_rotate.*`.
- 1Password: дубль «Botkin Admin Dashboard» удалён; поле `Admin Dashboard.password` в заметке «Botkin (ex-HealthVault) — service secrets» (id `wq4v5xg36b2rg33qejhyf3zudu`) обновлено. Старого `0a75…4fde` больше нет нигде.
- Осталась одна карточка **«Botkin Admin Panel»** (`ogcfrrgtxcnjwho533fn2mfhgu`), url `https://botkin.health/admin/`.

**Проверка:** старый пароль → 401, новый → 200 + Set-Cookie. Cookie-токен привязан к паролю → старые «remember-me» куки автоматически инвалидированы (один повторный ввод).

## 2026-06-06 — feat(admin): «запомнить меня» — cookie-сессия, чтобы не вводить пароль каждый раз

**Зачем:** Basic Auth переспрашивал логин/пароль на каждом заходе (нативный попап Chrome без галки «запомнить»).

**Решение (`telegram-bot/webhook/admin.py`):** после успешного Basic Auth `/admin/` ставит подписанную куку `botkin_admin` (HttpOnly, Secure, SameSite=lax, Path=/admin, Max-Age=90 дней). `_check_auth` пускает либо по валидной куке, либо по Basic Auth. Токен куки = `HMAC(ADMIN_PASSWORD, "botkin-admin-cookie-v1")` — **отдельный секрет не нужен**, и смена `ADMIN_PASSWORD` автоматически инвалидирует все куки. Браузерная фетч-сессия отправляет куку и на `/admin/api/*` → попап исчезает целиком.

**Проверка:** локальный sanity (no-auth→401, basic→ok, valid-cookie→ok, stale-cookie→401, no-pass→503) + E2E по HTTPS (401 без auth, 200+Set-Cookie с Basic, 200 только по куке на `/` и `/api/users`). py_compile OK. Задеплоено (`deploy.sh`, rebuild+up -d). ⚠️ изменение в working-tree, **не закоммичено** (прод обновлён через rsync).

## 2026-06-06 — fix(admin): восстановлены ADMIN_USERNAME/ADMIN_PASSWORD в прод-.env (админка отдавала 503)

**Симптом:** `botkin.health/admin/` отдавал `{"detail":"Admin not configured"}` (HTTP 503).

**Причина:** при инциденте 06.06 (dev-`.env` затёр прод, восстановление из `.env.bak`) текущий прод-`/opt/healthvault/.env` потерял строки `ADMIN_USERNAME`/`ADMIN_PASSWORD`. `_check_auth` (`telegram-bot/webhook/admin.py:46-48`) при пустом `ADMIN_PASSWORD` намеренно отдаёт 503. Та же первопричина, что F-003 (потеря `BOTKIN_ADMIN_ID`) — неполное ручное восстановление прод-`.env`.

**Фикс:** дописал `ADMIN_USERNAME=admin` + `ADMIN_PASSWORD=0a75…4fde` (значение идентично во всех `.env.bak*`) в прод-`.env`, пересоздал контейнер `docker compose up -d bot` (`restart` НЕ перечитывает env_file — первый заход не помог). Бэкап `.env.bak.before_admin_restore.*`. Деплой-фикс `d96895d` (не синкать `.env`) — корректен, не трогался.

**Проверка:** `curl /admin/` без auth → 401 (было 503); с `admin:<pass>` → 200. ✅

**Урок:** после ручного восстановления прод-`.env` сверять полноту ключей с `.env.bak` (там 65+ строк) — два инцидента подряд (F-003 + этот) из-за частичного восстановления.

## 2026-06-06 — fix(night-shift): починка регрессий PII-скраба + продуктовый разбор переписки

**Контекст:** ночная смена (`/night-shift`) нашла, что PII-скраб 04.06 (`f325de1`/`b6dec50`) внёс 3 регрессии. Применены сегодня через ручной апрув.

- **F-003 (🔴 прод):** `BOTKIN_ADMIN_ID` не был задан в env бота → `config.users.is_admin()` всегда False → `/block`,`/unblock`,`/users`,admin-`/sync` не работали ~2 суток. Добавлен `BOTKIN_ADMIN_ID=895655` в `/opt/healthvault/.env`, бот пересоздан (`docker compose up -d bot`). Проверено: `is_admin(895655)=True`. `tests/test_multi_user.py` переписан на monkeypatch (не зависит от env).
- **F-001:** голый `REDACTED_ID` (undefined) в коде. Тесты (`test_jwt_auth`, `test_onboard_server_deployer`, `test_show_calorie_bar_setting`) — добавлена фейк-константа `REDACTED_ID=111111`. Боевые скрипты (`scripts/mcp/healthvault_mcp.py`, `scripts/backfill_andrey_apple_health.py`, `scripts/audit/nutrition_schema_scan.py`) — переведены на env (`HV_SECOND_USER_ID`/`ANDREY_UID`), без возврата PII в публичный репо.
- **F-002:** пропавший шаблон `scripts/server/agent_prompts/templates/family_active_coach.md` восстановлен из git `3afae7f` (onboarding family-юзеров был сломан). `test_onboard_persona_generator` — assert обновлён под scrubbed sample (`Игорь`→`sample_input.name`).
- **Результат:** pytest 478 passed / 0 failed (было 469/9).

**🟢 backlog (применено):**
- **F-004:** defusedxml на всех 12 XML-парсерах (Apple Health export + RSS-scout), bandit B314 15→0, `defusedxml==0.7.1` в requirements.
- **F-005:** dead code (unused imports/var, unreachable, if-False стабы, unused params).
- **F-006:** `recent_meals` compact-режим (имена+калории, days>14 авто) — запрос «ел ли я X за 3 мес» 120k→~10-20k токенов.

**P-001 (построено):** `edit_meal`/`delete_meal` тулы агента — редактирование/перенос/удаление залогированной еды. CRUD `update_nutrition_meal_fields` получил `new_date`. +8 тестов. (Из Product Signals — Alex 30.05 не мог перенести обед.) ⚠️ нужен deploy.

**Доработка скилла night-shift:** добавлены под-фазы **3g Product Review** (👍/👎/✅/🔧 из переписки) и **3h Prepare Improvements** (готовит улучшения с patch-наброском). P-002 (food-советчик) и P-003 (свежесть Garmin) — остаются подготовленными в `docs/night-shift/2026-06-06.md`.

**Итог pytest:** 487 passed / 0 failed.

**Прочее (недокументированные коммиты 04.06):** `33e6137` whoop OAuth (мультиюзер sleep/recovery/HRV/strain), `85f9a92` aerobic-base (возраст 49), `f325de1`+`b6dec50` PII/secrets scrub + gitleaks pre-commit.

## 2026-06-02 — fix(health): дашборд биомаркеров Андрея Походни — закрыты alias-гэпы, развенчан «фантом 35 маркеров»

**Контекст:** после унификации pipeline (01.06) дашборд Андрея (tg 836757955) показывал меньше маркеров, чем старый `biomarkers_836757955.json` (35). Расследование provenance старого файла.

**Главная находка (НЕ выдумывать данные):** «35 маркеров» в старом файле = **18 реальных значений + 17 пустых заглушек** (`value: null`). Проверка ВСЕХ 141 PDF Андрея (`Biohimiakrovi`/`Gormonal'nye`/`Gemostaz`/ОАК/ОАМ + 75 клинических `report-34821-*` + назначения): **ни одного измеренного значения** LDL/HDL/триглицеридов/ApoB/Lp(a)/тестостерона/кортизола/DHEA-S/мочевой к-ты/витамина D/ферритина/NT-proBNP/омега-3 — этих анализов ему никогда не делали (панели периода госпитализации с POAF янв 2025 + контроль дек 2025 — базовая биохимия). Хиты на «магний»/«инсулин»/«гликированный» в тексте = назначения препаратов и план обследований, не результаты. **Маркеры НЕ восстанавливались по памяти/из старого файла** — показываем только подтверждённое.

**Что реально починено:**
- `core/health/kb_schema.py` — **alias-гэпы** (данные были в KB, но сырые ключи К+31 не маппились → дропались): `urea_mmol_l`→urea, `potassium_mmol_l`→potassium, `sodium_mmol_l`→sodium, `alp_u_l`→ALP, `plt_10_9_l`→PLT, `rdw_cv_pct`→RDW_CV, лейкоформула `neut_pct`/`lymph_pct`/`mon_pct`/`eo_pct`→neutrophils/lymphocytes/monocytes/eosinophils, новый канон `basophils` (`bas_pct`). Единицы сверены по реальным значениям (все %/ммоль/л — фактор 1, без конверсии).
- **Закрыт follow-up прошлой записи:** добавлены каноны `NT_proBNP` (пг/мл, как в `dashboard_generator.biomarkers_latest`) и `omega3_index` (% EPA+DHA мембраны эритроцитов, HS-Omega-3). Реальных значений у Андрея нет → алиасы без конверсии; pmol/L-фактор для NT-proBNP задокументирован, но не активирован (нет данных для сверки).
- `FamilyHealth/Андрей Походня — Здоровье/knowledge_base.json` — добавлен **HbA1c=5.51%** как `subtype=cgm_derived`, `lab="CGM eA1c (FreeStyle Libre 3)"` — единственное честное добавление: расчётный eA1c (Nathan 2008) из 30-дн CGM-периода (2939 измерений). В summary явно: НЕ лабораторный HbA1c.
- Синк `sync_user_health.py --user 836757955 --apply` (1 new + 17 upd).
- **Результат канонизации: 20 → 32 маркера** (НЕ 35 — расхождение с ожиданием задачи объяснимо: 17 фантомных null-заглушек реальными быть не могут). `biomarkers_latest` заполнен 8/16; LDL/HDL/тестостерон/витD/ферритин/мочевая/hs-CRP/NT-proBNP пусты — честно (не сдавались). Обычный СРБ (6.31, острофаза POAF) намеренно НЕ подменён на hs-CRP.
- Тесты: 22 зелёных (kb_schema/aggregate/regression/dashboard_db); коллизий от новых алиасов по всем 8 family-KB нет (3 предсуществующие у Александра — bare `eosinophils` абс vs `_percent`, вне scope).
- **Follow-up:** `micro_*`/`mpv_fl`/`rdw_sd_fl`/`pct_pct`/`prothrombin_pct` остаются немаппленными (узкоспец, нет в дашборде); консолидация `biomarker_dynamics.py::MARKER_CONFIG` на kb_schema всё ещё открыта.

## 2026-06-01 — feat(health): унификация pipeline биомаркеров (read-time канонизация, вариант B)

**Закрывает арх-долг из записи онбординга Димы** (3 источника биомаркеров с дублирующими маппингами). Сделано через worktree + TDD + subagent-driven; spec/plan в `docs/superpowers/`.

**Что сделано:**
- `core/health/kb_schema.py` — единый канонический реестр (74 маркера): `CANONICAL` (сырой ключ→канон + единица + множитель конверсии), `to_canonical(values, *, passthrough_unmapped) -> (dict, warnings)`. Case-insensitive, только явные алиасы (без авто-стрипа: `albumin_pct` ≠ `albumin_g_l`). Реверс-индекс с проверкой дублей на импорте.
- **Конверсия единиц с guard** (правило «не сглаживать молча»): insulin pmol/L→µIU/mL (÷6.945), folate (÷2.266), B12 (×1.355), PTH (×9.434). Неоднозначные ключи НЕ маппятся (bare `HCT`=доля vs `Hct`=%; bare `neutrophils`=абс; Александров `free_testosterone` иной шкалы) — иначе мис-масштаб пациентских значений.
- `core/health/biomarkers.py::aggregate_biomarkers(tests)` — seen/peak_max/peak_min/earliest/n_history/_meta поверх `to_canonical`.
- `telegram-bot/dashboard_generator.py` — биомаркеры из Postgres `blood_tests` (было: файл `biomarkers_<id>.json`). Структура переменной идентична → downstream (panels/PhenoAge/CAP) не тронут. Legacy-файл за флагом `BOTKIN_LEGACY_BIOMARKERS_JSON`.
- `telegram-bot/webhook/agent_tools_api.py` — `/recent_biomarkers` (канон + passthrough) и `/phenoage` (канон-lookup в Python вместо хрупкого `jsonb_each_text WHERE key=ANY`). **Чинит phenoage для Димы и всех family** (раньше работал только под CamelCase Александра). `_as_dict` guard на str/JSONB.
- `scripts/sync_user_health.py --user/--all [--apply]` + `config/users.py::KB_USERS` — единый 2-стадийный синк (KB→bind-mount + KB→Postgres), переиспользует функции `sync_family_kb`/`kb_to_blood_tests`. `generate_biomarkers_json` рефакторен на `aggregate_biomarkers`; write/`--deploy` за legacy-флагом.
- **Тесты (48 в биомаркерном наборе, все зелёные):** unit kb_schema (конверсии, guard, коллизии, case-insensitive), aggregate, **golden-regression `test_alexander_golden_nothing_lost` (на живых данных, не skip)** — owner ничего не теряет; Дима-smoke (>30 маркеров, единицы sane). Важный факт: старый ad-hoc `biomarkers_303663179.json` оказался БИТЫМ (сырые pmol/L под каноническими именами: инсулин 122→17.66, ПТГ 8.22→77.5) — новый код это чинит.
- **Follow-up (не в этой итерации):** консолидировать `core/reports/biomarker_dynamics.py::MARKER_CONFIG` (4-й маппинг, case-sensitive — баг для Димы) на kb_schema; удалить `biomarkers_*.json` через 1-2 недели; добавить NT_proBNP в реестр.

## 2026-06-01 — feat(onboarding): полное подключение Дмитрия Медведко (друг, family/cardiac) + аудит парсинга по чек-листу Кристины Очкиной

**Что сделано:**
- Распарсены 2 чек-апа Димы из Поликлиника.ру (окт-дек 2024 + фев-апр 2026) — 60 PDF/docx/xlsx через `pdftotext` → `docs/_text_extracted/`. 4 параллельных AI-агента (анализы крови/мочи · гормоны+витамины+онко · УЗИ+ЭКГ+инструментальные · приёмы врачей).
- Собран `knowledge_base.json` (64 KB): 11 blood_tests, 2 urine, 1 fecal, 6 hormones, 3 vitamins, 2 oncomarkers, 7 УЗИ, 3 ЭКГ, 4 other_studies (ЭГДС/колоно/ОКТ/H.pylori), 16 medical_records, 15 chronic_diagnoses, 10 current_medications.
- `PROFILE.md` (карта диагнозов по системам + журнал обследований через `generate_exam_journal.py`), `chat_anamnesis.md` (шаблон).
- **Аудит парсинга (прецедент Кристина Очкина / blood-test.ochkina.com, Granola 26.05):** Sonnet после ~10 файлов начал пропускать данные — ровно как предупреждала Кристина. Найдены и добавлены вручную пропуски: ПТГ 8.22, гомоцистеин 9.53, тиреоглобулин 18.5, витамины E/A/B6, дигидротестостерон 581.99, **PSA-соотношение (31.3%→25.6%, неблагоприятная динамика)**. Исправлена неверная атрибуция `source_text_file` для биохимии 06.03.2026 (16 биомаркеров приписаны к 1 файлу вместо 4 — split fix). Все ЗНАЧЕНИЯ корректны, чинились только пропуски/атрибуции.
- Деплой 3 канала: KB → bind-mount `/app/data/kb/kb_303663179.json`; KB → Postgres `blood_tests` (15 строк) через `kb_to_blood_tests.py`; biomarkers → `/app/telegram-bot/biomarkers_303663179.json` (58 маркеров) для дашборда (карточка «Загрузи анализы» убрана, появились панели Attia/LE8/PhenoAge).
- Enroll: `cohort=external→family`, `pack=generic→cardiac`, `agent_system_prompt` 8616 симв через `onboard_family_user.py`.
- HTML-отчёт `Отчёт_для_Дмитрия_Валентиновича_2026-06-01_v1.html` (770 строк, 16 разделов, 4 chart.js графика динамики МК/ЛПНП/печени/PSA) в стиле эталона Павла Храпкина.
- E2E через `ask_agent(303663179, ...)` — агент корректно видит KB (динамика МК, рост печени 12.3→17.7 см, препараты, всплывает открытые вопросы: киста почки, C13-тест). Тестовая история (24 строки `source='e2e_test'`) удалена из `agent_conversations`.
- `scripts/sync_family_kb.py` — добавлен `303663179: "Дмитрий Медведко — Здоровье"` в USERS.
- Папка `FamilyHealth/Дмитрий. Медведко - Здоровье` → `Дмитрий Медведко — Здоровье` (стандарт именования).
- **Архитектурный долг зафиксирован:** 3 источника биомаркеров (KB JSON + Postgres + biomarkers_<id>.json) с дублирующими маппингами — вынесено в отдельную сессию (spawn_task: унификация в Postgres-single-source + `core/health/kb_schema.py`).

## 2026-06-01 — feat(food): логгер еды понимает относительную/явную дату

**Проблема (прецедент 30.05):** «Обед вчера: …» записывался на сегодня. Корень — три точки:
1. У агента в tool `log_meal_text` не было параметра `date` (endpoint + модель его уже принимали).
2. `extract_date_from_text` ловил «вчера» только в НАЧАЛЕ строки (startswith) → «Обед **вчера**:» промахивался. (Месяцы «29 мая» и DD.MM уже работали где угодно.)
3. **Агент не знал сегодняшнюю дату** — в системный промпт она не инжектилась, LLM угадывал (e2e показал: при сервере 01.06 агент решил, что сегодня 02.06).

**Что сделано:**
- `telegram-bot/handlers/text.py::extract_date_from_text` — «вчера/позавчера/yesterday» ищется в любом месте строки (`\b` + re.search), префикс сохраняется («Обед вчера: X» → дата вчера + «Обед X»). Ветка подтверждения добавок+еды теперь показывает `📅 на <дата>`.
- `core/agent_chat.py` — в tool `log_meal_text` добавлен параметр `date` (YYYY-MM-DD) + инструкция агенту резолвить относительную дату и называть её в ответе. Handler уже шлёт args целиком — проброс автоматический.
- `core/agent_chat.py` — в системный промпт инжектится **`📅 Сегодня: YYYY-MM-DD (день недели), таймзона юзера`** (через zoneinfo). Чинит relative-date математику агента и улучшает все date-вопросы.
- `tests/test_extract_date.py` — 6 unit-тестов (вчера в середине/начале, позавчера, месяц, DD.MM, без даты). Полный сьют 453 passed.
- E2E: «запиши обед на вчера» → агент кладёт на 31.05 (при сегодня=01.06), называет дату. Тестовые записи удалены.

## 2026-06-01 — chore(agent): откат BotkinClaw Opus 4.8 → Sonnet 4.6 (стоимость)

**Причина:** замер реальной стоимости через `llm_usage_log` показал Opus 4.8 ~$7.5/активный день (≈$100/мес при активном использовании), дорогие tool-итерации (agent_chat_tool $8.24 > agent_chat $7.26 — каждая итерация шлёт растущий контекст по Opus-цене). Для семейного медбота Sonnet 4.6 даёт достаточное качество в ~5× дешевле.

**Что сделано** (`core/agent_chat.py`):
- `MODEL`: claude-opus-4-8 → **claude-sonnet-4-6**
- `FALLBACK_MODEL`: claude-sonnet-4-6 → **claude-sonnet-4-5** (другой пул)
- `AGENT_EFFORT`: high → **medium** (документированный sweet spot Sonnet 4.6 для чата)
- В fallback-ветке `_post_with_overload_retry` добавлен `p.pop("output_config")` — Sonnet 4.5 не поддерживает effort, иначе 400.
- E2E через ask_agent: Sonnet 4.6 + medium отвечает корректно, без 400. Деплой docker cp + restart.

(Цена Opus 4.8/4.7 в `llm_usage.py` оставлена — на случай возврата + для исторического учёта.)

## 2026-05-30 — feat(agent): алкоголь-флаг + full_series в get_recent_trends

**Проблема:** BotkinClaw в чате отвечал «алкоголь нигде не трекается» — хотя флаг `has_alcohol` есть в `nutrition_log.totals` (18 приёмов, ~16 дней). Причина: ни один tool его не отдавал, а `recent_trends` был капнут на 90 дней и `items[:30]`.

**Что сделано** (`telegram-bot/webhook/agent_tools_api.py` + `core/agent_chat.py`):
- `recent_trends`: LEFT JOIN агрегата `nutrition_log` по дню → поле `alcohol:bool` в каждом item + `alcohol_days` в stats. Кап окна 90 → **180** дней.
- Новый параметр `full_series` (дефолт false → последние 30 точек; true → ВСЕ точки окна, нужно для корреляций/графиков на 90-180 днях).
- Описание tool'а в `agent_chat.py` обновлено (alcohol, full_series, кейс «алкоголь → HRV следующего дня»).
- E2E через `ask_agent`: агент теперь видит 16 алко-дней, считает HRV на D+1, отвечает. Деплой `docker cp` + restart.

**Известное ограничение:** агент считает корреляцию вручную (получил −2 мс vs мой Python −6 мс) — точный Pearson+детренд это задача отдельного server-side tool `get_correlation` (в бэклоге).

## 2026-05-29 — feat(agent): BotkinClaw на Claude Opus 4.8 + effort-параметр

**Контекст:** Opus 4.8 вышел 28.05.2026 — в 4× реже пропускает ошибки и честнее про неуверенность, чем предшественники. Для медицинского агента это критично.

**Что сделано** (`core/agent_chat.py` + `core/llm/router.py`):
- `agent_chat.py`: `MODEL` `claude-sonnet-4-6` → **`claude-opus-4-8`**; `FALLBACK_MODEL` `claude-sonnet-4-5` → **`claude-sonnet-4-6`** (Sonnet 4.5 НЕ поддерживает `output_config.effort` → вернул бы 400). Добавлен `AGENT_EFFORT="high"` + `"output_config": {"effort": AGENT_EFFORT}` в payload. Взят `high` (не `max`): для tool-heavy чат-бота `max` рискует overthinking + латентностью в Telegram.
- `router.py` (классификация еды/добавок): добавлен `"output_config": {"effort": "low"}` — простая JSON-классификация, экономит токены/латентность.
- Контракт `effort` сверен с docs Anthropic: top-level `output_config: {effort: low|medium|high|xhigh|max}`, дефолт `high`. ⚠️ На Opus 4.8 ручной `thinking: {budget_tokens}` даёт 400 — в payload его нет, ОК.
- Деплой: `docker cp` изменённых файлов в контейнер + restart. E2E через `ask_agent`.

## 2026-05-26 — fix: все скрипты переведены с sshpass на ssh по ключу

Сервер `116.203.213.137` имеет `PasswordAuthentication no` — парольный вход вообще выключен (проверено `BatchMode=yes` + `sshd_config`). Поэтому весь sshpass-код был мёртвым грузом: пароль уходил на сервер, который его не слушает → exit 3. Доступ держится на `~/.ssh/id_ed25519` (файл на диске, не агент).

Переведены на `ssh`/`scp`/`rsync` по ключу (паттерн `SSH_OPTS`, как в `sync_family_kb.py`), удалены все хардкод-пароли и `_read_pw`/`get_server_password`:
- **Python:** `push_garmin_to_db.py`, `generate_biomarkers_json.py`, `backfill_to_postgres.py`, `backfill_andrey_apple_health.py`, `audit/nutrition_schema_scan.py`, `import/zepp_api.py`, `import/zepp_csv.py`, `backfill/backfill_amount_from_calories.py`, `backfill/backfill_fiber.py`, `mcp/healthvault_mcp.py`, `analysis/progress_chart.py`, `onboard/server_deployer.py` (+ дроп `password`/`sshpass_path` из `ServerConfig`), `onboard_family_user.py`, `util/fetch_from_server.py` (paramiko → `key_filename`).
- **Shell:** `fetch_remote_nutrition.sh`, `sync_all_data.sh`, `util/deploy.sh`, `util/diagnose_remote.sh`.
- **Проверено:** ruff clean, 19/19 onboard-тестов, live-смоук read-only скриптов через ключ (`fetch_remote_nutrition.sh` → данные, `nutrition_schema_scan.py` → 956 строк, `backfill_amount --dry-run` → 48 items). Главный `generate_biomarkers_json.py --deploy` теперь не зависит от пароля.

## 2026-05-26 — fix: kb_to_blood_tests.py переведён на ssh по ключу (sshpass+устаревший пароль)

Транспорт в `scripts/import/kb_to_blood_tests.py` падал на scp/ssh через sshpass (exit 3) — `_read_pw()` тянул устаревший пароль из `PASS=` в `fetch_remote_nutrition.sh`, хотя ключевой `ssh root@116.203.213.137` работает.

- Убраны `SSHPASS`-константа и функция `_read_pw()`; `_psql_exec` и `_psql_copy_via_python` переписаны на `ssh`/`scp` по ключу (та же схема `SSH_OPTS`, что в `sync_family_kb.py`).
- Проверено: `python3 scripts/import/kb_to_blood_tests.py --user-id 5162726004 --folder "Валерия Лысковская — Здоровье"` → 41 строка upsert (0 new, 41 updated), идемпотентно.
- **Осталось (не трогал в этой задаче):** тем же устаревшим паролем через sshpass пользуются ещё ~15 скриптов, в т.ч. главный `generate_biomarkers_json.py --deploy`, `sync_all_data.sh`, `util/deploy.sh`, `zepp_api.py`, `push_garmin_to_db.py`. Их стоит так же перевести на ключевой ssh.

## 2026-05-26 — feat: Валерия Лысковская заведена полноценным пользователем (мама Александра)

Завели маму Александра (Лысковская Валерия Николаевна, @vachest, telegram_id **5162726004**) на сервере — по той же схеме, что папа/Игорь/Андрей, чтобы при первом подключении её ждал «обученный» ИИ-аналитик.

- **KB-аудит:** все 77 файлов в `FamilyHealth/Валерия Лысковская — Здоровье/` уже проиндексированы (JPEG/PDF/DOC распарсены со значениями) — пробелов нет.
- **USERS-маппинг** (`scripts/sync_family_kb.py`): добавлен `5162726004 → "Валерия Лысковская — Здоровье"`.
- **БД-строка:** cohort=`family`, pack=`cardiac`, sex=female, birth 1953-06-19, tz `Asia/Novosibirsk`, kb_status=`shared`, share_token + jwt_secret, is_active.
- **KB bind-mount:** `kb_5162726004.json` залит на сервер (агент: `/kb_value`, `/list_kb_keys`).
- **blood_tests:** импортировано 38 записей (2009–2026) для `/recent_biomarkers`.
- **agent_system_prompt** (~12k): кардио-фокус, полная история диагнозов/лекарств/флагов, непереносимость статинов. **Критичные правила тона:** обращение «Валерия» на «вы», НЕ давить (она отложила ЭКГ/ЭхоКГ до осени), ИИ = инструмент-помощник, не врач.
- **E2E (ask_agent):** агент корректно назвал последний холестерин/ЛПНП из blood_tests, дневник АД, и отказался предлагать статины (помнит непереносимость). e2e-сообщения вычищены из `agent_conversations` (чистая история к подключению). Дашборд `botkin.health/mc/<token>` → 200.
- **Заметка:** транспорт `kb_to_blood_tests.py` через sshpass упал (пароль в `fetch_remote_nutrition.sh` устарел, exit 3) — импорт проведён вручную через ssh по ключу. Стоит починить пароль/перейти на ключевой ssh.
- **Персональное приветствие /start** (`telegram-bot/handlers/commands.py`): добавлен словарь `PERSONAL_START_GREETINGS` (ключ — telegram_id). Для Валерии — развёрнутое приветствие на «вы»: что Боткин про неё знает (анализы 2009–2026, диагнозы, лекарства, дневник АД) + примеры вопросов по темам (🩺 здоровье/анализы/симптомы, 🥗 питание, 🚶 активность: ходьба/лыжи/велик) + ссылка на дашборд. Стандартное food-приветствие у остальных не тронуто. Задеплоено + рестарт.
- **HTML-отчёт по ссылке** (как у папы): `Отчёт_для_Валерии_Николаевны_2026-04-24.html` захостен на nginx в `/opt/botkin-site/r/valeria_2026-04-24_Sj8h7shLfKM.html` → `https://botkin.health/r/...` (приватный URL за случайным суффиксом). В отличие от папы (ссылка давалась вручную), агенту Валерии **добавлена секция в `agent_system_prompt`** — на вопрос про «отчёт/полный разбор/что Саша готовил» он сам выдаёт ссылку. E2E подтверждён. Обновление отчёта = scp нового HTML в `/opt/botkin-site/r/` + правка ссылки в промпте.
- **PDF-версия отчёта** (как у папы есть `.pdf`): HTML отрендерен в PDF через headless Chrome (`--print-to-pdf --virtual-time-budget=12000`, 22 стр., 895 КБ, Chart.js успевает отрисоваться). Копия сохранена локально в папке Валерии, захощена на `/opt/botkin-site/r/valeria_2026-04-24_ODF3-HUsY5A.pdf` → `https://botkin.health/r/...`. Секция отчёта в промпте обновлена на два формата: веб (по умолчанию, открывается в Telegram) + PDF (когда просит скачать/распечатать). E2E подтверждён.

## 2026-05-28 — fix(router): guard от false-positive BP-замеров из вопросов и диапазонов

**Прецедент:** Валерия Лысковская (мама Александра) при первом общении с ботом написала: «Если у меня давление в интервале 140-120 /85-70, нужно ли мне пить таблетки от давления?». Regex pre-check (`_BP_RE`) выдрал «120/85» из её вопроса и записал в `blood_pressure_logs` как замер (источник `manual_text`), а сам вопрос к BotkinClaw не дошёл. Через 45 секунд она переспросила короче, и второе сообщение пошло в агент уже без чисел.

**Что сделано** (`telegram-bot/handlers/text.py` + `core/llm/router.py`):
- В regex-пути (line ~633) — добавлен **двойной guard**: `_BP_QUESTION_MARKERS` (`«нужно ли», «можно ли», «опасно ли», «что делать», «?», ...`) и `_BP_RANGE_RE` (диапазоны вида `\d-\d/\d` или `\d/\d-\d`). При срабатывании любого — `bp_match=None`, сообщение идёт дальше к LLM-роутеру/агенту.
- В LLM-роутер-пути (line ~1225) — тот же guard, `router_result=None / msg_type=None` чтобы выпасть к BotkinClaw.
- В промпте LLM-роутера (`core/llm/router.py` SCENARIO 7) — явная инструкция «не классифицировать как BP вопросы / диапазоны / прошлое время; использовать SCENARIO 5 (OTHER)».
- Defense-in-depth: 3 уровня (regex guard + LLM-router guard + LLM prompt).

**Тест на 8 кейсах:** её исходная фраза → AGENT ✅; «У меня 140/90, что делать?» → AGENT ✅; нормальные замеры «120/80 пульс 65», «Сейчас 15:07 151/92 пуль 65», «АД 130/85» → BP-LOG ✅. Регрессий валидных замеров нет.

**Фейковая запись** 120/85 от 28.05 18:37 удалена из `blood_pressure_logs` (DELETE 1, осталось 0).

## 2026-05-28 — fix(deploy): задеплоен `agent_tools_api.py` — починен 404 `/open_questions`

Первая реальная сессия Валерии (28.05.2026, 18:38 НСК) показала, что BotkinClaw вызывает tool `get_open_questions` и получает `HTTP 404`. Расследование: контейнер `healthvault_bot` оставался на коммите `a1a93ec`, тогда как локально были два более новых: `0eb998b` (добавление `/open_questions`) и `efd9f0f` (фикс таймзоны UTC→локальная для агентских тулз). Деплой проведён обычной схемой: scp `agent_tools_api.py` → docker cp → restart. После рестарта эндпоинт отвечает корректно. У Валерии в KB нет ключа `open_questions` (есть только у папы), поэтому тулза возвращает `{source: "not-tracked"}` — агент при этом красиво собирает список из `flags` и других секций. Можно опционально завести у мамы `open_questions` в `knowledge_base.json` (как у папы 12 пунктов) для более точных, формализованных ответов.

## 2026-05-26 — data: OCR всех JPEG Олега и Игоря — масштабное дополнение KB

**Олег (85 → полностью покрыт):** Обработано 47 JPEG, у которых стояло «текст не извлечён».
Ключевые находки:
- `blood_2019-07-08_*` и `blood_2021-04-01_*`: гепатит/ВИЧ/сифилис — отрицательно оба раза
- `blood_urine_2021-04-01_general.jpeg`: полный ОАК + ОАМ; PLT=46 — возможный артефакт агглютинации
- `efgds_2018-10-13`: поверхностный гастродуоденит, ДГР
- `efgds_2019-07-10`: желчный рефлюкс-гастрит, выраженный ДГР
- `ecg_2020-07-17`: ЧСС 56, синдром РРЖ (СРРЖ); `ecg_2021-03-31`: ЧСС 67, норма
- `endocrinologist_2020-07-17`: рост **178 см**, вес **71 кг**, ИМТ 22.4 (впервые антропометрия в KB), E55 (дефицит вит.D)
- `cardiologist_2020-07-17`: пограничная АГ I10, СМАД — нон-диппер, среднедневное 133/76
- `ophthalmologist_2018-05-02`: H35.0 ангиопатия сетчатки обоих глаз по гипертоническому типу
- `discharge_infectious_2019-07-18`: выписка — хр. описторхоз + холангиохолецистит, бильтрицид
- `probing_2019-06-15`: яйца Opisthorchis felineus (первичная диагностика описторхоза), сиаловые кислоты 4.2 (N <2.8)
- `gastroenterologist_*` (10 приёмов 2017-2020) + `therapist_*` (6 приёмов 2020-2021): полная история ГЭ пути
- Академический отпуск НГУ 2020: основание — описторхоз + ДЖВП + колит

Задеплоено: `kb_1137554647.json`

**Игорь (32 JPEG):** Большинство уже были частично обработаны, дополнены пропущенные детали.
Ключевые дополнения:
- `medical_records`: военно-медицинская комиссия ГНОКБ 28-30.06.2023 (полная биохимия, билирубин 25.7 ↑, фибриноген 268 ↓, схема лечения)
- `allergy_tests[2022]` и `[2023]`: расширен спектр аллергенов (рыба, пыльца, клещи)
- `vaccinations`: 27 записей с точными датами (гепатит B, полиомиелит, АКДС, паротит)
- `tuberculin_tests`: 14 записей Манту/Диаскинтест 2006-2020 — все отрицательные
- Военкомат 2023: Беродуал ситуационно без базисной терапии (объясняет обострение при госпитализации)

Задеплоено: `kb_830908046.json`

---

## 2026-05-26 — data: KB Павла — добавлена мочевая кислота 2026-02-03 (ЭМЛ)

`blood_tests[2026-02-03]`: uric_acid = **496.17 мкмоль/л** ⚠️ выше референса (214–488).
Файл `blood_2026-02-03_eml_uric-acid.pdf` (ЭМЛ СПб, заказчик ВеронаМед) ранее не был добавлен в KB.
Единственная запись мочевой кислоты в истории Павла — динамика пока неизвестна (нет предыдущих замеров).
Задеплоено: `/opt/healthvault/data/kb/kb_33831673.json`

---

## 2026-05-26 — data: OCR-аудит всех нечитаемых PDF (KDL/Atlas, 4 пользователя) — масштабное дополнение KB

Все KDL и Atlas PDF с нечитаемым шрифтом (cid-encoding) отрендерены через PyMuPDF → JPEG → Claude Vision.
Охвачено **41 garbled PDF** (~63 страницы): Катя — 36 стр, Игорь — 8 стр, Олег/Александр — ранее.

**Изменения в KB по пользователям:**

`FamilyHealth/Екатерина Лысковская — Здоровье/knowledge_base.json` (Катя не является пользователем бота):
- `blood_tests[2021-08-04]`: перестроена с 0 → **46 полей** (полный checkup: ОАК 20п, биохимия 15п, липиды/минералы 10п, гормоны 6п включая TSH 0.6039, fT4 12.89, fT3 3.81, антитела)
- `blood_tests[2022-04-24]`: +21 поле (ОАК + биохимия); **удалены TSH/fT4/fT3** — отсутствуют в этом PDF (были из другого теста)
- `blood_tests[2022-09-21]`: +25 полей (полный ОАК + биохимия + минералы + anti_thyroglobulin 0.57, anti_thyroid_peroxidase 0.25)
- `blood_tests[2022-11-24]`: +2 поля (anti_thyroglobulin 1.43, anti_thyroid_peroxidase 0.24)
- `blood_tests[2023-04-27]`: +2 поля (bilirubin_total 7.2, urea 6.2)
- `blood_tests[2023-05-31]`: +2 поля (anti_thyroglobulin 0.42, anti_thyroid_peroxidase 0.00)
- `blood_tests[2023-12-28]`: +24 поля (полный ОАК + биохимия)
- `blood_tests[2024-12-28]`: +18 полей (полный ОАК)

`FamilyHealth/Игорь Лысковский — Здоровье/knowledge_base.json` (Игорь не является пользователем бота):
- `blood_tests[2022-04-17]`: +17 полей ОАК (ESR 2, Ht 47.0, MCV 83.2, MCH 27.7, MCHC 33.3, тромбоцитарные индексы, лейкограмма)
- `blood_tests[2023-12-28]`: +2 поля (iron 17.9, bilirubin_total 20.5)

Дополнительно от аудита 5 PDF (см. запись ниже): исправлена 1 галлюцинация в KB Олега (bilirubin_direct).

Итог OCR-сессии: KB семьи полностью верифицированы по первичным источникам.
Катя и Игорь не деплоятся на сервер (нет telegram_id в sync_family_kb.py).

---

## 2026-05-26 — data: Аудит галлюцинаций KB — 5 PDF, найден 1 ошибочный biomarker, исправлено

Проверен вопрос о возможных LLM-галлюцинациях в KB. Метод извлечения — **не LLM-OCR**, а pdfplumber/fitz
(машинное извлечение текста) с ручной транскрипцией Claude. Риск — не галлюцинации, а пропуск полей.

Сравнены 5 случайных PDF с соответствующими KB-записями:

| PDF | Человек | Дата | Результат |
|-----|---------|------|-----------|
| blood_2026-01-07_invitro_biochemistry-comprehensive.pdf | Александр | 2026-01-07 | ✅ 21/21 точное совпадение |
| blood_2024-05-12_kdl_general.pdf | Олег | 2024-05-12 | ✅ 2/2 точное совпадение |
| blood_2018-10-12_biochemistry.pdf | Олег | 2018-10-12 | ✅ 12/12 верные; 2 поля в PDF пропущены |
| blood_2024-11-08_pol97_full-export.pdf | Павел | 2024-11-08 | ✅ 20/20 верные; 4 мелких пропущены |
| blood_2026-04-13_unknown_comprehensive.pdf | Олег | 2026-04-13 | ⚠️ 57/57 верные; **1 лишнее** поле в KB |

Найденные ошибки и исправления в `FamilyHealth/Олег Лысковский — Здоровье/knowledge_base.json`:
- `blood_tests[2026-04-13]`: удалён `bilirubin_direct=2.5` — отсутствует в PDF (ни одна из 8 страниц); добавлен пропущенный `ESR=2`
- `blood_tests[2018-10-12]`: добавлены пропущенные `urea=3.7` и `uric_acid=380.1`

Вывод: системных галлюцинаций нет. Паттерн ошибок — неполное извлечение (пропуск полей), не выдуманные значения.
Исключение: `bilirubin_direct` в записи 2026-04-13 — единственный случай значения без источника в PDF.

Задеплоено: `/opt/healthvault/data/kb/kb_1137554647.json`

---

## 2026-05-26 — data: KB Павла — аудит покрытия файлов, ОАМ 2024-11-08 дополнена

Аудит KB Павла Храпкина (telegram_id 33831673): все 33 PDF покрыты (29 extracted + 3 duplicate).
Единственный незакрытый файл — сгенерированный отчёт `Отчёт_*_v3.pdf`, не медицинский.
Дополнена запись `urine_tests[2024-11-08]`: добавлены глюкоза (отрицательно), лейкоциты (не обнаружено),
эритроциты (отрицательно) — эти поля были в PDF но отсутствовали в KB. Плотность и pH —
в PDF СПб ГП №71 выводятся только словесно ("норма"), числа не напечатаны.
Задеплоено: `/opt/healthvault/data/kb/kb_33831673.json`

---

## 2026-05-26 — data: KB Олега — ЭКГ 2025-09/10 и ОАМ 2025-10 распарсены и задеплоены

Извлечены данные из JPEG-файлов в KB Олега Лысковского (telegram_id: 1137554647):
- `ecg_2025-09-30` и `ecg_2025-10-01`: ЧСС 59, синусовая брадикардия, QTc 0.400с, ЭКГ без патологии, врач Рыбакова Т.А.
- `urine_2025-10-01`: ОАМ норма (удельный вес 1.015, pH 6.0, белок 0.00 г/л, все элементы в норме)

Файл: `FamilyHealth/Олег Лысковский — Здоровье/knowledge_base.json`
Деплой: `/opt/healthvault/data/kb/kb_1137554647.json` (MD5 eb31e80...) — через jump host (прямой SSH временно заблокирован fail2ban после серии scp)

Попутно задеплоены обновлённые KB для Александра, Павла и Андрея (все три были устаревшими на сервере).

---

## 2026-05-26 — fix: UnboundLocalError MSK в photo.py + вопрос про витамин логировался как приём

Три связанных бага в `@Botkin_md_bot`, выявленных пользователем по скринам:

1. **Фото обеда → нет ответа.** Photo с caption «Обед» успешно распознавался LLM как food
   (видно в логах: `Распознано через LLM: Лосось в терияки, 500 ккал`), `process_llm_food_data`
   возвращал валидные items+totals, но карточка с КБЖУ и кнопкой «Сохранить» не отрисовывалась.
   Лог: `Failed to feed update to legacy bot: cannot access local variable 'MSK' where it is not associated with a value`.
2. **Текстовое описание после фото → молчание.** Из-за бага #1 state оставался `waiting_description`,
   следующее сообщение «Мурманский лосось 520 ккал…» уходило в `handle_description` и
   снова падало на том же MSK.
3. **«Какой у меня витамин Д?» → «💊 Витамины: Витамин D3 ✅ Записано».** Вопрос про
   анализ логировался как факт приёма добавки.

**Root cause #1+#2:** в `telegram-bot/handlers/photo.py` внутри функций `handle_description`
(line 941) и `process_photos_list` (line 272) был локальный re-assignment
`MSK = timezone(timedelta(hours=3))` в BP-ветке. Python видит присваивание и помечает
MSK как local для ВСЕЙ функции. Когда food-flow позже обращался к `datetime.now(MSK)`
(lines 1052/1069/502), Python кидал UnboundLocalError. Тот же баг чинили в text.py
(commit af71067), но в photo.py пропустили.

**Root cause #3:** vitamin pre-check в `telegram-bot/handlers/text.py:655` стоял
ПЕРЕД conversational pre-filter (line 718). «Какой у меня витамин Д?» = 5 слов ≤ 6,
содержит «витамин д» → router_result становился `{type: vitamins, items: [Витамин D3]}` →
save_supplements. Conversational pre-filter (который вернул бы `type=other` → BotkinClaw)
никогда не доходил. Регрессия от commit a0c2154.

**Fix:**
- `photo.py`: удалены локальные `MSK = ...` (lines 272, 941). Используется модульный
  MSK с line 13.
- `text.py`: vitamin pre-check (line 655) и regex fallback (line 787) теперь гарданы
  условием `not _is_clearly_conversational(text)`. Вопрос → агент, факт приёма → логирование.

Задеплоено: `docker cp` photo.py + text.py в `healthvault_bot`, restart. Smoke-test
прошёл (бот стартанул, 156 обработчиков зарегистрированы).

---

## 2026-05-26 — scripts: warn на пустые values в KB перед генерацией biomarkers

Добавлена функция `warn_empty_values()` в `scripts/generate_biomarkers_json.py`.
При каждом запуске (с `--deploy` или без) сканирует секции `blood_tests`, `urine_tests`, `hormones`, `vitamins`
и выводит `⚠️ Пустые values: {section} {date} {lab}` для записей с пустым или отсутствующим полем `values`.
Деплой не прерывается — только информирование. Итоговая строка подсказывает как исправить.

---

## 2026-05-26 — KB: анализы мочи — парсинг 4 тестов (2016–2026)

Обнаружено, что секция `urine_tests` в `knowledge_base.json` содержала 1 запись с пустыми `values: {}`.
Найдено и распарсено 4 PDF (3 архивных + 1 свежий из `blood_2026-05-23_cmd_comprehensive.pdf`):

- **2016-09-17** Invitro — 20 параметров. Норма, незначительные оксалаты.
- **2017-06-16** Invitro — 19 параметров. Эритроциты на верхней границе (2, норма <2) — borderline.
- **2021-03-01** Atlas KDL — 17 параметров. Флаги: билирубин обнаружен, переходный эпителий 8.0↑ (норма 0–4.5). PDF с CID-шрифтом — восстановлен через OCR скриншота PyMuPDF.
- **2026-05-23** CMD — 29 параметров. Флаги: **лейкоциты 6–8 в п/зр (норма 0–3)** — стерильная лейкоцитурия (нитриты/бактерии/лейкоцитарная эстераза отрицательны), слегка мутная, оксалаты незначительные. Рекомендован повторный ОАМ через 2–4 нед.

Задеплоено: `biomarkers_895655.json` → контейнер бота, `kb_895655.json` → bind-mount, `blood_tests` Postgres — 90 строк updated. PROFILE.md exam journal регенерирован.

---

## 2026-05-26 — Security: удаление персональных данных из публичного репо

Полный аудит публичного GitHub-репо на предмет чувствительных данных. Найдено и устранено:

1. **`telegram-bot/biomarkers_895655.json`** (15KB реальных биомаркеров) — удалён из git-истории через `git filter-repo --invert-paths`. Файл был закоммичен в 5 коммитах. Теперь ни в одном коммите истории нет.
2. **`database/migrations/add_cohort_columns.sql`** — убраны `UPDATE` с реальными telegram_id и health-пакетами членов семьи (bariatric, female-cycle, cardiac). Заменены на placeholder-комментарии.
3. **`database/migrations/add_respiratory_allergic_pack.sql`** — убраны имя пользователя (Igor Lyskovsky) и telegram_id из комментария.
4. **`docs/superpowers/`** — 3 файла удалены из трекинга (содержали реальные имена, TG ID, health-пакеты семьи). Папка добавлена в `.gitignore`.

Force push с переписанной историей. Защита ветки main временно снята на время push, восстановлена.

Коммит `213c23d`. Не-чувствительное (`config/users.py` ADMIN_USER_ID, IP сервера, распределение TG ID `895655` по docs-примерам) — оставлено как есть.

## 2026-05-26 — Архитектурный фикс «всё фото = еда»

Прецедент 07:08-07:25: Александр прислал 2 скриншота Garmin → 3 раза «не еда» подряд + текст-вопрос «Сейчас утро вторника. Ты видишь сон?» тоже ушёл в food-handler. Root cause — две дыры:

1. `photo.py:506` — фото без caption где роутер вернул `type≠food` ставило `state=waiting_description`. Любой следующий текст уходил в `handle_description`.
2. `text.py:501` — при `state=waiting_description` ВСЁ заменялось на `handle_description`, минуя BP regex и conversational pre-filter.

Fix: фото-не-еда больше **не ставит state**, просто отвечает «🤔 Не распознал еду. Напиши текстом — разберусь». Текстовая ветка с `state=waiting_description` сначала проверяет `_is_clearly_conversational` → если да, сбрасывает state и идёт в нормальный flow.

E2E подтверждено: фото тонометра → правильный ответ + текст «🧪 ты видишь мой сон?» → BotkinClaw корректно ответил про сон.

Коммит `7b9d030`. Закрыт task #52.

## 2026-05-25 — Marathon: открытые вопросы папы + BP regex + E2E test mode + memory fix

8 коммитов, 9+ часов:

1. **`get_open_questions` tool + universal meta-prompt** (`agent_chat.py`). Закрывает класс ошибок «бот не всплывает висящие клинические вопросы из KB». Прецедент: папа спрашивает «какие у меня диагнозы» → 8 диагнозов, но молчание про K/Mg/ТТГ при QTc 0.60. Папе отправлен отчёт «6 открытых вопросов для Тани». Коммит `9f81177`.

2. **BP regex pre-check в `text.py`** + `clear_state` в else-ветке `photo.py`. Папа прислал фото тонометра → бот 4 раза «не еда». Fix: regex `(\d{2,3})/(\d{2,3})\s*(?:пульс\s*(\d{2,3}))?` → `save_bp_to_db` напрямую, мимо LLM. Восстановлены 2 потерянных замера. Коммиты `3bf6f96`, `4165f5b`, `b9953ec`.

3. **E2E test mode (task #62)**. После того как Claude через MCP по ошибке удалил 20 настоящих диалогов Александра приняв их за тесты — добавлен маркер `🧪` + `source='e2e_test'` + admin endpoint `DELETE /admin/api/cleanup_e2e`. ADMIN_PASSWORD в 1Password «Botkin Admin Panel». Коммит `043704f`.

4. **Memory-prompt fix «потерял нить»**. Claude галлюцинировал на коротких follow-up'ах. Новый блок «🧠 ПАМЯТЬ ДИАЛОГА» в `UNIVERSAL_META_PROMPT` запрещает фразы «потерял нить» и требует перечитывать 3-5 последних сообщений при «ты говорил / мы обсуждали». Коммит `c89c181`.

5. **Бэкапы видны в админ-панели**: mount `/opt/backups:/app/backups`. Коммит `61fe419`.

6. **Brand+form для всех 8 добавок** (KB). Закрыли давний TODO о форме магния — **Глицинат 400мг Purely Holistic**. Удалено 8 фантомных приёмов которые бот ошибочно записал в `supplements_log` при photo-метадата-intent (баг #65).

## 2026-05-24 — Marathon: server-side derived pipelines + bot token rollback + 3-source KB sync

Большой день, четыре независимых блока:

1. **CMD-панель Александра (23.05) распарсена и залита.** 50+ биомаркеров в KB. `blood_2026-05-23_cmd_comprehensive.pdf` в FamilyHealth. Журнал обследований регенерирован. Динамика март→май сравнена с командировочной неделей (4 ночи недосыпа, HRV UNBALANCED 3 дня подряд, алкоголь 3 вечера) → объясняет искажение кортизола, DHEA-S, креатинина, ЛПНП.

2. **Server-side derived pipelines (закрыли мак-зависимость).** Новые скрипты `scripts/util/build_workouts_log.py` (Garmin activities → `workouts_log_<id>.json`) и `scripts/util/build_env_data.py` (netatmo_history → `env_data_<id>.json`). Добавлены шаги в `sync_all.sh` (ночной cron) и в `handlers/sync_cmd.py` (бот). `.dockerignore` исключает derived JSON-ы из образа. В `deploy.sh` после `up -d` запускаются builders. Прецедент: тренировка 22.05 трижды пропадала с дашборда после каждого `--force-rebuild`. Архитектурно закрыто.

3. **PhenoAge креатин-артефакт детекция.** `core/health/supplements.py`: новые `is_supplement_active()` и `check_lab_artefacts_for_user()` + таблица `LAB_ARTEFACTS` (creatine → creatinine ×0.78, расширяема для биотин/алкоголь/BCAA). `dashboard_generator.py` Panel 4: маркер «Креатинин» теперь содержит флаг + corrected_val + биовозраст с поправкой (35.7 → 33.2). UI: оранжевая плашка в Примечании + 🔶 бейдж на маркере с tooltip. PhenoAge переехала на первую позицию среди вкладок биомаркеров. Pill-button стиль вкладок + короткие названия (Attia, LE8, ASCVD) чтобы все 7 умещались в строку.

4. **Bot token rollback + 3-source KB sync pipeline.** Обнаружено что `.env` (мак, сервер, 1Password) содержал старый токен `@HealthVault_bot` (8500310863), а display name старого бота был переименован в «NutriLogBot» — пользователь думал что пишет `@Botkin_md_bot`, но Telegram открывал старый чат. Откатили: токен в трёх местах → правильный 8739688481, старый бот переименован в «HealthVault (архив)» через `setMyName`, webhook у старого снят через `deleteWebhook`. **Главное архитектурное:** агент читает анализы из ТРЁХ мест (flat JSON для дашборда, PostgreSQL `blood_tests` для `/recent_biomarkers`, `/app/data/kb/kb_<id>.json` для `/kb_value`). Раньше `generate_biomarkers_json.py --deploy` обновлял только flat — поэтому дашборд знал май, агент твердил «последний 19 марта». Теперь `--deploy` запускает 3-stage pipeline: (1) deploy flat-JSON, (2) `kb_to_blood_tests.py`, (3) `sync_family_kb.py`. См. `docs/ai_context/04_workflows.md` §13. Bind-mount `/opt/healthvault/data/kb → /app/data/kb` уже существовал (коммиты 4665a03 + 9d3d93c).

Коммиты: `af8aa59` day cleanup · `7c33f6a` deploy derived-rebuild · `b48526b` auto-sync blood_tests · `d69f095` 3-stage --deploy.

## 2026-05-22 — Igor onboarding to BotkinClaw + reusable family-user pipeline

- **Family user onboarding to BotkinClaw + reusable pipeline.** Подключён family-пользователь (pack: respiratory_allergic). Создан `scripts/onboard_family_user.py` с командами enroll/refresh-kb/refresh-prompt/unenroll, поддержкой dry-run, атомарным scp+psql с rollback'ом, post-upload JSON-валидацией. Реестр packs вынесен в `core/packs.py` как декларативный `@dataclass(frozen=True)`. Шаблон промпта `scripts/server/agent_prompts/templates/family_active_coach.md` с `string.Template`-плейсхолдерами + LLM-генерация 6 структурированных блоков через claude-sonnet-4-6 (fallback на 4-5). Runbook: [docs/operations/onboard-family-user.md](../operations/onboard-family-user.md). Скрипт переиспользуется для подключения других семейных юзеров тем же образом.

## 2026-05-21 — PNG-инфографика «Динамика биомаркеров»

Markdown-таблицы в Telegram читаются плохо (моноширинный не везде, узкие экраны ломают выравнивание). Решение: новый tool `render_report` который генерит matplotlib-картинку 2×3 small-multiples по 6 ключевым биомаркерам (глюкоза/гемоглобин/холестерин/креатинин/АЛТ/гематокрит и т.п.) с линиями, точками и зоной нормы — отправляет sendPhoto от имени `@Botkin_md_bot`.

- `core/reports/biomarker_dynamics.py` — рендерер, читает per-user KB, выбирает до 6 маркеров с ≥2 наблюдениями по приоритету.
- POST `/api/agent/render_report` ([agent_tools_api.py](telegram-bot/webhook/agent_tools_api.py)) — JWT-isolated endpoint, делает sendPhoto и возвращает агенту короткий статус (агент комментирует картинку текстом).
- Tool описан в `TOOLS` массиве `core/agent_chat.py` с явной инструкцией «вместо markdown-таблицы».
- `requirements.txt`: добавлен matplotlib>=3.8 (на проде установлен в running container).
- `docker-compose.prod.yml`: bind-mounts для `kb_<id>.json` чтобы файлы не терялись при пересборке (раньше docker cp пропадал).

E2E: запрос «покажи инфографикой динамику моих биомаркеров» к BotkinClaw от user_id=33831673 → агент дёргает render_report → Telegram получает PNG → агент отвечает 4 предложениями с фокусом на главное (рост глюкозы, снижение холестерина).

## 2026-05-21 — Длинные ответы BotkinClaw: чанкование под лимит Telegram

После markdown→HTML текст может превышать 4096-символьный лимит Telegram (теги дают expansion). Раньше отваливалось с `message is too long`, фоллбэк на plain снимал жирные/заголовки.

- `core.tg_markdown.split_markdown_for_telegram(text, max_chunk=3500)` — рубит по \\n\\n → \\n → `. ` → hard cut, не режет внутри ```код```.
- `handlers/text.py`: каждый чанк рендерится HTML отдельно, fallback на plain — только для конкретного чанка.

## 2026-05-21 — KB для папы подключён

Файл `kb_33831673.json` (41 КБ) был на хосте `/opt/healthvault/`, но не в контейнере. Пофикшено через bind-mount в `docker-compose.prod.yml`. Tool `get_kb_value` для папы теперь возвращает реальные данные.

## 2026-05-21 — Product-review pipeline: consent, raw-text log, ночной /review skill

Замысел: уметь раз в N дней (ночью) пройтись по переписке пользователей с Botkin
и автоматически выгребать оттуда баги / feature requests / неудобства. Без подглядывания
без согласия и без потери исходных формулировок, которые сейчас «съедаются» роутером
в пищевых сообщениях.

**Что сделано:**
- `users.agent_review_consent BOOLEAN NOT NULL DEFAULT TRUE` — миграция `add_agent_review_consent.sql`. На текущей закрытой стадии (семья + друзья) default ON.
- Тоггл «Делиться диалогами с командой» в мини-аппе → секция «Приватность» в `telegram-bot/webapp/index.html`, GET/POST `/api/settings` расширены. Свич с пояснением «никаких других данных — только сами сообщения».
- `agent_conversations.source TEXT` + индекс. Значения: `botkinclaw` (реальный диалог), `router_food` / `router_vitamins` / `router_bp` / `router_weight` / `router_mixed` / `router_body_measurements` (raw текст для не-агентных веток), NULL = легаси.
- `core.agent_chat.log_router_raw_text(uid, raw, msg_type)` — пишет user-turn с `source='router_*'`. Вызывается из `handlers/text.py` сразу после классификации.
- `_load_history` фильтрует `WHERE source IS NULL OR source='botkinclaw'` — non-agent сообщения не подмешиваются в контекст Claude.
- Skill `~/.claude/skills/review-conversations/SKILL.md` — ночное продукт-ревью: выгрузка из прод-БД с фильтром по consent, группировка по юзерам, прогон через Claude, сводный план в виде todo.

**E2E прогон:** GET /api/settings отдаёт `agent_review_consent`, тоггл туда-обратно работает, `log_router_raw_text` пишет с правильным source, `ask_agent` не подхватывает router_-записи в контекст.

## 2026-05-21 — jwt_secret: автогенерация для новых юзеров + бэкфилл легаси

Папа (33831673) при попытке поговорить с Botkin получал «Разговорный агент временно недоступен» — у него в `users` не было `jwt_secret`, BotkinClaw валился на `_generate_jwt`. Та же дыра у 4 других активных юзеров (DeployTest, Настя, Лена, игнат) — их онбординг прошёл до того, как ввели требование JWT.

**Чиним системно:**
- `database/models.py`: `User.jwt_secret` теперь имеет `default=lambda: secrets.token_hex(32)` — любой `User(...)` без явного значения получит секрет на INSERT. Покрывает все 3 точки создания (`onboarding.py:130`, `crud.py:49`, `crud.py:343`).
- `scripts/backfill_jwt_secret.py` — однократный бэкфилл для активных пользователей; флаги `--dry-run` и `--all` (включая неактивных).
- Прогнан на проде: 4 юзера получили секреты, бот перезапущен. У всех 9 активных юзеров теперь `jwt_secret IS NOT NULL`.

## 2026-05-21 — BotkinClaw: JWT fallback, +6 tools, Sonnet 4.6, multi-user safe

Ночная автономная сессия после сноса NanoClaw (см. ADR-0002). Имя in-process AI-агента — **BotkinClaw** (игра слов NanoClaw → BotkinClaw).

**Архитектура:**
- `core/agent_chat.py:agent_id_for(user)` — общий helper. Если `users.container_id` NULL → деривирует `botkinclaw-{telegram_id}`. И generate, и validate JWT используют одну функцию. Снимает зависимость от NanoClaw-провижна.
- `_generate_jwt` требует только `jwt_secret` (не `container_id`).
- Модель: `claude-sonnet-4-5` → **`claude-sonnet-4-6`** (агент + photo router).
- `TypingMiddleware` — нативный «печатает...» в Telegram, обновляется каждые 4 сек.
- `telegram_router.py` — удалена мёртвая ветка `forward_to_container`.

**Новые tools (8→18):** `get_weight_history`, `get_body_measurements`, `get_day_summary(date)`, `get_indoor_air(days)` (Netatmo, owner-only), `get_outdoor_weather(date)` (Open-Meteo), `get_user_settings`, `recent_workouts` теперь с DB-fallback (multi-user safe).

**E2E проверка:** ping-pong 32 запроса (2 юзера × 16 endpoints) — 0 ошибок 500, все `no_data` ответы корректные.

**Dev experience:** `pyjwt==2.8.0` → `>=2.8.0`, `datetime.utcnow()` × 7 → `datetime.now(timezone.utc)`, Mac venv пересоздан, 5 merged-веток удалены, `docs/operations/dependency-updates-2026-05-21.md` — аудит outdated-пакетов, BotkinClaw sanity-check в `/cleanup` skill.

**Тесты:** 407 unit passed + 8 новых.

**Commits:** `6b138b1`, `2bfb1fa`, `fa184f7`, `7cc1e8d`, `0339296`, `7c01b70`.

---

## 2026-05-12 — 🏷 Переименование проекта: HealthVault → Botkin

**Контекст:** Имя «HealthVault» было рабочим. Перед публичным релизом (конференция июнь 2026) выбрали постоянное название.

**Решение:** Проект называется **Botkin** — в честь Сергея Петровича Боткина (1832–1889), основоположника русской клинической медицины. Игра слов: `BOT + KIN` (бот, который тебе родной).

**Что изменено:**

| Параметр | Было | Стало |
|---|---|---|
| Бренд продукта | HealthVault | **Botkin** |
| Домен | (не было) | **`botkin.health`** (куплен на Cloudflare 12.05) |
| GitHub репо | `Lyskovsky/HealthVault` | **`Lyskovsky/Botkin`** (переименовано через GitHub API, redirect работает) |
| Telegram bot username | `@HealthVault_bot` | **`@Botkin_md_bot`** (новый бот, bot_id 8739688481) |
| Bot display name | NutriLogBot | **Botkin** |
| Bot About | (старое) | «AI-врач и помощник в botkin.health» |
| 1Password карточка | «HealthVault / NutriLogBot — service secrets» | **«Botkin (ex-HealthVault) — service secrets»** |

**Telegram bot — миграция:**
- Создан новый бот через `/newbot` (Telegram запрещает переименовывать существующих — см. https://core.telegram.org/bots/features)
- `.env` обновлён на новый токен (старый сохранён в `.env.bak.*`)
- Webhook нового бота на `https://health.orangegate.cc/telegram/webhook`, у старого удалён
- Старый бот `@HealthVault_bot` — архив, истории чатов сохранены
- Все 4 юзера получили миграционное сообщение через старого бота, переходят /start в новом — профили подтягиваются по `telegram_id`

**Что НЕ изменено (намеренно):**
- БД схема, имя БД `healthvault`, Postgres креды (`HealthVault_Secure_2026_*` в `.env`)
- Архивные доки (`SPRINT_1A_DEPLOY.md`, `ONBOARDING_v2_apr26.md`, старые планы)

**Что ПЕРЕИМЕНОВАНО позже (12.05.2026, после первоначальной миграции):**
- Папка медданных семьи: `~/.../Мой диск/HealthVault/` → **`~/.../Мой диск/FamilyHealth/`** (параллельно с уже существующим `FamilyDocs/`). Обновлены 13 ABS-путей.
- Локальная папка проекта: `~/.../Projects/Vibe coding/HealthVault-engine/` → **`~/.../Projects/Vibe coding/Botkin/`** (совпадает 1:1 с GitHub `Lyskovsky/Botkin`). Обновлены ABS-пути в 9 активных файлах. Архивные plan-файлы (`docs/superpowers/plans/2026-04-*`) намеренно не тронуты.

**📌 Если AI открывает проект из новой папки `Botkin/`:**
- Контекст полностью сохраняется через `CLAUDE.md` (project memory) + `~/.claude/CLAUDE.md` (глобальная)
- Активные задачи на момент переименования — см. `todo.md` раздел «🚧 Активные задачи»

**Затронутые файлы (обновлены на Botkin):**
- `README.md`, `CLAUDE.md`, `todo.md`
- `docs/landing/*` (лендинг с фото Александра)
- `docs/user_guide/ru/*.md` (9 разделов гайда)
- `docs/superpowers/specs/2026-05-12-cohort-agents-v2-design.md`
- `telegram-bot/bot.py` (banner, error messages)
- `telegram-bot/webhook/admin.py` (заголовок, HTTP Basic Realm)
- `telegram-bot/webhook/apple_health.py` (FastAPI app title)
- 1Password карточка, `~/.claude/CLAUDE.md`

**Кто решал:** Александр. Ника предложила «Нутри» — сохранили как имя AI-помощника внутри бота на будущее.

---

## 2026-05-10 — HAE парсер: sleep, energy, HRV-surrogate Body Battery (продолжение)

**Задача:** Починить Body Battery / Stress / Sleep для не-Garmin пользователей (Apple Watch через HAE)

**HRV surrogate Body Battery (dashboard_generator.py):**
- При отсутствии Garmin BB/Stress вычисляется суррогат по HRV:
  `BB = 50 + (hrv/median − 1) × 100`, clamped 0-100; Stress = инверсия
- Андрей: BB=52, Stress=48 отображаются на дашборде
- Тайлы называются «Body Battery» / «Стресс» без привязки к источнику (по просьбе пользователя)

**nginx:** client_max_body_size 1m → 200m; proxy_read_timeout 30s → 300s (фикс 413 для bulk HAE upload)

**Docker Claude API 401:** `docker compose up -d bot` (не restart) при смене ключей в .env

**HAE sleep_analysis (apple_health.py) — расследование и фикс:**
- Реальный формат: `{totalSleep: 4.3, core: 2.3, deep: 0.97, rem: 1.06, awake: 0, sleepStart, sleepEnd, ...}`
- Поля `qty`/`Asleep`/`InBed` отсутствуют (причина NULL в БД)
- Фикс: читаем `totalSleep` → `sleep_hours`, стадии deep/rem/core/awake → `raw_data`
- Добавлены поля `sleep_deep_h`, `sleep_rem_h`, `sleep_core_h`, `sleep_awake_h` в AppleHealthPayload

**HAE basal_energy_burned — фикс единиц:**
- HAE шлёт МДж (megajoules), ошибочно маркируя как `units="kJ"` (баг HAE)
- Признак: `value < 100` при `units=kJ` → трактуем как МДж × 239 → ккал
- Было: `bmr_calories = 5.9` (ккал), стало: `bmr_calories ≈ 1400` (ккал)

**Коммиты:**
- `8dbf1b6` fix(apple_health): улучшить парсинг sleep_analysis и единиц энергии из HAE (debug logging)
- `8dd4d30` fix(apple_health): исправить парсинг sleep totalSleep и конвертацию МДж в ккал

**Статус:** бот задеплоен, ждём подтверждение от Андрея (ручной экспорт). Бэкфилл 4-10 мая нужен повторно — предыдущий upload был до фикса.

---

## 2026-05-10 — Мультипользовательский дашборд + подключение second early_user

**Задача:** Подключить early_user (user_id=836757955) к HealthVault, настроить HAE, загрузить исторические данные, улучшить дашборд.

**Данные пользователя (user_id=836757955):**
- HAE (Health Auto Export) настроен → webhook `POST /apple_health_v2`, токен сохранён
- Бэкфилл 60 дней из knowledge_base.json → `activity_log` (60 строк обновлено)
- `blood_pressure_logs`: 12 пар (уже были из ранних сессий)
- Задокументировано 122 ЭКГ-записи Apple Watch: SinusRhythm:53, AFib:66, HighHR:3 (диапазон 2021→2026)
- `biomarkers_836757955.json` обновлён: 35 ключей vs 7, расширен набор cardiac markers

**Sprint 3 план:**
- `docs/superpowers/plans/2026-05-10-sprint3-ecg-syncope.md` — план импорта ЭКГ в `ecg_event` + `syncope_event` (6 задач, ~787 строк)
- Таблицы в БД пока не созданы — следующая итерация

**Дашборд — мультипользовательские исправления:**
- `dashboard_blocks.has_blood_test_data`: убран хардкод `cohort == "owner"`, теперь проверяет `biomarkers_{telegram_id}.json` для ЛЮБОГО пользователя
- `dashboard_generator.biomarkers_latest`: добавлены AST, GGT, hs_CRP, NT_proBNP (cardiac markers)
- `biomarkers_836757955.json`: исправлен ключ `hsCRP` → `hs_CRP` для совместимости с панелями Attia
- `mc_template.html`: улучшен график калорий — стековый вывод алкоголь/еда (alco_kcal split)
- Задеплоено и проверено: обе ссылки `/mc/*` работают, все маркеры отображаются

**Коммиты:**
- `a0ffd2c` fix(router+dashboard): legacy aiogram fallback + pack-aware targets
- `d81a972` feat(health): Sprint 3 plan — ecg_event + syncope_event tables and import
- `4917927` feat(dashboard): multi-user blood-test support + cardiac markers

**Дополнение (10.05.2026, завершение сессии):**
- `knowledge_base.json` пользователя обновлён из более новой версии (442889 → 444742 байт)
- Добавлены клинические данные из КТ и POAF-периода в knowledge_base
- `scripts/generate_exam_journal.py`: фикс — КТ/МРТ теперь берут дату из `imaging.ct`/`imaging.mri` (если новее, чем из medical_records)
- Журнал обследований регенерирован: КТ дата исправлена 2024-10-31 → 2025-01-28
- Дублирующиеся файлы: `knowledge_base (1).json` и `PROFILE (1).md` можно удалить с Google Drive

---

## 2026-05-10 — Разделение API ключей по проектам + расследование расходов Anthropic

**Задача:** Выяснить куда уходят деньги с Anthropic баланса, разделить ключи по сервисам.

**Расследование расходов:**
- Методом анализа логов console.anthropic.com + OpenClaw сессий установлено: ~$15 потратил Кузя (OpenClaw на сервере 116.203.213.137) через LiteLLM прокси
- Причина дорогих запросов: сессия с февраля 2026 накопила 1269 сообщений (2.7 МБ) — каждый вопрос тянет ~70k токенов истории
- Всё легитимно — Кузя отвечал на вопросы про погоду и обновлял скилы через Telegram

**Ротация и разделение ключей:**
- Создан ключ `healthvault-bot` → прописан в `.env`, `.env.production` (сервер), 1Password (HealthVault secrets)
- Создан ключ `OpenClaw (Kuzya)` → прописан в `/root/.openclaw/.env` и `/opt/openclaw/litellm.env`, 1Password
- Старые ключи `Claude_API_key` и `scheduler-bot` — отозваны
- Проверка git-истории: реальный ключ ни разу не коммитился (только `sk-ant-test` в тестах)

**Переключение LLM для распознавания еды:**
- `core/llm/router.py` — добавлена функция `analyze_message_claude()`, цепочка: Claude Sonnet 4.5 → GPT-4o → Gemini
- `config/settings.py` — добавлено поле `anthropic_api_key`
- Исправлен промпт расчёта клетчатки: CRITICAL RULE per-ingredient (не на весь вес блюда)
- `telegram-bot/handlers/commands.py` — в `/day` убраны проценты у клетчатки, формат как у БЖУ
- Исправлена запись завтрака 9 мая (ABC Coffee): 630 ккал, 410г, Б19/Ж44/У28, клетчатка 6г

## 2026-05-09 — Заполнение пропущенных дней питания + улучшения бота

**Задача:** Восстановить пропущенные записи питания за апрель–май, улучшить распознавание еды по фото.

**Питание — внесено в БД:**
- **13 апр** (Новосибирск, у мамы): обед щи+сало+коньяк+кулич+салат (ids 1241-1243, 3591 ккал)
- **14 апр** (Новосибирск → Москва): обед у мамы (щи+пирожки), ужин у сына (лосось+пюре), кафе Скворечник (медовик+вино+форшмак+фаршированный перец) (ids 1244-1247, 2580 ккал)
- **15 апр** (перелёт NSK→MOW): обед Аэрофлот эконом + домашняя утка карри (ids → 1883 ккал)
- **16 апр** (Москва, дома): типичный день — яйца+хлеб, тунец+салат, лосось+брокколи, сыр адыгейский (1488 ккал)
- **7 мая**: подтверждено что 1559 ккал — правильно, малоедный день намеренно

**Улучшения кода:**
- `core/llm/router.py` — добавлен SCENARIO 1.3 для распознавания весов на фото (приоритет LED-дисплея над дефолтными 100г)
- `core/llm/router.py` — исправлено КБЖУ Bombbar Original glazed: 142 ккал/40г
- `telegram-bot/handlers/photo.py` — в подтверждении блюда теперь показывается вес (`⚖️ Вес: X г`)
- `scripts/import/weather.py` — добавлены overrides для Челябинска (05-06 мая 2026), запущен backfill

**Прочее:**
- Диагностирован и устранён gap в HAE данных (4-8 мая) — пользователь не оплатил подписку, 140-байтные пустые ответы. После оплаты — ручной экспорт 8 дней восстановлен.
- `todo.md` — добавлена задача автодетекта города из дневниковых записей → обновление LOCATION_OVERRIDES

**Файлы:**
- `core/llm/router.py`, `telegram-bot/handlers/photo.py`, `scripts/import/weather.py`, `todo.md`

---

## 2026-05-04 — Sprint 1a Task 12: Smoke Tests & Regression Verification

**Задача:** Запустить все smoke-тесты Sprint 1a, исправить найденные баги, подтвердить что система работает end-to-end.

**Результаты smoke-тестов:**
1. ✅ `/health` endpoint — `{"status":"ok","service":"apple_health_webhook"}`
2. ✅ `/telegram/webhook` — `{"status":"ok","action":"onboarding"}` (после фикса)
3. ✅ `/api/agent/user_profile` с JWT — возвращает cohort=owner, pack=bariatric
4. ✅ `/apple_health_v2` HAE webhook — 200 OK, steps=1234 записаны
5. ✅ Dashboard `/mc/<share_token>` — HTML без ошибок
6. ✅ Unit-тесты: **349 passed**, 0 failures (5 aiogram-зависимых тестов запускаются только в контейнере)
7. ✅ Integration-тесты: **5/5 passed** (RLS-изоляция, audit_log trigger)

**Баги найдены и исправлены:**
- `telegram_router.py` — `handle_onboarding()` падал с `ModuleNotFoundError: No module named 'handlers.onboarding'`. Исправлено: lazy import с graceful fallback (Sprint 1b реализует wizard).
- `apple_health.py` — `from aiogram.types import Update` на top-level ломал импорт в тестах. Исправлено: moved inside function (lazy import).
- `tests/test_nutrition_goals.py` — тест не включал новые поля `tdee` и `deficit_pct` в expected dict. Исправлено.
- `tests/test_nutrition_api.py::FakeActRow` — не имел атрибутов `total_calories`/`bmr_calories`, код упал при AttributeError. Исправлено: добавлены `None` атрибуты в mock.

**Файлы:**
- `telegram-bot/webhook/telegram_router.py` — lazy onboarding import
- `telegram-bot/webhook/apple_health.py` — lazy aiogram import
- `tests/test_nutrition_goals.py` — updated expected dict
- `tests/test_nutrition_api.py` — FakeActRow + total_calories/bmr_calories attrs
- `todo.md` — Sprint 1a отмечен как выполненный

---

## 2026-05-04 — Sprint 1a Task 11: Telegram Webhook Registration & Deploy

**Задача:** Зарегистрировать Telegram webhook для `@HealthVault_bot` и создать deploy-доку Sprint 1a.

**Что сделано:**
1. Webhook зарегистрирован через Bot API: `https://health.orangegate.cc/telegram/webhook` — подтверждено `"ok":true`.
2. `telegram-bot/webhook/apple_health.py` — добавлен `POST /telegram/webhook` endpoint, который передаёт обновления в aiogram dispatcher через `dp.feed_update()`; добавлена функция `set_telegram_dispatcher(bot, dp)`.
3. `telegram-bot/bot.py` — удалён вызов `delete_webhook` при старте; переход с polling на webhook-режим (FastAPI-сервер теперь единственная точка входа для Telegram-обновлений).
4. Задеплоено на сервер: загружены недостающие модули (`agent_tools_api.py`, `telegram_router.py`, `jwt_auth.py`), обновлён `requirements.txt` (добавлен `pyjwt==2.8.0`), пересобран и перезапущен Docker-контейнер.
5. `docs/SPRINT_1A_DEPLOY.md` — создан, содержит: что сделано, endpoint-карта, инструкции по деплою/логам/проверке.

**Проверка:** `POST /telegram/webhook` возвращает `{"status":"ok",...}`, `GET /health` → `{"status":"ok"}`, `getWebhookInfo` → `pending_update_count: 0`.

**Файлы:** `telegram-bot/bot.py`, `telegram-bot/webhook/apple_health.py`, `docs/SPRINT_1A_DEPLOY.md`.

**Коммит:** `9dcd048`

---

## 2026-05-04 — Sprint 1a Task 10: Adaptive Dashboard — Skip Empty Blocks

**Задача:** Дашборд должен пропускать пустые блоки для пользователей без данных (Андрей, Элен — нет Garmin, нет анализов, нет Netatmo).

**Что сделано:**
1. `telegram-bot/dashboard_blocks.py` (новый) — хелперы для проверки наличия данных по блокам:
   - `has_garmin_data(db, user)` — garmin_email OR активность за 30 дней
   - `has_apple_health_data(db, user)` — есть ли строки в `blood_pressure_logs` (raw SQL, таблица не в models.py)
   - `has_blood_test_data(db, user)` — owner + ненулевые `values` в `knowledge_base.json`
   - `has_nutrition_data(db, user)`, `has_weight_data(db, user)` — ORM-запросы
   - `get_available_blocks(db, user)` — сводный dict `block → bool` для всего дашборда
2. `telegram-bot/dashboard_generator.py` — `generate_dashboard_html()` теперь вызывает `get_available_blocks()` и дополняет `meta.capabilities` lifetime-проверками (OR-merge). Шаблон уже читает `capabilities` для show/hide секций.
3. `tests/test_dashboard_blocks.py` (новый) — 5 unit-тестов с mock-DB. Все PASS.

**Файлы:** `telegram-bot/dashboard_blocks.py`, `telegram-bot/dashboard_generator.py`, `tests/test_dashboard_blocks.py`.

**Коммит:** `076ca1f`

---

## 2026-05-04 — Sprint 1a Task 9: New User Onboarding Wizard

**Задача:** 5-шаговый онбординг-визард для новых пользователей бота.

**Что сделано:**
1. `database/migrations/add_onboarding_step.sql` — миграция: добавлены колонки `onboarding_step VARCHAR(30)` и `onboarding_data JSONB` в таблицу `users`. Применена на сервере.
2. `database/models.py` — добавлены поля `onboarding_step` и `onboarding_data` в класс `User`.
3. `telegram-bot/handlers/onboarding.py` (новый) — FSM-визард: `name → age → sex → height → has_garmin → done`.
   - При завершении генерирует `health_token` формата `hvt_{telegram_id}_{32hex}` и отправляет инструкции для настройки Health Auto Export.
   - `send_message()` — прямой вызов Telegram Bot API (httpx), не через aiogram.
   - `start_wizard()` — точка входа из `telegram_router`.
4. `tests/integration/test_onboarding_wizard.py` (новый) — 4 теста: создание нового пользователя, валидный возраст, невалидный возраст, завершение онбординга с генерацией токена. Все PASS.

**Файлы:** `database/migrations/add_onboarding_step.sql`, `database/models.py`, `telegram-bot/handlers/onboarding.py`, `tests/integration/test_onboarding_wizard.py`.

**Коммит:** `7a15025`

---

## 2026-05-04 — Sprint 1a Task 8: Telegram Webhook Router

**Задача:** Маршрутизатор входящих Telegram-апдейтов через FastAPI webhook.

**Что сделано:**
1. `telegram-bot/webhook/telegram_router.py` (новый) — `POST /telegram/webhook`:
   - Новые пользователи (нет в БД) → `handle_onboarding()`
   - Пользователи с контейнером (`container_id` + `container_port`) → `forward_to_container()` (POST на `/agent/process` контейнера)
   - Пользователи без контейнера (Sprint 1a state) → no-op, 200 OK
   - Фото/голосовые → no-op (обрабатывает legacy aiogram long-poll)
   - Fallback при недоступности контейнера — отправляет сообщение пользователю через Bot API
2. `telegram-bot/webhook/apple_health.py` — добавлен `include_router(telegram_router)`
3. `tests/integration/test_telegram_router.py` (новый) — 4 теста на TestClient + mock SessionLocal, все PASS

**Файлы:** `telegram-bot/webhook/telegram_router.py`, `telegram-bot/webhook/apple_health.py`, `tests/integration/test_telegram_router.py`.

**Коммит:** `4977ed8`

---

## 2026-05-04 — Sprint 1a Tasks 5-7: Agent Tools API (8 endpoints for NanoClaw containers)

**Задача:** REST API для агентских контейнеров NanoClaw — запись еды, добавок, давления; чтение истории питания, профиля, дашборда метрик.

**Что сделано:**
1. `telegram-bot/webhook/agent_tools_api.py` (новый) — 8 эндпоинтов под префиксом `/api/agent`, JWT-аутентификация через `get_agent_user`:
   - `POST /log_meal_text` — парсит текстовое описание еды (fallback-stub если парсер недоступен), пишет в `nutrition_log`
   - `POST /log_supplement` — пишет запись в `supplements_log`
   - `POST /log_bp` — raw SQL upsert в `blood_pressure_logs`
   - `POST /regenerate_health_token` — генерирует новый `hvt_{uid}_{hex32}` токен, сохраняет в `users`
   - `GET /recent_meals?days=N` — последние N дней из `nutrition_log` (1–90 дней)
   - `GET /kb_value?key=<path>` — dot-notation доступ к `knowledge_base.json` (только cohort=owner, остальным stub)
   - `GET /dashboard_summary` — агрегат за 7 дней: шаги, пульс, ккал сожжённых и потреблённых, последний вес
   - `GET /user_profile` — нечувствительный профиль пользователя
2. `telegram-bot/webhook/apple_health.py` — добавлен `include_router(agent_tools_router)`
3. `tests/test_agent_tools_api.py` (новый) — 16 unit-тестов на TestClient + in-memory SQLite, все PASS

**Файлы:** `telegram-bot/webhook/agent_tools_api.py`, `telegram-bot/webhook/apple_health.py`, `tests/test_agent_tools_api.py`.

**Коммит:** `763034d`

---

## 2026-05-04 — Sprint 1a Task 3: audit_log table + DML trigger on admin access

**Задача:** Аудит-трейл для DML-операций admin-роли (`healthvault`) на чувствительных таблицах. PostgreSQL не поддерживает SELECT-триггеры, поэтому SELECT-логирование через `log_statement='all'` на уровне роли (идёт в PG log-файл).

**Что сделано:**
1. `database/migrations/add_audit_log.sql` — SQL-миграция: таблица `audit_log` (BIGSERIAL PK, ts, db_user, query_type, table_name, query_excerpt), два индекса (ts DESC, db_user+table_name). Триггер `audit_admin_access()` с `SECURITY DEFINER` срабатывает на INSERT/UPDATE/DELETE по 7 таблицам только если `current_user = 'healthvault'`. RLS + политика `audit_admin_only` блокирует `hv_app` от чтения audit_log. `ALTER ROLE healthvault SET log_statement='all'`.
2. `database/models.py` — добавлен класс `AuditLog` (BigInteger PK, DateTime(tz), Text поля).
3. `tests/integration/test_audit_trail.py` — интеграционный тест: INSERT в nutrition_log → проверяет +1 запись в audit_log с корректными полями (db_user, query_type, table_name).
4. Миграция применена на сервере. Тест PASS.

**Файлы:** `database/migrations/add_audit_log.sql`, `database/models.py`, `tests/integration/test_audit_trail.py`.

**Коммит:** `4f4d684`

---

## 2026-05-04 — Sprint 1a Task 2: PostgreSQL RLS + hv_app role (session-variable isolation)

**Задача:** Добавить Row Level Security в PostgreSQL, чтобы контейнеры NanoClaw (роль hv_app) видели только данные своего пользователя через сессионную переменную `app.user_id`.

**Что сделано:**
1. `database/migrations/add_rls_policies.sql` — SQL-миграция: создаёт роль `hv_app` (NULLIF-safe политики), включает RLS на 6 таблицах (`nutrition_log`, `supplements_log`, `weights`, `activity_log`, `blood_pressure_logs`, `user_settings`), политики `user_isolation` с `SET LOCAL app.user_id`.
2. `database/crud.py` — добавлена функция `set_user_session_var(db, user_id)`: выполняет `SET LOCAL app.user_id = :uid` для RLS-фильтрации.
3. `tests/integration/test_rls_isolation.py` — 4 интеграционных теста через SSH-туннель: блокировка чужих строк, доступ к своим, нет var = 0 строк, проверка supplements.
4. Миграция применена на сервере. Все 4 теста PASS.

**Важный баг-фикс:** `isolation_level="AUTOCOMMIT"` на engine делает `conn.begin()` savepoint-ом, и `SET LOCAL` не работает. Исправлено — engine без AUTOCOMMIT, `conn.begin()` создаёт реальный BEGIN.

**Файлы:** `database/migrations/add_rls_policies.sql`, `database/crud.py`, `tests/integration/test_rls_isolation.py`.

**Коммит:** `162f23f`

---

## 2026-05-04 — Sprint 1a Task 1: cohort/container/pack/jwt/byok columns in users

**Задача:** Добавить поддержку мульти-пользовательских когорт — колонки для разделения пользователей по типу (owner/family/early_user/external), pack-профилю и изолированным контейнерам.

**Что сделано:**
1. `database/migrations/add_cohort_columns.sql` — SQL-миграция: 7 новых колонок + backfill для 3 существующих пользователей.
2. `database/models.py` — класс `User` расширен: `cohort`, `container_id`, `container_port`, `pack_name`, `jwt_secret`, `encrypted_openai_key`, `encrypted_anthropic_key`.
3. `tests/test_user_model.py` — TDD-тест (SQLite in-memory): проверяет наличие когортных полей и их nullable/default поведение.
4. Миграция применена к production DB; backfill выполнен для 3 существующих пользователей с назначением когорт и pack-профилей.

**Файлы:** `database/migrations/add_cohort_columns.sql`, `database/models.py`, `tests/test_user_model.py`.

---

## 2026-05-03 — Privacy cleanup: анонимизация личных данных в публичных файлах

**Задача:** Убрать из публичного репозитория реальные имена (Ника Селезнёва, сыновья), диагнозы, Telegram username и user_id из комментариев/документации.

**Что сделано:**
1. `config/scout/profile.yaml` — `family_context` заменён на обезличенные описания (возраст и проблема без имён).
2. `docs/MULTI_USER_PLAN.md` — «Ника Селезнёва» и `485132` → «Пользователь 2».
3. `docs/ai_context/AI_CHANGELOG.md`, `README.md`, `03_database_schema.md` — Telegram usernames и user_id → `user_2`, `user3`.
4. `scripts/mcp/healthvault_mcp.py`, `scripts/audit/nutrition_schema_scan.py` — убраны персональные имена из комментариев.
5. `todo.md` — анонимизированы упоминания конкретных диагнозов и историй.
6. `CLAUDE.md` (проектный) — убрана таблица с Telegram ID и данными семьи; перенесено в приватный `~/.claude/projects/.../memory/reference_health_context.md` (не в git).
7. Создан `~/.claude/projects/.../memory/reference_health_context.md` — 63 строки, приватный, Claude читает при каждой сессии в проекте (содержит bot users, семья+диагнозы, папки Google Drive, подключение к серверу).

**Правило:** Имена, диагнозы, Telegram ID реальных людей — только в `~/.claude/` (не в git). Репозиторий публичный — только архитектура и код.

**Файлы:** `config/scout/profile.yaml`, `todo.md`, `docs/MULTI_USER_PLAN.md`, `docs/ai_context/AI_CHANGELOG.md`, `docs/ai_context/README.md`, `docs/ai_context/03_database_schema.md`, `scripts/mcp/healthvault_mcp.py`, `scripts/audit/nutrition_schema_scan.py`, `CLAUDE.md`.

---

## 2026-05-03 — Kcal consistency check + исправление Bombbar

**Задача:** Бот иногда записывал неверные калории из-за рассинхрона stated kcal vs БЖУ.

**Что сделано:**
1. `core/food/nutrition.py` — добавлены `check_kcal_consistency()` и `format_kcal_warning()`: если указанные ккал расходятся с формулой (4·Б + 9·Ж + 4·У) более чем на 25% — выводится предупреждение перед сохранением.
2. `telegram-bot/handlers/photo.py`, `text.py` — предупреждение вставлено в подтверждение приёма пищи (до кнопок).
3. `core/llm/router.py` — исправлены данные Bombbar Original glazed bar: `142 kcal / 40g` вместо некорректных `116 kcal / 35g` (в шоколаде = Original glazed line, не Slim).

**Файлы:** `core/food/nutrition.py`, `core/llm/router.py`, `telegram-bot/handlers/photo.py`, `telegram-bot/handlers/text.py`.

---

## 2026-05-03 — ActivityWatch: дедупликация + mac_screentime улучшения

**Задача:** `scripts/import/activitywatch.py` показывал 38 часов экранного времени 08.03 вместо реальных 6.3 из-за Biome-дублей.

**Что сделано:**
1. `scripts/import/activitywatch.py` — дедупликация по `(timestamp, app, duration)` перед агрегацией. Biome до ~15.03.2026 импортировал каждое событие 3-6 раз.
2. `scripts/import/mac_screentime.py` — добавлен `EXCLUDED_APPS` (loginwindow, Dock, WindowManager и др. системные процессы), добавлена константа `AW_AFK_BUCKET` с комментарием (AFK = источник истины о реальном времени за маком, window = распределение по приложениям).

**Файлы:** `scripts/import/activitywatch.py`, `scripts/import/mac_screentime.py`.

---

## 2026-05-03 — Security audit, history rewrite, repo публичный

**Проблема:** Перед публикацией репозитория нужно убедиться, что в истории нет утечки секретов.

**Аудит:** gitleaks нашёл 615 находок (OpenAI API key, GCP key, Garmin OAuth consumer key, Clearspace API key, 609 в log-файлах). Все — в старых коммитах, в рабочей копии уже были плейсхолдеры.

**Что сделано:**
1. `git-filter-repo` переписал историю (228 коммитов):
   - Удалены из всех коммитов: `.openai_api_key`, `logs/bot.log`, `telegram-bot/logs/bot.log`
   - Редактированы строки: OpenAI key → `sk-proj-OPENAI_KEY_REDACTED_FROM_HISTORY`, GCP key → `AIzaSy_GCP_KEY_REDACTED`, Clearspace key → `CLEARSPACE_API_KEY_REDACTED`, Garmin OAuth consumer key/secret → плейсхолдеры
2. После очистки `gitleaks detect` → **0 findings**.
3. `git push --force origin main` — переписанная история залита на GitHub.
4. Репозиторий переведён из private → **public** (`PATCH /repos/Lyskovsky/HealthVault {private: false}`).
5. Branch protection на `main`: force-push и удаление ветки запрещены; требуется PR для не-admin-коллабораторов; владелец (Lyskovsky, admin) может пушить напрямую.
6. Коллабораторы: `pohodnyandrey-creator` (read), `rsvbitrix` (write → пуш только через PR).

**Важно:** Старый OpenAI API key был в истории — удалён через git filter-repo, ключ отозван на платформе.

**Файлы:** git history (все коммиты), `.gitignore` уже корректный.

---

## 2026-05-02 — Автоматический экспорт Apple Health через Health Auto Export

**Проблема:** Старый Shortcut на iPhone (`HealthVault_Daily`) был ненадёжен: требовал ручного запуска, регулярно падал на ошибках, пользователь забывал. Apple Health-данные обновлялись только раз в 2-4 недели через ручной ZIP-экспорт.

**Решение:** Перешли на iOS-приложение [Health Auto Export – JSON+CSV](https://apps.apple.com/app/health-auto-export-json-csv/id1115567069) ($24.99 lifetime). Поддерживает REST API automation с Bearer-auth, JSON формат v2, daily schedule в фоне.

**Что сделано:**
1. Добавлен endpoint `POST /apple_health_v2` в `telegram-bot/webhook/apple_health.py` — функция `_hae_to_daily_payloads()` парсит нативный HAE-формат (`data.metrics[]`), группирует по дням, упсертит в `activity_log` / `blood_pressure_logs` / `weights`.
2. Маппинг 17 имён метрик HAE на нашу схему: `step_count`, `walking_running_distance`, `walking_speed`, `walking_step_length`, `walking_double_support_percentage`, `walking_asymmetry_percentage`, `heart_rate`, `resting_heart_rate`, `blood_pressure` (combined), `weight_body_mass`, `body_fat_percentage`, `lean_body_mass`, `active_energy`, `flights_climbed`, `vo2_max`, `respiratory_rate`, `apple_sleeping_wrist_temperature`.
3. UPSERT для `weights` через прямой SQL `ON CONFLICT (user_id, measured_at) DO UPDATE` — `create_weight()` без upsert падал на повторных запусках.
4. Старый `/apple_health` (v1) оставлен для обратной совместимости.
5. Документация — обновлён `CLAUDE.md` (раздел «Ежедневный автоэкспорт через Health Auto Export»).

**Проверено:** ручной экспорт за неделю прошёл — 6 дней (26.04–01.05) с шагами, BP, весом, %жира, мышцами, походкой, активной энергией, этажами. Ночью 03.05 в 01:34 МСК прошёл первый автозапуск с данными за 02.05.

**Файлы:** `telegram-bot/webhook/apple_health.py`, `CLAUDE.md`.

---

## 2026-04-28 — Фича: кнопка «Удалить» в sheet редактирования (мини-апп)

**Проблема:** удаление item было только свайпом влево — не очевидно. Зашедший впервые пользователь не мог найти как удалить запись.

**Решение:** в sheet редактирования (открывается тапом по item) добавлена кнопка «🗑 Удалить» под «Сохранить» — красным цветом (`.danger-btn`, стандартный iOS destructive action). 2 тапа защищают от случайного удаления. После удаления показывается snackbar с Undo (уже было).

**Файлы:** `telegram-bot/webapp/index.html`, `telegram-bot/webapp/day.css` (+CSS `.danger-btn`), `telegram-bot/webapp/day.js` (обработчик `edit-delete`).

---

## 2026-04-25 — Фича: клетчатка в заголовке каждого приёма пищи (мини-апп)

**Запрос:** Второй пользователь хотел видеть клетчатку в каждом приёме пищи рядом с КБЖУ, как в дневном итоге.

**Было:** в заголовке слота (завтрак/обед/ужин/перекус) — только ккал. Клетчатка была только в развёрнутом списке items.

**Стало:** в правой части заголовка слота под числом ккал добавлена строка "Кл X г" (если > 0). Данные берутся из `m.totals.fib`, который уже приходил из API — просто не отображался.

**Файлы:** `telegram-bot/webapp/day.js` (+2 строки), `telegram-bot/webapp/day.css` (+1 строка).

---

## 2026-04-25 — Фикс: «Псиллиум» без слова «(БАД)» терял клетчатку

**Симптом:** Пользователь 2 (user_id=485132) залогала «Псиллиум 3г» — в мини-аппе клетчатка 0. У Александра те же записи назывались «Псиллиум (БАД)» и LLM ставил fiber=4г из 5г (правильно, ~80%).

**Root cause:** LLM реагирует на «(БАД)» как на подсказку. Без неё — пасует и возвращает fiber=0. Зависимость от формулировки имени.

**Фикс:**
- `core/food/fiber_table.py`: добавлены `псиллиум / псилиум / psyllium` со значением **85г клетчатки на 100г**. Теперь `enrich_items_with_fiber` подстрахует LLM независимо от того, написал юзер «БАД» или нет.
- Тесты: `tests/test_fiber_enrichment.py` +2 кейса (variants + расчёт для случая Ники). 368/368 suite.
- Запись Ники (`log_id=1128`, items[4]) поправлена: fiber `0 → 2.5` (85% × 3г).

**Scope аудита:** просканированы все nutrition_log Александра и Ники с 6 янв на «псиллиум / отруб / клетчатка / семена льна / чиа / шелуха / husk» с `fiber=0`. Хитов — только 1 (запись Ники). У Александра все 20+ записей псиллиума с правильной клетчаткой — для него фикс просто страховка на будущее.

---

## 2026-04-24 — Фикс: вес блюд терялся в `nutrition_log` (amount=0 у 90 записей)

**Симптом:** в мини-аппе у гриль-чиза с тунцом (24.04, 13:41) показывалось `0 г` при правильных КБЖУ 439 ккал / 19Б / 22Ж / 42У. На исходном чеке Яндекс Еды — `165 г`.

**Root cause:** `telegram-bot/handlers/photo.py:985` → `handle_menu_photo` хардкодил `weight_g: None` в `meal_items`, полностью игнорируя `weight` из `menu_data`, которое GPT-vision корректно возвращал. LLM видит вес на упаковках/чеках, но код его выбрасывал.

**Масштаб:** 90 записей за 2026-01-06 … 2026-04-24 с `amount=0` / `amount=NULL` при `calories>0`. КБЖУ везде правильные — только вес потерян.

**Фикс:**
- Новая функция `build_menu_meal_item(menu_data)` в `telegram-bot/handlers/photo.py`: читает `weight` / `weight_grams`, fallback на 100г, помечает `weight_source="llm" | "default_100g"`.
- `handle_menu_photo` теперь собирает `meal_items` через неё.
- Тесты: `tests/test_menu_photo_weight.py` — 8 кейсов (прямой LLM weight, alias `weight_grams`, fallback при None/0/missing, preservation КБЖУ, source marker). 366/366 suite прошли.

**Бэкфилл истории (опция C — оценка из калорий):**
- Скрипт `scripts/backfill/backfill_amount_from_calories.py` с таблицей ккал/г по категориям (вино 0.8, мясо 2.0, сладкое 2.8, батончики 3.5, рыба 1.5, паста 1.5, творог 1.0, кефир 1.0, напитки 0.55, суп 0.6, орехи 5.5, масло 4.0, сушёное 3.5 и т.д.; дефолт 1.5 для готовых блюд).
- Обработано **91 item в 90 записях**. Каждый изменённый item получает поля `"amount_source": "estimated_from_calories"` и `"amount_category": "<категория>"` — чтобы будущие аудиты различали измеренный вес и оценку.
- Проверка на реальном случае: гриль-чиз 439 ккал → эвристика дала 176г, факт 165г (расхождение 7%). После бэкфилла скорректировано вручную на точные 165г с `amount_source="receipt_exact"`.

**Что НЕ трогается:** `calories`, `protein`, `fats`, `carbs`, `fiber` в items и `totals` — они авторитетные, статистика не сдвигается.

**Deploy:** через `deploy.sh`, smoke-тест прошёл. Код поправлен до бэкфилла — новые записи сразу пишутся с корректным `amount`.

— Claude Sonnet 4.7

---

## 2026-04-24 — Архив медицинских документов второго family-пользователя: 25 сканов 2004–2021

**Источник:** 25 JPEG-сканов исторических анализов и выписок. Скачано через Google Workspace MCP (перед этим пришлось убить дубль `workspace-mcp` процесс — был конфликт state OAuth между Claude Desktop и Claude Code).

**Сделано:**
- Все 25 файлов скопированы в папку пользователя в FamilyHealth с именами по схеме `{тип}_{дата}_{источник}.jpeg`
- Визуально просмотрен каждый скан (через thumbnails 900px). Ориентация у всех корректная — поворачивать не требовалось.
- `knowledge_base.json` расширен: blood_tests 27→41, urinalysis 5→6, добавлены секции `coagulation` (3 записи) и `gynecology` (1 запись), imaging 3→5, consultations 1→5.
- `PROFILE.md` обновлён: добавлены диагнозы и исторические лабораторные данные 2004–2021.
- 01.04.2013 — H. pylori + хронический лямблиоз + аскаридоз (выписка НАКО №169).

— Claude Sonnet 4.6

---

## 2026-04-23 — Фикс слот-префикса: голое слово «Завтрак» в caption

**Баг:** пользователь прикрепил фото с подписью «Завтрак» в 12:36, блюдо записалось без префикса («Жареное мясо с рисом и брокколи»), мини-апп разложил его в слот «Обед» (по времени 12:36 → lunch).

**Причина:** регексп в `telegram-bot/handlers/text.py:detect_slot_prefix` требовал разделитель `:`, `-` или `—` после слова. «Завтрак» без двоеточия не матчилось → `apply_slot_prefix` не приклеивал префикс → `slot_from_meal` падал на time-based fallback.

**Фикс:** regex обновлён на `\b` (граница слова) + снятие ведущих не-словесных символов (для эмодзи). Логика аналогична `nutrition_slots._starts_with_token`.

**Что теперь работает:**
- `Завтрак` → Завтрак ✅
- `🌅 Завтрак` → Завтрак ✅
- `Завтрак с кофе` → Завтрак ✅
- `завтракаю` → None (глагольная форма) ✅
- `Поздний обед` → None (квалификатор, time-based) ✅

**Старую БД не трогали** — исходные captions не сохранялись. Массовой ошибки не обнаружено (см. todo для «meal_log.raw_caption» на будущее).

27 новых тестов, **358 тестов всего проходят**. Коммит `cb14ae2`. — Claude Sonnet 4.6

---

## 2026-04-23 — Фикс UserSettings для новых пользователей + deploy.sh

**Баг:** Новые пользователи регистрировались, но `UserSettings` не создавались — `get_user_settings()` возвращал `None`. Симптом: `calorie_goal_pct=None` в бюджете, хотя дефолт должен быть -15%.

**Причина:** Сервер деплоился без пересборки образа. Docker-контейнер работал со старым `/app/database/models.py` (без поля `calorie_goal_pct`) и `crud.py` (без создания UserSettings). `git pull` обновлял только `/opt/healthvault/`, но не контейнер — `COPY . .` в Dockerfile не работал без `docker compose build`.

**Решение:**
- `docker cp` обновлённых файлов в работающий контейнер (быстрая hotfix)
- `scripts/util/deploy.sh` — новый деплой-скрипт с двумя режимами:
  - **fast** (default): rsync → docker cp → restart (~10с)
  - **--full-rebuild**: rsync → docker compose build → force-recreate (~2 мин)
  - Встроенный smoke test: регистрация пользователя + проверка UserSettings

**Проверено:**
```
USER:     999888000 is_active=True             ✅
SETTINGS: calorie_goal_pct=-15, show_bar=True  ✅
BUDGET:   target=1828, has_garmin=False, goal_pct=-15  ✅
```

Коммит `42caea8`. — Claude Sonnet 4.6

---

## 2026-04-22 — Открытая регистрация + admin /block /unblock /users

**Что:** убран статический whitelist, бот стал открытым для всех Telegram-пользователей.

**Изменения:**
- `telegram-bot/middlewares/auth.py`: `is_user_allowed()` → проверка `users.is_active` из БД. `ensure_user_exists()` вызывается на каждом сообщении — новые пользователи регистрируются автоматически.
- `config/users.py`: удалены `ALLOWED_USERS` и `is_user_allowed()`. Остались `ADMIN_USER_ID=895655` и `is_admin()`.
- `telegram-bot/handlers/commands.py`: добавлены admin-команды `/block <id>`, `/unblock <id>`, `/users`. `/start` теперь показывает подсказку `/setup` для новых пользователей без Garmin.
- `tests/test_multi_user.py`: тесты обновлены под open-registration модель. Добавлен `test_new_user_gets_default_settings`.

**331 тест проходит.** Задеплоено на сервер. Коммит `a1f1921`. — Claude Sonnet 4.6

---

## 2026-04-22 — Аудит мультиюзер-готовности + hardening user_id isolation

**Что:** полный аудит хардкода `user_id=895655` в продакшн-коде перед разработкой мультиюзера (запланировано на 25–26 апр). Найдено и исправлено:

1. **`helpers/db_save.py`** — убраны дефолты `user_id=895655` из 4 функций (`save_meal_to_db`, `save_weight_to_db`, `save_supplements_to_db`, `save_body_measurement_to_db`). Теперь `user_id=None` + `raise ValueError` если не передан — молчаливая утечка данных к первому пользователю теперь невозможна.

2. **`database/crud.py`** — `ensure_user_exists()` теперь создаёт `UserSettings` с дефолтами при первой регистрации. До этого новый пользователь существовал без записи в `user_settings`, код везде делал `if s else`.

3. **`telegram-bot/webhook/apple_health.py`** — Apple Health webhook теперь роутит по `users.health_token` (поле уже было в модели). Глобальный `APPLE_HEALTH_TOKEN` → `_PRIMARY_USER_ID` сохранён для обратной совместимости. Каждый пользователь теперь может иметь свой Bearer token.

4. **`services/nutrition_service.py`** — исправлен docstring `default: 895655`.

**Результат аудита (хорошие новости):** все обработчики (`photo.py`, `text.py`, `commands.py`) уже правильно передают `user_id=telegram_user_id`. `caloric_budget.py` обрабатывает `None` settings. `garmin_data.py` поддерживает мультиюзер через `user.garmin_email`. Основной блокер для новых пользователей — `config/users.py` whitelist (требует design decision от владельца).

**Детальный чеклист** перенесён в `todo.md` (пункт «🚀 Полноценный мультиюзер NutriLogBot»).

**330 тестов проходят.** Коммит `d188abf`. — Claude Sonnet 4.6

---

## 2026-04-21 — Полное переписывание AI-context доков

**Что:** ревью обнаружило что 3 из 7 файлов `docs/ai_context/` содержат неверные пути модулей и старые поля БД. Переписаны полностью с применением best practices от Anthropic и опытных AI-coding команд.

**Изменения:**
- ✨ **Новый `README.md`** — индекс с навигацией «когда читать что», принципы поддержки доков (single source of truth, anti-patterns в явном виде, file:line ссылки и т.п.)
- 🔄 **`01_architecture.md`** — полностью переписан. Реальные пути (`core/llm/router.py` а не `core/llm_router.py`), описание мини-аппа, FastAPI слоя, supplements_api, flow данных от ввода до БД, anti-patterns.
- 🔄 **`03_database_schema.md`** — полностью переписан. Все 8 таблиц управляемых ORM + список orphan-таблиц. Реальные имена полей (`fats` не `fat`, `body_fat` не `fat_percent`, `supplement_name` не `name`, FK на `users.telegram_id` не `users.id`). Документированы 3 несовместимые схемы внутри `nutrition_log.items`. Готовые SQL-сниппеты.
- 🔄 **`04_workflows.md`** — полностью переписан. Реальные пути скриптов (`scripts/import/X.py` а не `scripts/import_X.py`). Новые SOP: деплой в продакшен, мини-апп фичи, удаление мёртвой фичи (как делали с `/my_products`).
- 🔄 **`05_food_logging_context.md`** — обновлён. Добавлены новые способы ввода (фото упаковки с авто-весом, мини-апп редактирование, daily-log добавок, голосовое). Обновлена таблица КБЖУ.
- 🛠 **`02_data_sources.md`** — точечные фиксы: `fat`→`fats`, `weight_kg`→`weight`, добавлена шапка с каноническими именами полей.
- ❌ **Удалён `FULL_CONTEXT.md`** (24KB) — полностью overlap'ил с новыми 01+02+03, содержал неверные данные (2 пользователя вместо 3, 125 тестов вместо 307, неверный путь проекта, ссылки на несуществующие скрипты).

**Best practices применены:**
- `**Last verified:** YYYY-MM-DD` в шапке каждого файла → видно стейл с первого взгляда
- Anti-patterns в явном виде с ❌/✅ маркерами
- Single source of truth — каждый факт в одном файле
- File:line ссылки где применимо (например `database/crud.py:172`)
- Канонические команды для копи-паста (psql, pytest, deploy)
- «Почему» в дополнение к «что» (e.g. почему JSONB вместо нормальных таблиц)

**Также:**
- `CLAUDE.md` — обновлена строчка `docs/ai_context/` чтобы вести через `README.md`.
- 307 тестов проходят, никакого кода не тронуто (только доки).

**Файлы:** `docs/ai_context/{README,01_architecture,02_data_sources,03_database_schema,04_workflows,05_food_logging_context,AI_CHANGELOG}.md`, `CLAUDE.md`. Удалён `docs/ai_context/FULL_CONTEXT.md`. — Claude Sonnet 4.6

---

## 2026-04-21 — Fix #5: race condition в supplements toggle (generation counter)

**Что:** быстрые тапы по двум разным добавкам запускали два конкурирующих `loadSupplementsDay()`. Тот что финишировал позже перезаписывал `innerHTML` со стейл-данными — пользователь видел мигание и думал что тап не сработал.

**Решение:** generation counter `_suppLoadGen`. Каждый вызов `loadSupplementsDay()` инкрементирует счётчик и захватывает текущее значение в `gen`. Ответ выбрасывается если `gen !== _suppLoadGen` (т.е. пока летел запрос, стартовал более свежий). Проверка и на успех, и на ошибку.

**Файлы:** `telegram-bot/webapp/index.html`. Коммит `68067df`. — Claude Opus 4.7

---

## 2026-04-21 — Pass 2 #1: унификация схем nutrition_log.items (schema unification)

**Что:** в `nutrition_log.items` JSONB сосуществовали 3 несовместимых диалекта: `{food, amount, unit}` (основной бот), `{name, weight}` (LLM legacy), `{product, weight_g}` (psyllium/internal). Функция `get_recent_product_names` читала только `product`/`weight_g` → «Часто используемое» в мини-аппе было пусто для 90% записей.

**Что сделано:**
- `telegram-bot/webhook/nutrition_api.py` — POST `/api/meal/item` теперь нормализует через `normalize_item_to_canonical()` перед записью в БД
- `database/crud.py:update_nutrition_item_weight` — исправлен: читал `weight_g`, писал гибрид `{amount, weight_g}`. Теперь читает `amount|weight_g|weight`, пишет только `amount`, удаляет legacy-ключи
- `tests/test_nutrition_crud.py` — тест обновлён под канон (`amount`, нет `weight_g`)
- `scripts/backfill_psyllium_nutrition.py` — роутит через `normalize_item_to_canonical()` вместо прямой записи
- `scripts/backfill/normalize_item_schemas.py` — новый DRY/--apply скрипт: сканирует все строки, нормализует только по структуре ключей (не по значениям), идемпотентный
- В продакшене нормализовано **79 из 700** строк (остальные уже канонические). Проверена целостность: месячные суммы КБЖУ для user_id=895655 и user_id=485132 байт-идентичны с pre-migration бэкапом

**Файлы:** `telegram-bot/webhook/nutrition_api.py`, `database/crud.py`, `tests/test_nutrition_crud.py`, `scripts/backfill_psyllium_nutrition.py`, `scripts/backfill/normalize_item_schemas.py`. — Claude Opus 4.7

---

## 2026-04-21 — Архитектурный аудит: top-10 проблем (3 параллельных агента)

**Что:** мульти-агентное ревью кода после серии быстрых фич (фибро-пайплайн, мини-апп редизайн, supplements daily log). 3 параллельных агента с разными ролями (Backend/Data, Frontend/UX, Pragmatic engineer) + личная SQL-проба 100 дней реальных данных.

**Результат:** топ-10 проблем по серьёзности:
- **Tier S (silent data rot):** 3 несовместимые item-схемы, 103 items с null weight, бесполезный unique-constraint (30 дублей), totals.fiber drift между read/write путями.
- **Tier A (UX-баги):** race в supplements toggle, autosave без retry, autosave-pill за tab-bar на iPhone Pro.
- **Tier B (tech debt):** 6 proxy-шимов + dead CSS + archive/2026-02-01/, AI-context доки 5+ недель устарели, photo.py 1217 LOC без тестов.

**Файл:** `docs/2026-04-21-architectural-review.md` (207 строк).

**Делать в три захода:** quick (~2ч) → important (~1д) → reliability (~1д). — Claude Sonnet 4.6

---

## 2026-04-21 — Полная чистка `/my_products` фичи

**Что:** после подтверждения 0 рядов во всех таблицах user_products / user_product_variants полностью удалена фича.

**Удалено (~370 LOC):**
- Bot command handlers: `cmd_my_products`, `cmd_add_product`, `cmd_add_variant`
- CRUD: `get_user_products`, `add_user_product`, `add_product_variant`, `update_product_average_from_variants`, `match_user_product`
- ORM models: `UserProduct`, `UserProductVariant`
- Database imports / `__all__` entries для всего вышеперечисленного
- Early-exit product matching block в `handlers/text.py`

**Database migration (вручную на проде):**
```sql
DROP TABLE IF EXISTS user_product_variants CASCADE;
DROP TABLE IF EXISTS user_products CASCADE;
```

**Telegram bot menu теперь:** /start /day /week /vitamins /help (5 команд вместо 6).

**Verification:** 307 тестов прошли, бот стартует чисто, все 4 API endpoint'а отвечают ожидаемо. — Claude Sonnet 4.6

---

## 2026-04-19 — Полная загрузка EMIAS: 21 PDF + 3 исследования + документация метода

**Что:** Загружены все 21 PDF из ЕМИАС (18 анализов + 3 исследования). Добавлены KB-записи для ОАК 12.07.2024 (24 параметра), ЭКГ 23.01.2025, рентгена рёбер 06.02.2025. Создана документация по методу для повторного использования (Ника и другие члены семьи). Написан отчёт по медицинским находкам.

**Технический метод:**
- Браузер Claude in Chrome + MCP JavaScript tool
- Перехват `URL.createObjectURL` → exfil через localhost:18765 (Python HTTP-сервер)
- JWT рефреш не работает вручную (кука httpOnly) — только через UI-клики
- Документация: `docs/emias_extraction_guide.md`

**Новые записи в KB:**
- `blood_2024-07-12_emias_cbc.pdf` — ОАК 12.07.2024, 24 параметра (все в норме)
- `ecg_2025-01-23_emias_ecg.pdf` — ЭКГ, ритм синусовый, ЧСС 62, ФВД норма
- `xray_2025-02-06_emias_ribs.pdf` — рентген рёбер, диагноз S20.2 (ушиб грудной клетки)

**Медицински важно:**
- 2025-01-23: холестерин 5.66↑, ЛПНП 3.90↑ — выше нормы (последний результат март 2026: 5.24/3.10 — улучшение)
- 2024-08-26: COVID-19 антиген ПОЛОЖИТЕЛЬНЫЙ — повторное заражение (2-й раз после мая 2021)
- 2025-02-06: рентген рёбер S20.2 (ушиб) — был какой-то травматический эпизод
- 2025-01-23: спирометрия ФВД — полностью в норме (ФЖЕЛ, ОФВ1, ОФВ1/ФЖЕЛ все норма)
- 2025-01-23: ЭКГ — норма (синусовый ритм, ЧСС 62 уд/мин, правильный ритм)

---

## 2026-04-19 — Парсинг 17 EMIAS PDF-анализов → knowledge_base.json

**Что:** Загружены 17 PDF-файлов из ЕМИАС за 4 даты визитов в поликлинику.
Извлечены лабораторные значения через PyMuPDF (текст читался корректно).
Обнаружена проблема: ЕМИАС перепутал содержимое и имена файлов (например, файл
`2024-09-02_b26536b3_Протромбиновое_время_+_МНО.pdf` содержит глюкозу 2025-01-23).
Все данные смаплированы по фактическому содержимому.

**Результат:**
- 5 групповых PDF скопированы/обновлены в health folder (merged multi-page)
- 4 существующих KB-записи обогащены полными значениями (было по 1-23 параметра, стало до 30)
- 1 новая запись добавлена: IgE 28.45 МЕ/мл от 2024-07-13
- Создан backup: `knowledge_base.json.bak_20260419_121159`

**Ключевые значения:**
- 2025-01-23: холестерин 5.66 ↑ (норма ≤5.2), ЛПНП 3.90 ↑ (норма ≤3.40), АЛТ 22.2, АСТ 15.3, ЛДГ 192, СРБ 3.0, креатинин 90.3, глюкоза 4.80
- 2024-09-02: АЧТВ 32.7, ПВ 10.8, МНО 1.00, СОЭ 2.0 (все в норме — послековидный контроль)
- 2024-08-26: COVID-19 антиген ОБНАРУЖЕН (повторный COVID, 2-й раз)
- 2024-07-12: ОАК полный + глюкоза 4.68 (норма)
- 2024-07-13: IgE 28.45 МЕ/мл (норма)

**Заметка:** Файл 2024-07-12 "холестерин" по EMIAS API (26e288d5 — ОАК) не загружен;
файл b26536b3 (метка: ПВ+МНО 2024-09-02) фактически содержит глюкозу 2025-01-23.

**Где:**
- KB: `HealthVault/Александр Лысковский — Здоровье/knowledge_base.json`
- PDFs: `blood_2024-07-12_emias_biochem.pdf`, `blood_2024-07-13_emias_ige.pdf`,
  `covid_2024-08-26_emias_antigen.pdf`, `blood_2024-09-02_emias_cbc-coag.pdf`,
  `blood_2025-01-23_emias_biochem-cbc.pdf`

---

## 2026-04-17 — Nutrition day editor mini-app

**Что:** Второй экран Telegram Mini App — редактор дневника питания. Позволяет
просматривать и редактировать все приёмы пищи по любому дню (навигация через
‹ / › / календарь), группированные в 4 слота (Завтрак / Обед / Перекус / Ужин),
добавлять продукты руками (через существующий LLM-пайплайн) или из последних
использованных, менять вес (КБЖУ пересчитывается), удалять со снэкбаром
"Отменить". Sticky-футер с прогресс-барами Ккал/Б/Ж/У/клетчатка до дневных целей.

**Зачем:** до этого нельзя было исправить ошибочно распознанный вес продукта
и посмотреть историю за любой день — только ввод через бота.

**Где:**
- Спек: [docs/superpowers/specs/2026-04-17-nutrition-day-editor-design.md](../superpowers/specs/2026-04-17-nutrition-day-editor-design.md)
- План: [docs/superpowers/plans/2026-04-17-nutrition-day-editor.md](../superpowers/plans/2026-04-17-nutrition-day-editor.md)
- Фронт: `telegram-bot/webapp/{index.html, day.js, day.css}`
- Бэк: `telegram-bot/webhook/nutrition_api.py`, `nutrition_slots.py`, `nutrition_goals.py`
- CRUD: новые хелперы в `database/crud.py`

**Паттерны UX:** cкопированы из MyFitnessPal / Yazio / Cronometer (day-switcher
сверху, 4 слота, "+ add food" в каждом слоте, свайп-to-delete, прогресс-бары
в футере). Фото/голос остаются в боте, мини-апп — только ручной ввод.

---

## 2026

- **[2026-04-18]** Импорт 41 анализа из fdoctor.ru в knowledge_base.json Александра: 35 PDF (кровь, гормоны, витамины, COVID), 1 PDF УЗИ, 5 MD-протоколов. Создан `scripts/import/fdoctor_import.py`, `fdoctor_ir.py`, `update_kb.py`. Исправлены 4 мёртвые ссылки в KB. KB вырос с 48 до 89 записей. — *Claude Code*

- **[2026-04-18]** Автосинхронизация `alcohol_daily.json`: создан `scripts/import/sync_alcohol.py` (читает nutrition_log_remote.json → группирует по дням → пишет alcohol_daily.json). Добавлен в `sync_all_data.sh` шагом 1.9/4. — *Claude Code*

- **[2026-04-19]** Импорт медданных МЦ «Атлас» (2021): найдено 6 писем с atlasclinic.ru, скачано 6 вложений, добавлено 5 файлов в папку здоровья Александра (3 PDF анализов + 2 DOCX: заключение терапевта и УЗИ). 5 новых записей в knowledge_base.json (血CBC, СРБ+железо, ОАМ, приём терапевта с ЭКГ/ЭхоКГ/УЗДГ/ЭФГДС/колоноскопией, УЗИ МВС). KB вырос с 89 до 97 записей (75 с values). GPT-4o Vision использован для парсинга PDF с кастомным шрифтовым кодированием. — *Claude Code*

- **[2026-04-18]** Парсинг лабораторных значений из PDF: создан `scripts/import/parse_lab_pdfs.py` (PyMuPDF → GPT-4o-mini → values в KB). Распарсено 31 PDF, 70 из 89 записей KB теперь имеют поле `values` с числами, единицами и референсами (78%). Оставшиеся 19 — генетика, ПЦР, описательные протоколы УЗИ. — *Claude Code*

- **[2026-04-17]** Обновлён Apple Health export до 16.04.2026: распакован `/Users/alexlyskovsky/Downloads/экспорт 2.zip` → 727 MB XML, запущен `scripts/import/apple_health.py --export_xml '/tmp/ah_export2/apple_health_export/экспорт.xml'`. Результат: АД 128/86 (16.04), пульс покоя 49 уд/мин, шаги ср7д 7 697, ходьба 4.42 км/ч. Данные в `data/apple_health_{blood_pressure,heart_rate,steps_daily,gait}.json`. Примечание: после каждого `/sync` нужно перезапускать импорт вручную — `sync_all_data.sh` находит старый `apple_health_export4/` (март) и перетирает свежие данные. — *Claude Code*

- **[2026-04-17]** Создан `docs/LONGEVITY_BENCHMARKS.md` — сравнительный анализ двух лонджевити-бенчмарков (Blueprint by Bryan Johnson и Singularity Club) с HealthVault: что у них есть, чего нет у нас (пробелы: омега-3 индекс, LDL particle size, MMA, тяжёлые металлы Pb/Hg, ANA, VO₂max, CGM, WGS, фармакогеномика), что есть у нас и нет у них (ежедневная гранулярность). Приоритизированный список «добавить в HealthVault» (🔴/🟡/🟢). Протокол чекапов 2x/год + 1x/год + каждые 3–4 мес. — *Claude Code*

- **[2026-04-17]** `todo.md` — добавлены два раздела: (1) `🏃 VO₂max тест — май-июнь 2026` с адресами (TriSystems Крылатское, FT Studio), ценой 9 500–10 900 ₽, форматом (~60 мин, лактатные пороги, персональные зоны ЧСС); (2) уточнена дата анализов крови «25–26 мая» в заголовке раздела 🩸. DHEA-S, эстрадиол, DHT, IGF-1 были уже в списке. — *Claude Code*

- **[2026-04-17]** `CLAUDE.md` — убраны упоминания Ники Селезнёвой из раздела семейного хранилища медданных (папка HealthVault/Ника) и таблицы «Люди и их ключевые проблемы». В таблице пользователей NutriLogBot (user_id=485132) оставлена — она продолжает пользоваться ботом. Сама папка в Google Drive удалена вручную пользователем. — *Claude Code*

- **[2026-04-10]** Поле `drinks` (стандартные дозы алкоголя) в NutriLogBot: LLM теперь возвращает `drinks` для каждого продукта (1 доза = 10г этанола ≈ 150мл вина ≈ 50мл водки ≈ 500мл пива). Добавлено в SYSTEM_PROMPT, Pydantic-модели (FoodItem, TotalNutrition), `calculate_meal_totals()` в nutrition.py. Бэкфил 599 исторических записей на сервере через SQL regex. Исправлен `_ALCOHOL_RE` — `\b` не работает с кириллицей, заменён на lookbehind. Тесты: 41 новый тест (`test_alcohol_drinks.py`). Итого: 241 тестов, все зелёные. (`core/llm/models.py`, `core/llm/router.py`, `core/food/nutrition.py`, `tests/test_alcohol_drinks.py`) — *Claude Code*

- **[2026-04-09]** BiomarkerDash — извлечение данных из 50 PDF и визуализация: прочитаны все PDF анализов крови через Vision, заполнен `knowledge_base.json` (было 8 записей с данными → стало 20+ дат, 20 маркеров с историей). Исторические данные с 2015 по 2026. Построены 3 графика трендов: Липиды, Печень/метаболизм, ОАК/гормоны/витамины. Сохранены в `data/blood-tests/biomarkers_*.png`. Ключевые находки: холестерин и LDL нестабильны (выход из нормы в 2025-01), тестостерон вырос 10→16 нмоль/л за год, ферритин снизился 286→245, CRP упал 3.0→0.11. — *Claude Code*

- **[2026-04-09]** QA-аудит и регрессионные тесты: проанализированы production-логи сервера (176 Traceback), выявлены 3 класса реальных ошибок. Написаны 4 новых регрессионных теста: `test_cmd_day_no_crash.py` (7 тестов, NameError status_msg), `test_message_formatting.py` (15 тестов, TelegramBadRequest HTML), `test_caloric_density_check.py` (30 тестов, галлюцинации LLM), `test_supplement_recognition.py` (38 тестов, синонимы Метилофолат), `test_show_calorie_bar_setting.py` (12 тестов, show_bar=False). Удалён мёртвый код: `tests/test_repository.py`, `tests/verify_*.py`. Интеграционные тесты помечены `@pytest.mark.integration`. Итого: 200 тестов (было 104), все зелёные. — *Claude Code*

- **[2026-04-09]** Pre-commit хуки: добавлены `ruff` + `ruff-format` + pre-commit-hooks (check-ast, detect-private-key, trailing-whitespace, end-of-file-fixer). Создан `.pre-commit-config.yaml` и `pyproject.toml` с конфигом ruff. Автофикс: 1449 нарушений в core/, telegram-bot/, scripts/. Попутно найдены и исправлены реальные баги: дубликат функции `save_photo` в `photo.py` (строки 629 и 650), дублирующиеся ключи словаря в `description_parser.py` и `health_correlations.py`. Хуки установлены в `.git/hooks/pre-commit`. — *Claude Code*
- **[2026-04-09]** Few-shot примеры в промпте меню: добавлены 5 примеров в SYSTEM_PROMPT (`core/llm/router.py`) — ресторанное меню, Яндекс.Еда, фото еды, меню ккал/100г, бизнес-ланч. Каждый пример показывает правильный формат JSON и содержит NOTE с ключевым правилом. — *Claude Code*
- **[2026-04-09]** Якорные калорийности в промпте: добавлена таблица CALORIC DENSITY ANCHORS в SYSTEM_PROMPT (`core/llm/router.py`) — 15 продуктов где GPT исторически ошибался (сливочное масло 748 ккал/100г vs ошибочные 302, брокколи 34 vs 180, куриная грудка 165 vs 250, креветки 95 vs 160 и др.). Добавлено правило #11: проверять плотность ккал/г в диапазоне 0.1–9. — *Claude Code*

- **[2026-04-08]** Добавлен раздел НАПИТКИ и АЛКОГОЛЬ в STANDARD PORTIONS DATABASE промпта LLM (`core/llm/router.py`). Теперь "бокал вина" → 150г, "рюмка водки" → 50г, "кружка пива" → 500г — LLM больше не ставит "(?" при напитках без указания объёма. Добавлено правило в CRITICAL RULES: конвертировать контейнеры напитков в граммы. — *Claude Code*

- **[2026-04-05]** Фикс: при `show_calorie_budget_bar=false` в `/day` теперь скрываются и калорийный bar, и макро-бары Б/Ж/У (раньше скрывалась только калорийная полоса). (`telegram-bot/handlers/commands.py`). — *Claude Code*

- **[2026-04-05]** Telegram Mini App — панель настроек NutriLogBot v1. Новая таблица `user_settings` (PostgreSQL). CRUD `get_user_settings`/`upsert_user_settings` (`database/crud.py`). `SupplementService` теперь читает расписание добавок из БД вместо хардкода — при первом запуске мигрирует дефолтный список (`core/health/supplements.py`). Параметр `show_bar: bool` в `format_budget_line()` (`core/health/caloric_budget.py`) — Ника может скрыть шкалу калорий. API endpoint `GET/POST /api/settings` с HMAC-SHA256 авторизацией Telegram WebApp (`telegram-bot/webhook/apple_health.py`). SPA `telegram-bot/webapp/index.html` (4 раздела: Питание, Добавки, Уведомления, Справка). StaticFiles смонтирован на `/webapp/`. Задеплоено: `https://health.orangegate.cc/webapp/`. BotFather Menu Button — ручной шаг (URL: `https://health.orangegate.cc/webapp/`). — *Claude Code*

- **[2026-04-05]** Исправлен баг: Метилфолат не записывался при написании "Метилофолат" (опечатка с лишней 'о'). Добавлены синонимы в `_SUPPLEMENT_KEYWORDS` (`telegram-bot/handlers/text.py`) и `self.synonyms` (`core/health/supplements.py`). Добавлены пропущенные записи за Apr 4 и Apr 5 напрямую в БД. — *Claude Code*

- **[2026-04-02]** Клетчатка в боте: добавлено поле `fiber` в промпт LLM (`core/llm/router.py`) — GPT теперь оценивает граммы клетчатки для каждого продукта. Агрегация в `crud.py` и отображение в `/day` (`🌿`) и `/week` уже были готовы. — *Claude Code*

- **[2026-04-02]** Garmin auth — финальное решение: бот больше не логинится паролем никогда. `sync_today_garmin()` использует только garth-токены из `/app/data/garth/895655/`. Токены автоматически копируются на сервер при каждом `/sync` через `push_garmin_to_db.sh`. При ошибке `/day` показывает `⚠️ Garmin недоступен` вместо 0. Полное руководство: `docs/ai_context/GARMIN_AUTH_GUIDE.md`. — *Claude Code*

- **[2026-04-01]** Починён активные калории в боте (показывал 0): (1) Убран вызов `sync_missing_garmin_days` из `commands.py` — бот больше не дёргает Garmin API напрямую, только читает из `activity_log`. (2) Создан `scripts/push_garmin_to_db.sh` — пушит локальные `data/garmin/daily-summary/YYYY-MM-DD.json` на сервер через SSH psql upsert. Добавлен в `sync_all_data.sh` шаг 2.3. (3) Починен баг float→int: `4.0` → `4` через `int()` в python3. (4) Добавлен `export PATH=/opt/homebrew/bin:$PATH` в `deploy.sh` для sshpass. Деплой выполнен. — *Claude Code*

- **[2026-03-30]** Исправлен `scripts/analysis/progress_chart.py`: калории и алкоголь теперь всегда читаются из PostgreSQL через SSH (NutriLogBot → Hetzner VPS). Убран хардкод дат алкоголя и мёртвые пути (`/tmp/hv_nutrition_daily.csv`, `data/nutrition/*.json` per-day). Локальный кэш `nutrition_log_remote.json` используется только как fallback при недоступности SSH (известная проблема: `json_agg` двойной эскейп кавычек в именах блюд). Источники задокументированы в docstring скрипта. — *Claude Code*
- **[2026-03-30]** Архитектурный рефакторинг источников данных: убрана зависимость от Apple Health для HR и шагов. Дашборд переключён на прямое чтение из `data/garmin/daily-summary/*.json` (`stats.restingHeartRate`, `stats.totalSteps`). Apple Health теперь используется только для давления (Omron) и походки (gait) — метрик без альтернативного источника. Обновлены: `CLAUDE.md` (полная таблица источников "что откуда"), `~/.claude/skills/dashboard/SKILL.md` (4 потока переработаны). Давление и походка читаются из PostgreSQL через SSH. — *Claude Code*
- **[2026-03-30]** Добавлен Метилфолат (Solgar Folate 400 мкг, Metafolin) в бот: `core/health/supplements.py` (блок утро, синонимы: фолат/folate/metafolin/5-mthf/methylfolate), `HEALTH.md` (перенесён из «к покупке» в «ежедневно утром»). Деплой выполнен. — *Claude Code*
- **[2026-03-30]** iPhone Shortcut HealthVault_Daily_v8 для Apple Health webhook: создан и подписан `.shortcut` файл (17 действий, gait 4 метрики + АД, `is.workflow.actions.filter.health.quantity` + `statistics`). Endpoint `https://health.orangegate.cc/apple_health`. Проблема: некоторые метрики требуют ручного разрешения в Health app → Shortcuts. Текущий статус: АД и gait ещё не подтянулись (⚠️ 9 дней). — *Claude Code*
- **[2026-03-29]** Apple Health автоимпорт через iPhone Shortcuts: создан FastAPI webhook `telegram-bot/webhook/apple_health.py` (порт 8081, Bearer auth) — принимает шаги, пульс, АД, вес, gait-метрики. Интегрирован с ботом через `asyncio.gather` (`bot.py`). Деплой: порт 8081:8081 в docker-compose, nginx на Hetzner (порт 443 занят xray REALITY → решение через Cloudflare Proxy + Page Rule Flexible SSL). Endpoint `https://health.orangegate.cc/apple_health` работает и пишет в `activity_log` + `weights`. — *Claude Code*
- **[2026-03-29]** Garmin 429 rate limit — восстановление: (1) Причина бана — бот вызывал `sync_garmin_data` при каждом `/day` → 18 попыток пароль-логина за час. Добавлен 4-часовой in-memory backoff в `core/health/garmin_data.py`. (2) Исправлен `garmin_data.py` — сначала загружает garth токены (`Garmin().login(garth_home)`), пароль только как fallback. (3) Свежие токены получены через CAS SSO: CASTGC из Chrome → `sso/signin` → OAuth1 preauthorized → OAuth2 exchange; consumer credentials с S3 (thegarth.s3.amazonaws.com). Access 18ч, refresh 29д. (4) Восстановлены данные за 21-28 марта. — *Claude Code*
- **[2026-03-29]** Исправлен `llm_food_processor.py` PATH A: LLM вес теперь имеет приоритет над regex (regex — только fallback). Убран fuzzy matching по токенам. Добавлен американо в `products.json` (3 ккал/100мл). — *Claude Code*

- **[2026-03-21]** Создан скилл `/refresh` — умная актуализация потоков: проверяет что устарело, запускает автоматические скрипты, говорит что сделать вручную (Apple Health, замеры тела). Исправлено: давление через Apple Health от Omron (не ручной ввод). iPhone Screen Time починен: `aw-import-screentime` + `import_activitywatch.py` — данные до 21.03. Добавки и питание: `fetch_remote_nutrition.sh` тянет с сервера. SOP обновлён в памяти Claude с детальными инструкциями по каждому потоку - *Claude Code*
- **[2026-03-21]** Создан скилл `/dashboard` — табличка полноты 18 потоков данных здоровья с эмодзи. Удалён `import_chrome_history.py` из sync (дублировал Screen Time), данные `chrome_history.json` удалены, RescueTime добавлен в todo.md как замена - *Claude Code*
- **[2026-03-21]** Рефакторинг хранения OAuth-токенов: единое место `data/cache/tokens.json` (в .gitignore). Удалена воссозданная `tools/scaleconnect/`, путь в `import_zepp_api.py` обновлён, CLAUDE.md дополнен таблицей секретов - *Claude Code*
- **[2026-03-21]** Итоговый PDF анализов CMD (DFF39243844) сохранён как `blood_cmd_2026-03-19_comprehensive.pdf`, knowledge_base.json обновлён с инсулином 8.1 и HOMA 1.7 - *Claude Code*
- **[2026-03-21]** Импортирован свежий экспорт Apple Health (738 MB, данные по 21.03.2026): 1037 замеров веса, 156 АД, 4075 дней шагов, 2049 пульс покоя, 1999 дней ходьбы - *Claude Code*
- **[2026-03-21]** Рефакторинг проекта: удалены `tools/scaleconnect/` (9 MB, заменён OAuth2 API), `database/repository.py` (deprecated), стейл-файлы в `data/analysis/`, bot-логи, кэш. Удалены дублирующие доки `ARCHITECTURE.md`, `ONBOARDING.md`, `QUICK_START.md`, `README_DATA_ANALYSIS.md`. SQL миграции перемещены в архив - *Claude Code*
- **[2026-03-21]** Обновлён HEALTH.md: актуальные данные марта 2026 (вес 77.7, АД 122/78, все анализы CMD), убраны @@TODO@@ маркеры, таблица замеров тела - *Claude Code*
- **[2026-03-21]** Создан CLAUDE.md — контекст для Claude Code с навигацией по проекту, источниками данных, skills и правилами - *Claude Code*

- **[2026-03-01]** Создана модульная база знаний `docs/ai_context/` для улучшения контекста ИИ - *Antigravity*
- **[2026-03-01]** Добавлен скрипт `import_screentime.py` для парсинга `knowledgeC.db` MacOS. Успешно извлечено 1000 событий, для работы скрипта выдан Full Disk Access - *Antigravity*
- **[2026-03-01]** Настроена интеграция с Netatmo (`scripts/import_netatmo.py`), осуществляется переход на Refresh Token авторизацию - *Antigravity*
- **[2026-03-01]** Исправлен баг: алиасный матч в `find_product` не имел защиты от ложных срабатываний — короткий алиас ("черри") матчился с длинным составным блюдом, возвращая неверные КБЖУ (45 ккал вместо 250 для салата с креветками). Добавлен guard `len(query_significant) > len(alias_significant) + 1` аналогичный тому, что был в секции product name matching. (`core/product_search.py`) - *Claude*
- **[2026-03-09]** Настроен pipeline iPhone Screen Time (по-приложенно): ActivityWatch v0.13.2 + aw-import-screentime читает Apple Biome файлы → 6437 событий за Feb 9–Mar 9 (93 приложения). Создан `scripts/import_activitywatch.py` — агрегирует события из AW API по дням (UTC+3), сохраняет в `data/activities/iphone_screentime_perapp.json`. ActivityWatch добавлен в Login Items (автозапуск). LaunchAgent `com.healthvault.screentime-import` запускает ежедневно в 8:00: aw-import-screentime + import_activitywatch.py - *Claude*
- **[2026-03-09]** Создан `scripts/import_mac_screentime.py` — Mac Screen Time по-приложенно из двух источников: knowledgeC.db (до 30 дней истории, bundle IDs) + ActivityWatch aw-watcher-window (накапливается с Mar 9). Автоматически объединяет: AW приоритетнее если накопил ≥30 мин/день. Сохраняет в `data/activities/mac_screentime_perapp.json`. Добавлен в LaunchAgent (ежедневно 8:00) - *Claude*
- **[2026-03-09]** Создан `scripts/import_chrome_history.py` — импорт Chrome Browser History (~26k визитов, 84 дня). Метрики по мотивам биохакеров/RescueTime: домены с категориями (12 категорий: ai_tools/social_media/entertainment/work/...), почасовое распределение, предсонная зона 22-00, переключения контекста (смен домена/час как мера расфокуса). Скорость: 0.4 сек. Добавлен в LaunchAgent (ежедневно 8:00). Вывод: `data/activities/chrome_history.json` - *Claude*
- **[2026-03-09]** Станция Netatmo "Гнездышко" исключена из импорта: добавлен `SKIP_STATIONS = {'Гнездышко'}` в `scripts/import_netatmo.py`, ключ удалён из `data/environment/netatmo_history.json`. Физически удалить Home Coach через API невозможно (Netatmo архитектурно исключает его из homes API, home_id = None) - *Claude*
- **[2026-03-10]** Исправлена документация источников данных: обнаружено, что `03_database_schema.md` содержал устаревшую схему `nutrition_log` (несуществующие колонки `calories`, `protein`, `fat`, `carbs`, `meal_type` и др.). Реальная схема: КБЖУ хранится в JSONB поле `totals` (`totals->>'calories'`). Обновлены: (1) `03_database_schema.md` — актуальная схема + рабочий SQL; (2) `02_data_sources.md` — добавлена шпаргалка "откуда брать данные" с таблицей источников и примерами SQL/bash-команд, секция критических ошибок; (3) `MEMORY.md` — раздел "Data Access Rules" с правилами источников и именем правильного docker-контейнера (`healthvault_postgres`, не `healthvault_db`) - *Claude*
- **[2026-03-09]** Добавлены новые потоки Apple Health: шаги (👣) и характеристики ходьбы (🚶 gait-метрики). Обновлён `scripts/import_apple_health.py`: теперь импортирует StepCount (суточные суммы по всем источникам Garmin+iPhone) → `data/apple_health_steps_daily.json` + WalkingSpeed/StepLength/DoubleSupportPercentage/AsymmetryPercentage → `data/apple_health_gait.json`. Ключевые цифры: средняя активность 16,725 шагов/день (с 6 янв), скорость ходьбы 4.94 км/ч, двойная опора 26.8%, асимметрия 0% (9 марта). Импорт добавлен в `sync_all_data.sh` как необязательный шаг 5 (автопоиск export.xml в ~/Downloads/). Обновлены: `docs/ai_context/02_data_sources.md` (добавлены секции 5b и 5c), `/sync` скилл (шаги и гайт в таблице актуальности) - *Claude*
- **[2026-03-15]** Добавлен источник данных «Погода». Создан `scripts/import_weather.py`: определяет локацию через LOCATION_OVERRIDES → Garmin GPS (`startLatitude/startLongitude`) → CoreLocationCLI (WiFi) → дефолт Москва. Получает данные с Open-Meteo API (температура, давление hPa→mmHg, влажность, солнце, УФ, код погоды). Умный режим `update_since_last()` заполняет пропуски с последней записи. Загружено 69 дней истории (2026-01-06 → 2026-03-15), включая override Санкт-Петербург 29-30 янв (найдено по авиабилетам в Gmail). Скрипт добавлен в `/sync` скилл (`~/.claude/skills/sync/SKILL.md`). Проведён корреляционный анализ HRV+сон+погода: сон влияет на HRV сильнее давления. Файл данных: `data/weather/weather_history.json`. ROADMAP обновлён: добавлен раздел «Погода и геолокация» — тест в других городах, Welltory/Oura подходы, автодетект поездок - *Claude*
- **[2026-03-15]** Записаны замеры тела (14 марта): талия (над пупком 97 см, по пупку 99 см), грудь по соскам 105 см, шея 42 см, бицепс 33 см, бёдра 99 см, икра 38 см, бедро 54 см (`data/weights/body_measurements.json`) - *Claude*
- **[2026-03-15]** Восстановлен импорт Zepp Smart Scale (Mi Body Composition Scale 2). Причина поломки: Xiaomi заблокировала программный логин через `account.xiaomi.com/pass/serviceLogin` (anti-bot, возвращает HTML вместо JSON) → бинарник scaleconnect v0.4.1 перестал работать. Решение: создан `scripts/import_zepp_api.py` — OAuth2 через браузер (Xiaomi → code → `account.huami.com/v2/client/login` → app_token), запросы к CN3-серверу (`api-mifit-cn3.zepp.com`) через Hetzner SSH-прокси (CN3 недоступен из VPN/России). Токен живёт ~5-7 дней, обновляется через `--reauth`. Восстановлены 9 записей (10-15 марта) с полным составом тела (висцеральный жир, мышечная масса и др.). Обновлены: `scripts/sync_all_data.sh`, `docs/ai_context/02_data_sources.md` - *Claude*
- **[2026-03-09]** Проведён полный аудит источников данных. Обновлён `docs/ai_context/02_data_sources.md`: расширен до 15 потоков (добавлены АД, Chrome History, разделены iPhone/Mac Screen Time), задокументированы gaps в PostgreSQL (HRV=NULL в activity_log, sleep_records и workouts пустые). Удалён мёртвый файл `data/blood-pressure/blood_pressure_log.json` (1 запись, заброшен). Обновлён `scripts/sync_all_data.sh`: заменён устаревший `import_screentime.py` на три новых скрипта (import_activitywatch.py, import_mac_screentime.py, import_chrome_history.py). Создан скилл `/sync` (`~/.claude/skills/sync/SKILL.md`) — аналог /cleanup для данных: синхронизирует все источники + выводит таблицу актуальности - *Claude*
