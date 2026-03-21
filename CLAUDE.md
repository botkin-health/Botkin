# HealthVault — Контекст для Claude Code

> Персональная система трекинга здоровья, питания, спорта и медицинских анализов.
> Владелец: Александр Лысковский, 48 лет, Москва.

## Навигация по проекту

| Файл | Что содержит |
|---|---|
| `HEALTH.md` | Профиль здоровья: вес, анализы, добавки, давление, цели |
| `knowledge_base.json` | Структурированные данные анализов (JSON) — источник истины |
| `KNOWLEDGE_BASE.md` | Человекочитаемый каталог анализов (дублирует JSON для удобства) |
| `todo.md` | Техдолг и роадмап проекта (без личных целей здоровья — они в HEALTH.md) |
| `docs/ai_context/` | Контекст для AI: архитектура, источники данных, схема БД, потоки |

## Данные здоровья

| Источник | Файлы | Актуализация |
|---|---|---|
| Apple Health | `data/apple_health_*.json` | Ручной экспорт с iPhone → `scripts/import_apple_health.py` |
| Zepp Life (весы) | `data/zepp_export_latest.csv` | `scripts/import_zepp_api.py --reauth` (OAuth2) |
| Garmin | `data/garmin/` | `scripts/garmin/download_garmin_data.py` |
| Замеры тела | `data/weights/body_measurements.json` | Вручную, ~раз в неделю |
| Анализы крови | `data/blood-tests/*.pdf` + `knowledge_base.json` | После каждого визита в лабораторию |
| Netatmo | `data/environment/` | `scripts/import_netatmo.py` |
| Погода | `data/weather/` | `scripts/import_weather.py` |

## Skills (Claude Code)

- `/sync` — обновить все источники данных, показать таблицу актуальности
- `/cleanup` — коммит, пуш, бэкап БД, удаление мусора

## Важные правила

- **Язык**: всегда общаться с пользователем на русском
- **AI_CHANGELOG**: после каждой задачи обновлять `docs/ai_context/AI_CHANGELOG.md`
- **Синк перед анализом**: всегда запускать `/sync` перед анализом данных здоровья
- **knowledge_base.json**: при добавлении новых анализов крови — обновлять этот файл
- **Бэкап**: БД на удалённом сервере, не на localhost. Для записи в БД нужен SSH к серверу.

## Архитектура

```
HealthVault/
├── config/          # Настройки, пользователи
├── core/            # Бизнес-логика (LLM, питание, парсеры)
├── database/        # SQLAlchemy модели, CRUD, миграции
├── domain/          # Доменные модели
├── services/        # Сервисный слой
├── telegram-bot/    # Aiogram бот (handlers, middlewares)
├── scripts/         # Импорт данных, анализ, бэкфилл
├── tests/           # Pytest (unit + LLM prompt тесты)
├── data/            # Все данные (JSON, CSV, PDF, медиа)
├── docs/            # Документация + ai_context/
└── archive/         # Архив старого кода
```
