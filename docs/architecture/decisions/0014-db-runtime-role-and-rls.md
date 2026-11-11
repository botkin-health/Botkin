# ADR-0014: Рантайм-роль БД без superuser, RLS как второй рубеж; доступ к ресурсам владельца по стабильному ID

**Дата:** 2026-11-09 · **Статус:** Proposed · **Автор:** Александр Лысковский (с Claude)

## Контекст

Внешний пентест 08.11.2026 (пункты F5 и F3). Срочное закрыто PR #676/#677. Здесь — второй рубеж защиты медданных.

Что было на 08.11.2026 (сверено на проде и деве):

- Приложение ходит в Postgres ролью `healthvault`: `rolsuper=t`, `rolbypassrls=t`, она же владелец всех таблиц. RLS для неё не действует.
- RLS-политики есть на 14 таблицах, но написаны `TO hv_app`, а `hv_app` приложение не использует. Половина таблиц с медданными RLS не включала вовсе: `blood_tests`, `body_measurements`, `workouts`, `health_reports`, `food_interactions`, `personal_access_tokens`, `users` и др.
- Политика `agent_conversations_self` (роль `public`) пропускает **все** строки, если `app.user_id` пуст.
- `set_user_session_var` (`SET LOCAL app.user_id`) вызывается в одном месте — `webhook/jwt_auth.py`. После первого `commit()` переменная сбрасывается, следующая транзакция идёт без контекста.
- Изоляция пользователей держится только на `WHERE user_id = …` в коде. Один забытый фильтр, и пользователь видит чужие анализы.
- Доступ к legacy-KB владельца (`knowledge_base.json`), генетике и Netatmo выдавался по `users.cohort == 'owner'`. Админка позволяет сменить cohort любому пользователю, так что админ (или тот, кто украл админ-сессию) мог одним кликом открыть пользователю медкарту владельца.

## Решение

### 1. Три роли Postgres

| Роль | Атрибуты | Кто использует | URL |
|---|---|---|---|
| `healthvault` | владелец таблиц, superuser (bootstrap-роль образа postgres) | только миграции (Alembic) и ручной ops | `MIGRATIONS_DATABASE_URL` |
| `hv_app` | `NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE`, только DML | **по умолчанию** всё приложение: бот, агент, дашборд, мини-апп, вебхуки | `DATABASE_URL` |
| `hv_system` | `NOSUPERUSER BYPASSRLS`, только DML | только явный `system_session()`: планировщик, админка, bootstrap-аутентификация по токену, межпользовательские операции | `SYSTEM_DATABASE_URL` |

`hv_app` переиспользуем: роль уже есть на проде и деве, все гранты и политики написаны на неё.

Пароли в миграциях не живут. Миграция создаёт роли `NOLOGIN`, логин и пароль включает ops-шаг (`scripts/ops/db_roles.sh`), пароли лежат в `.env` стенда.

### 2. RLS на всех таблицах с `user_id`

- Единая функция `app_current_user_id()` = `NULLIF(current_setting('app.user_id', true), '')::bigint`.
- Политика `user_isolation` для `hv_app`: строка видна и пишется только если её владелец = `app_current_user_id()`. Колонка владельца — `user_id`; для `users` и `cgm_connections` — `telegram_id`, для `cgm_followers` — `owner_user_id`.
- Нет контекста — нет строк (fail-closed). Исключения «пустой контекст = видно всё» убраны (`agent_conversations`).
- Политики «только для админа» (`audit_log`, `funnel_events`) — `USING (false)` для `hv_app`. Запись туда идёт через `system_session()`.
- Глобальные справочники (`verified_products` с `user_id IS NULL`, `alembic_version`) не трогаем.
- `FORCE ROW LEVEL SECURITY` не включаем: владелец `healthvault` — роль миграций, ей RLS только мешает.

### 3. Контекст на границах транзакций

`database/rls.py`:

- `contextvar` `current_user_id` и контекст-менеджер `user_context(uid)`.
- Слушатель `after_begin` на всех сессиях `SessionLocal`: в начале **каждой** транзакции выполняет `set_config('app.user_id', <uid>, true)`. Источник: `session.info['app_user_id']`, иначе contextvar. Поэтому контекст переживает `commit()`: новая транзакция получает его заново, а `SET LOCAL` руками больше не нужен.
- `bind_user(db, uid)` привязывает уже открытую сессию к пользователю (пишет `session.info` и, если транзакция открыта, сразу выставляет переменную). Им заменён `set_user_session_var`.

Где ставится контекст:

| Граница | Источник `user_id` |
|---|---|
| aiogram, outer-middleware на каждый update | `event.from_user.id` |
| Tools API агента (`jwt_auth.get_agent_user`) | `sub` из проверенного JWT |
| Дашборд, мини-апп, `/share`, `/report`, вебхуки Apple Health / Android | пользователь из bootstrap-аутентификации (ниже) |
| BotkinClaw (`ask_agent`) | вызывается из хендлера, contextvar уже стоит |

### 4. Явные пути вне RLS

- **Bootstrap-аутентификация.** Поиск пользователя по `health_token`, `share_token`, PAT, initData делается до того, как пользователь известен. Это отдельные функции в `database/crud.py`, они ходят через `system_session()` и возвращают только `telegram_id`. Дальше запрос работает в обычной сессии `hv_app` с `bind_user`.
- **Админка и планировщик** — `system_session()`. Это видно в коде и ищется grep'ом. Каждый новый вызов `system_session()` в ревью проверяется так же, как raw SQL.
- Пока `SYSTEM_DATABASE_URL` не задан, `system_session()` идёт в тот же движок, что и приложение. Так код можно выкатить до переключения ролей: поведение не меняется.

