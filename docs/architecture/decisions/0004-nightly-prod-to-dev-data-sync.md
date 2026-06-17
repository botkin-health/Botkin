# ADR-0004: Ночной синк данных прод→дев (гибрид upsert/replace)

**Дата:** 2026-06-17
**Статус:** Accepted
**Автор:** Игорь Николаев
**Связи:** [#101](https://github.com/botkin-health/Botkin/issues/101), [ADR-0003](0003-alembic-for-db-migrations.md) (единый baseline-схемы prod/dev)

## Контекст

Дев-стенд (`@botkin_dev_bot`, `/opt/botkin-dev`, project `botkin-dev`) поднят со схемой, стэмпнутой с того же Alembic-baseline, что и прод, но **без данных**. Для реалистичного теста фич (дашборд, agent-tools, парсинг еды, биомаркеры) нужны прод-данные, причём владелец хочет **сохранять** свои дев-тестовые строки, а не терять их при каждом обновлении.

Прод содержит реальные медданные/PII; хост у прода и дева **общий** (multi-tenant). Прод трогать на запись нельзя.

## Решение

GitHub Action (`sync-prod-to-dev.yml`, `schedule '0 0 * * *'` = 03:00 МСК + `workflow_dispatch`) заходит по SSH на Hetzner и запускает серверный `scripts/ci/sync-prod-to-dev.sh`. Оба Postgres на одном хосте → синк через host-side pipe `docker exec … \copy`.

Ключевые решения:

1. **Прод строго read-only.** Единственный контакт с продом — `\copy … TO STDOUT`. Никаких записей.

2. **Гибрид по типу ключа таблицы** (а не единое зеркало — чтобы дев-тест выживал):
   - **Upsert** для таблиц с естественным ключом (`users`, `user_settings`, `nutrition_log`, `weights`, `activity_log`, `blood_pressure_logs`, `blood_tests`, `cgm_connections` по `patient_id`, `glucose_readings` по `user_id,ts`): прод-строки добавляются/обновляют совпадающие по ключу; дев-only строки сохраняются. Surrogate `id` **не переносим** — дев выдаёт свой → исключаем коллизию PK между двумя независимо инкрементящими БД.
   - **Full-replace** для таблиц только с serial `id` без естественного ключа (`body_measurements`, `supplements_log`, `workouts`, `agent_conversations`): `TRUNCATE` + копия + `setval`. Дев-only строки в них теряются (осознанно: там импорт, не ручной тест).
   - **Skip** служебных/orphan (`audit_log`, `llm_usage_log`, `daily_summaries`, `sleep_records`).

3. **Заливка под `session_replication_role = replica`.** Глушит аудит-триггер `audit_admin` (иначе построчный флуд дев-`audit_log` + тормоза на bulk-load) и FK-проверки на время загрузки. Возвращается в `origin` по завершении.

4. **Коннект ролью-владельцем `healthvault`** (она же superuser в дефолтном postgres-образе). Владелец RLS игнорирует → экспорт/импорт видят все строки. Защита от тихой регрессии: **sanity-guard** «`users` экспортировано > 0» — если кто-то включит `FORCE ROW LEVEL SECURITY`, синк не зальёт молча пустоту, а упадёт.

5. **Фильтр `WHERE <ключ> IS NOT NULL`** для upsert. Прод-схема местами nullable (см. ADR-0003 п.3); `NULL != NULL` в `ON CONFLICT` плодил бы дубли каждую ночь. Строки с NULL в конфликт-ключе не синкаются (край, логируется).

6. **Порядок и FK.** `users` грузится первой и **только upsert, никогда TRUNCATE** (снёс бы детей каскадом по `ON DELETE CASCADE`). Full-replace детей безопасен (на них никто не ссылается).

7. **data-файлы.** `rsync -a` **без `--delete`** `/opt/botkin/data → /opt/botkin-dev/data` через одноразовый privileged-контейнер (каталоги принадлежат uid 10001). Без `--delete` — дев-only файлы целы; синхронны с `nutrition_log.photo_paths` / `blood_tests.file_path`.

## Альтернативы

- **Reuse nightly `pg_dump` (`/opt/backups`) + restore** — отвергнуто: это полные снимки всей БД (root-only), а нужна **выборочная** заливка с upsert-слиянием по таблицам, чего restore не выражает (затёр бы дев-тест целиком = «полное зеркало», которое явно не нужно).
- **Деривация классификации из схемы** (вместо явных списков) — отвергнуто: не выводится надёжно (`daily_summaries` имеет естественный ключ, но orphan→skip; `glucose_readings` нужен `IS NOT NULL` по ключу). Явные списки + **coverage-guard** (каждая прод-таблица обязана быть в UPSERT/REPLACE/SKIP, иначе `die`) дают безопасность без хрупких эвристик — новая таблица из миграции не выпадет из синка молча.

## Последствия

**Плюсы:** дев получает реальные данные, сохраняя свой тест в natural-key таблицах; прод недостижим на запись; идемпотентно (повторный прогон не плодит дубли); устойчиво к включению RLS; coverage-guard ловит новые неклассифицированные таблицы.

**Минусы / риски:**
- **PII на деве:** прод-медданные (включая `agent_conversations` — приватная переписка с AI-врачом) ложатся на менее защищённый дев-стенд. Принято осознанно (raw-копия).
- **Активация только с `main`:** `schedule`/`workflow_dispatch` работают, лишь когда workflow на default-ветке → нужен `dev→main`, иначе cron молчит. Первый прогон — вручную с `dry_run`.
- **Дев-тест в replace-таблицах** (`body_measurements`/`supplements_log`/`workouts`/`agent_conversations`) затирается каждую ночь.
- **superuser-допущение** для `session_replication_role`: в дефолтном образе `healthvault` — superuser; иначе fallback — поштучный `ALTER TABLE … DISABLE TRIGGER audit_admin` (хватает прав владельца).
- **Дев одноразовый by design** — pre-sync бэкап дева не делаем (в отличие от прод-миграций по ADR-0003).
