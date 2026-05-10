# ИИ-Журнал Изменений (AI Changelog)

В этом файле ИИ-ассистенты (Cursor, Claude, Antigravity) фиксируют завершенные задачи. Это нужно для передачи контекста между IDE.

**Правило добавления:**
`[YYYY-MM-DD] Краткое описание реализованной фичи (затрагиваемые файлы) - Автор`

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

## 2026-05-10 — Мультипользовательский дашборд + медданные Андрея Походни

**Задача:** Подключить Андрея Походня к HealthVault, настроить HAE, загрузить исторические данные, улучшить дашборд.

**Данные Андрея (user_id=836757955):**
- HAE (Health Auto Export) настроен → webhook `POST /apple_health_v2`, токен сохранён
- Бэкфилл 60 дней из knowledge_base.json → `activity_log` (60 строк обновлено)
- `blood_pressure_logs`: 12 пар (уже были из ранних сессий)
- Задокументировано 122 ЭКГ-записи Apple Watch: SinusRhythm:53, AFib:66, HighHR:3 (диапазон 2021→2026)
- **Клинически важно:** 66 эпизодов ФП до госпитализации янв 2025 → ФП предшествовала POAF, не следствие операции
- `biomarkers_836757955.json` обновлён: 35 ключей vs 7, добавлены AST 60.3↑, GGT 18, CRP 6.31, hs_CRP, фибриноген, WBC и др.

**Sprint 3 план:**
- `docs/superpowers/plans/2026-05-10-sprint3-ecg-syncope.md` — план импорта ЭКГ в `ecg_event` + `syncope_event` (6 задач, ~787 строк)
- Таблицы в БД пока не созданы — следующая итерация

**Дашборд — мультипользовательские исправления:**
- `dashboard_blocks.has_blood_test_data`: убран хардкод `cohort == "owner"`, теперь проверяет `biomarkers_{telegram_id}.json` для ЛЮБОГО пользователя
- `dashboard_generator.biomarkers_latest`: добавлены AST, GGT, hs_CRP, NT_proBNP (cardiac markers для Андрея)
- `biomarkers_836757955.json`: исправлен ключ `hsCRP` → `hs_CRP` для совместимости с панелями Attia
- `mc_template.html`: улучшен график калорий — стековый вывод алкоголь/еда (alco_kcal split)
- Задеплоено и проверено: обе ссылки `/mc/*` работают, все маркеры отображаются

**Коммиты:**
- `a0ffd2c` fix(router+dashboard): legacy aiogram fallback + pack-aware targets
- `d81a972` feat(health): Sprint 3 plan — ecg_event + syncope_event tables and import
- `4917927` feat(dashboard): multi-user blood-test support + cardiac markers

**Дополнение (10.05.2026, завершение сессии):**
- `knowledge_base.json` Андрея обновлён из `knowledge_base (1).json` (более новая версия, 442889 → 444742 байт)
- КТ 28.01.2025 дополнен количественными находками: плевральный выпот ~400-450 мл, перикардиальный выпот 17 мл, атelectазы S6/S7-8/S9-10 слева, гепатоспленомегалия (ПД печени 18 см, SI=588), компрессия чревного ствола (MALS-подобная), замедленная эвакуация желудка. Добавлено `clinical_significance` — механизм POAF.
- **Исправление**: 66 AFib ECGs → все относятся к POAF-периоду 27.01–02.02.2025. До операции ФП НЕ было (исправлено неверное утверждение из CHANGELOG от 10.05).
- PROFILE.md Андрея: секция КТ 28.01.2025 дополнена объёмами выпота + механизм POAF
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
4. Миграция применена к production DB; backfill: owner/bariatric (895655), family/female-cycle (485132), early_user/cardiac (836757955).

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

## 2026-04-24 — Архив медицинских документов мамы (Валерия): 25 сканов 2004–2021

**Источник:** письмо от Валерии (мама, v.vachest@mail.ru) с 25 JPEG-сканами. Скачано через Google Workspace MCP (перед этим пришлось убить дубль `workspace-mcp` процесс — был конфликт state OAuth между Claude Desktop и Claude Code).

**Сделано:**
- Все 25 файлов скопированы в `HealthVault/Валерия Лысковская — Здоровье/` с именами вида `blood_2013-04-01_sls_biochem.jpeg`, `discharge_2015-10-15_zhd_hospital_pituitary_adenoma_surgery.jpeg` и т.п.
- Визуально просмотрен каждый скан (через thumbnails 900px). Ориентация у всех корректная — поворачивать не требовалось.
- `knowledge_base.json` Валерии расширен: blood_tests 27→41, urinalysis 5→6, добавлены секции `coagulation` (3 записи) и `gynecology` (1 запись), imaging 3→5, consultations 1→5 (включая выписку по операции аденомы гипофиза 15.10.2015 с полным предоперационным гормональным профилем).
- `PROFILE.md` Валерии обновлён: добавлены диагнозы (жировой гепатоз, атеросклероз БЦА, H. pylori-ассоциированная диспепсия+лямблиоз+аскаридоз 2013, ЧМТ 2004, перелом лучевой 2015). Расширены таблицы холестерина (история 2004–2015 с пиком 14.69 в июне 2015), ГГТ, лимфоцитоза (уже в 12.2021), преддиабета, гиперурикемии.

**Ключевые находки:**
- Аденома гипофиза — операция **22.10.2015** (НУЗ ДКБ ст.Новосибирск-Главный, транссфеноидально). Предоп гормоны: ТТГ 0.030 ↓, Пролактин 66.57 ↑↑.
- Холестерин достигал **14.69** (10.06.2015) — максимум за всю историю, ИА 7.07.
- ГГТ **484** (01.04.2013) — почти 13× норма. АЛТ 97 в 2013, 118 в 2015.
- Лимфоцитоз 56.7% уже в 07.12.2021 — проблема тянется 4+ года.
- Жировой гепатоз впервые зафиксирован 26.04.2010 (выписка НАКО №753).
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
