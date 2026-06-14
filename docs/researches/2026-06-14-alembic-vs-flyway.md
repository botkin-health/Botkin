# Ресёрч: фреймворк миграций БД — Alembic vs Flyway

> Дата: 2026-06-14 · Issue: [#83](https://github.com/botkin-health/Botkin/issues/83) · Решение: **Alembic**

## Вопрос

Какой migration runner подключить к Botkin (Python 3.11 + SQLAlchemy 2.0 + Postgres):
Alembic или Flyway?

## Вывод

**Alembic** — для Python/SQLAlchemy-проекта это не близкий выбор.

## Сравнение

| Критерий | **Alembic** | Flyway |
|---|---|---|
| Рантайм | чистый Python (`pip install alembic`) | **нужна JVM** (Java) |
| Связь с ORM | автор тот же, что у SQLAlchemy; нативная | ORM не знает |
| **Autogenerate** из моделей | **да** (дифф `Base.metadata` ↔ БД) | нет, миграции руками |
| Формат миграций | Python (`op.*`) или raw SQL (`op.execute`) | только SQL |
| Async-движок | поддержка | n/a |
| Down-миграции | да | да (Teams/платно для undo) |
| Polyglot (Java/Go/…) | нет | да |
| Кривая входа | чуть круче, но мы уже в SQLAlchemy | проще для чистого SQL |

## Почему именно для Botkin

1. **JVM в Docker** — Flyway потащил бы Java-рантайм в Python-образ бота. Абсурдный
   оверхед по размеру и поверхности атаки.
2. **Autogenerate** снимает главную боль текущего ручного процесса: Alembic сравнит
   `database/models.py` с реальной схемой и сгенерит дифф.
3. **Один язык** в репозитории; существующие `op.execute(<raw SQL>)` дружат с уже
   написанными идемпотентными `.sql`-миграциями (можно обернуть как baseline).
4. `alembic>=1.12.0` **уже в** `requirements.txt` — зависимость заявлена, осталось
   сконфигурировать.

Flyway/Liquibase оправданы в polyglot / Java-командах с отдельным DBA-процессом — не наш случай.

## Важные нюансы реализации (выявлено при ресёрче кода)

- **ORM ≠ полная схема.** `models.py` описывает 8 таблиц; реальная схема прода богаче
  (`agent_conversations`, `audit_log`, `user_products`, `user_product_variants`,
  `blood_pressure_logs`, `workouts`, RLS-политики, индексы). Наивный `--autogenerate`
  сгенерит `DROP` для всего, чего нет в `Base.metadata`.
  → **Baseline строим стэмпом существующей схемы (`alembic stamp`), не autogenerate.**
- **RLS-политики** (`add_rls_policies.sql`, `add_rls_biomarkers.sql`) Alembic autogenerate
  не видит → остаются ручными миграциями через `op.execute`.
- Движок **синхронный** (`database/__init__.py: create_engine`) → `env.py` без async-обвязки.
- Накат на прод сейчас ручной (`psql < file.sql`) → интегрировать `alembic upgrade head`
  в деплой/старт контейнера.

## Источники

- [Compare Alembic vs Flyway (2026) — Slashdot](https://slashdot.org/software/comparison/Alembic-DB-vs-Flyway/)
- [Choosing the Right Schema Migration Tool — PingCAP](https://www.pingcap.com/article/choosing-the-right-schema-migration-tool-a-comparative-guide/)
- [Database Migration Tools: Flyway, Liquibase, Alembic — dasroot.net (2026)](https://dasroot.net/posts/2026/04/database-migration-tools-flyway-liquibase-alembic/)
- [Mastering Alembic Migrations in Python — ThinhDA](https://thinhdanggroup.github.io/alembic-python/)
- [Database Migration Tools for Python — vajol/python-data-engineering-resources](https://github.com/vajol/python-data-engineering-resources/blob/main/resources/db-migration.md)