### 5. Ресурсы владельца — по стабильному ID

`users.cohort` больше ничего не открывает. Legacy-KB (`knowledge_base.json`), генетика из него и Netatmo доступны только пользователю `config.users.OWNER_USER_ID`: env `BOTKIN_OWNER_ID`, без него — основной админ из `BOTKIN_ADMIN_IDS`. Оба значения задаёт оператор в `.env`, из админки их не поменять. Админка больше не даёт выставить cohort `owner`.

## Альтернативы

- **Одна роль, обход RLS через GUC `app.system = on`.** Отвергнуто: SQL-инъекция в пользовательском пути сама выставит `set_config('app.system', 'on')` и получит всё, включая админские таблицы. Отдельную роль без membership так не получить.
- **Переписать планировщик на цикл «по пользователю с контекстом» вместо `hv_system`.** Правильно в перспективе, но это десятки джоб и большой риск регрессий за один PR. Оставлено как направление: у каждого `system_session()` должна быть причина.
- **SECURITY DEFINER-функции для bootstrap-поиска по токену.** Уже, чем `hv_system`, но юнит-тесты гоняются на SQLite, где таких функций нет. Вернуться, если `hv_system` уберём совсем.
- **`FORCE RLS` и отдельный владелец таблиц без superuser.** Нужна смена владельца у всех объектов и правка baseline. Выигрыш маленький: `healthvault` и так не используется рантаймом.
- **ACL-таблица для ресурсов владельца.** Ресурс один (файлы владельца на сервере), потребитель один. Env-ID проще и тоже не редактируется из админки. Если появятся общие ресурсы семьи — делать ACL.

## Последствия

**Позитивные**

- Забытый `WHERE user_id` в пользовательском пути возвращает только свои строки: проверено тестом `tests/integration/test_rls_runtime_role.py` на настоящем Postgres в CI.
- SQL-инъекция в пользовательском пути не меняет схему, не выключает RLS и не читает админские таблицы (`audit_log`, `funnel_events`).
- Перехват админки больше не открывает медкарту владельца сменой cohort.

**Негативные / trade-offs**

- **RLS по GUC не защищает от SQL-инъекции полностью.** `app.user_id` — обычная переменная сессии: инъекция может вызвать `set_config('app.user_id', '<чужой id>', true)` и читать чужие строки. RLS здесь — защита от забытого фильтра и логических ошибок, а не от инъекций. От инъекций защищают параметризованные запросы. Усиление на будущее: подписанный контекст (GUC с HMAC, проверка в SECURITY DEFINER-функции с секретом, недоступным `hv_app`).
- Рантайм-контейнер по-прежнему знает пароль `hv_system` (и `POSTGRES_PASSWORD` через `env_file`). От RCE в контейнере это не защищает. Следующий шаг — гонять миграции отдельным one-shot контейнером и убрать owner-пароль из env бота.
- Новый код, который открывает сессию вне хендлера и вне `user_context`, получит пустой результат вместо данных. Это сознательный fail-closed. На деве такие транзакции логируются (`RLS: транзакция без контекста`), по логу находим пропущенные места.
- Гонять `hv_app` в юнит-тестах нельзя (SQLite), RLS проверяет только интеграционный тест на Postgres.

**Что НЕ делать**

- ❌ Открывать `system_session()` в пользовательском пути «чтобы заработало». Сначала понять, почему нет контекста.
- ❌ Писать политики с «пустой контекст = видно всё».
- ❌ Давать доступ к данным по `users.cohort`. Cohort — сегмент для аналитики и онбординга, не право доступа.
- ❌ Вызывать `SET app.user_id` без `LOCAL`: переменная прилипнет к соединению в пуле и уедет к следующему пользователю. Только `set_config(..., true)` в `after_begin`.

## Раскатка

1. Код (этот PR) выкатывается без смены ролей: `system_session()` = тот же движок, контекст выставляется, но `healthvault` его игнорирует.
2. Миграция `rls02`: роль `hv_system`, функция `app_current_user_id()`, RLS на оставшихся таблицах, исправленная политика `agent_conversations`, гранты `hv_app` на `users`.
3. Дев: `scripts/ops/db_roles.sh` задаёт пароли; в `/opt/botkin-dev/.env` — `APP_DATABASE_URL` (hv_app), `SYSTEM_DATABASE_URL` (hv_system), `MIGRATIONS_DATABASE_URL` (healthvault); редеплой; e2e.
4. Прод — только после согласования с Александром, теми же шагами. Откат — убрать `APP_DATABASE_URL` из `.env` и перезапустить: compose вернёт `healthvault`.

## Ссылки

- Миграции RLS: `database/alembic/versions/rls02_runtime_role_rls.py`, ранее `database/migrations/add_rls_*.sql`
- ADR-0003 (Alembic), ADR-0006 (PAT→JWT)
- PostgreSQL: [Row Security Policies](https://www.postgresql.org/docs/15/ddl-rowsecurity.html), [`set_config`](https://www.postgresql.org/docs/15/functions-admin.html#FUNCTIONS-ADMIN-SET)
