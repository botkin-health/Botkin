# Тренировки через Health Auto Export (HAE) — формат и интеграция

**Дата:** 2026-06-18
**Статус:** код в dev ([#100](https://github.com/botkin-health/Botkin/issues/100)); живая проверка на сервере/у Ники — pending
**Зачем:** Apple Watch без Garmin (Ника) — нужен ежедневный синк тренировок. Здесь формат `data.workouts[]` от HAE, как Botkin его парсит, и почему «импорт автоматизаций» не помогает.

## Архитектура (коротко)

```
Apple Watch → Apple Health → HAE (iOS) → POST https://health.orangegate.cc/apple_health_v2
   body: {"data": {"workouts": [ {...}, ... ]}}   (отдельный POST, без data.metrics)
Сервер: webhook/apple_health.py
   _hae_workouts_to_rows() → _insert_new_workouts() → таблица workouts (дедуп по source)
```

Тренировки HAE шлёт **отдельной автоматизацией** (тип Workouts) → отдельный POST с `data.workouts[]`.
Метрики (шаги/пульс/вес) идут другой автоматизацией с `data.metrics[]`. Один и тот же эндпоинт
`/apple_health_v2` обрабатывает оба (workouts-only POST тоже валиден — ранний `return` это учитывает).

## Формат `data.workouts[]`

⚠️ **Две схемы.** Вики HAE (v2) и пример из issue #100 расходятся — парсер поддерживает обе.
Источник: [HAE Wiki — API Export JSON Format](https://github.com/Lybron/health-auto-export/wiki/API-Export---JSON-Format).

| Поле | Вики HAE (v2) | Пример issue | Парсинг в Botkin |
|---|---|---|---|
| тип активности | `name` (String) | `workoutActivityType` (`HKWorkoutActivityType*`) | `_hae_workout_type`: предпочесть `workoutActivityType` (снять префикс `HKWorkoutActivityType`), иначе `name`, иначе `"Workout"` |
| старт/конец | `start`/`end` | `startDate`/`endDate` | формат `%Y-%m-%d %H:%M:%S %z` (напр. `2026-06-14 08:00:00 +0300`); без распознанной даты старта запись **пропускается** |
| длительность | `duration` (число, **секунды**) | `duration` `{qty, units: "min"}` | `_hae_workout_duration_min`: dict с `units=min/h` → как есть; голое число → секунды/60 |
| дистанция | `distance` `{qty, units: "mi"\|"km"}` | то же | `_hae_workout_distance_km`: мили → км (×1.60934), иначе как есть |
| энергия | `activeEnergyBurned`/`totalEnergy` `{qty,units}` | `activeEnergy` `{qty}` | `_hae_workout_calories`: первый из `activeEnergyBurned`/`activeEnergy`/`totalEnergy` |
| идентификатор | `id` (String) | — | `source = hae_<id>`; без `id` → `hae_<start ISO>` (детерминированный, для дедупа) |

Вложенные величины — всегда `{"qty": <число>, "units": <строка>}` (хелпер `_hae_quantity` достаёт `qty` либо само число).

## Запись и дедуп

Таблица `workouts`: `user_id, date, workout_type, duration_minutes, start_time, end_time, calories_burned, distance_km, source`.

- Garmin-путь (`server_backfill_postgres.py`) дедупит **по дате** (1 трен./день). HAE может слать **несколько тренировок за день**, поэтому HAE-путь дедупит **по `source`** на уровне приложения (`_insert_new_workouts`: предвыборка существующих `source`, пропуск дублей + дедуп внутри батча).
- Миграцию схемы (уникальный индекс на `source`) **не делали** — дедуп приложением достаточен и не требует SSH/Alembic. Если позже захочется БД-гарантию — добавить `UNIQUE(user_id, source)` отдельной миграцией.

## «Импорт автоматизаций» в HAE — НЕ поддерживается

Идея из issue (сгенерировать пользователю готовый конфиг-файл для импорта в один тап) **нереализуема**.
По [докам HAE — Automations](https://help.healthyapps.dev/en/health-auto-export/automations/) (проверено 2026-06-18):

- Есть только **iCloud backup/restore** автоматизаций (папка `Auto Export/Automations`, JSON), привязанный к устройству/iCloud конкретного пользователя.
- **Нет** экспорта/импорта конфигов как шэрабельных файлов, нет шаблонов с пред-заполнением URL/токена.
- Токены внешних сервисов в бэкап **не входят** (приватность).

**Вывод:** автоматизацию каждый пользователь настраивает вручную (см. ниже). One-tap онбординг через файл HAE невозможен; для grandma-proof пути нужен нативный мини-апп (отдельная задача роадмапа), не HAE-импорт.

## Настройка у пользователя (ручная) — для Ники

Вторая автоматизация в HAE, в дополнение к существующей (Health Metrics):

1. HAE → Automations → **+** (новая).
2. Тип: **REST API**, формат **JSON**, версия **v2**.
3. URL: `https://health.orangegate.cc/apple_health_v2`, заголовок `Authorization: Bearer <персональный health_token>`.
4. **Data type: Workouts** (не Health Metrics).
5. Date Range: **Yesterday**, Aggregate/Group: по дню, частота 1/день.
6. Проверка: «Ручной экспорт» за пару дней → ответ `200 {"workouts_inserted": N}`.

## Pending / проверка

- **Реальный сэмпл `data.workouts[]`** на 2026-06-18 не получен — парсер построен по вики+issue (защитно под обе схемы). После получения сэмпла от владельца HAE — сверить поля.
- Живая проверка «тренировка с Apple Watch → строка в `workouts`» — на сервере (нужен SSH) либо прогоном `/PR_test` после релиза.
