# HealthVault — Контекст для Claude Code

> Персональная система трекинга здоровья, питания, спорта и медицинских анализов.
> Владелец: Александр Лысковский, 48 лет, Москва.

## Пользователи бота (NutriLogBot)

| telegram_id | username | Кто |
|---|---|---|
| **895655** | alexlyskovsky | Александр (владелец) — ВСЕГДА фильтровать по этому user_id |
| 485132 | nika_selezneva | Ника (жена) — свои данные |
| 836757955 | Andrey_Pokhodnya | Андрей — свои данные |

**ВАЖНО:** При SQL-запросах к `nutrition_log` и `supplements_log` ВСЕГДА добавлять `WHERE user_id = 895655` для данных Александра. Без фильтра суммируются калории всех пользователей.

## Навигация по проекту

| Файл | Что содержит |
|---|---|
| `HEALTH.md` | Профиль здоровья: вес, анализы, добавки, давление, цели |
| `knowledge_base.json` | Структурированные данные анализов (JSON) — источник истины |
| `KNOWLEDGE_BASE.md` | Человекочитаемый каталог анализов (дублирует JSON для удобства) |
| `todo.md` | Техдолг и роадмап проекта (без личных целей здоровья — они в HEALTH.md) |
| `docs/ai_context/` | Контекст для AI: архитектура, источники данных, схема БД, потоки |

## Данные здоровья — источники и пайплайн

### Автоматические (скрипты тянут сами)

| Метрика | Источник | Файл/таблица | Скрипт |
|---|---|---|---|
| Шаги, дистанция | Garmin API | `data/garmin/daily-summary/YYYY-MM-DD.json` → `stats.totalSteps`, `totalDistanceMeters` | `scripts/garmin/download_garmin_data.py` |
| Пульс покоя, min/max HR | Garmin API | `data/garmin/daily-summary/` → `stats.restingHeartRate` | то же |
| Сон, стресс, HRV, Body Battery | Garmin API | `data/garmin/{sleep,stress,hrv,body-battery}/` | то же |
| Тренировки | Garmin API | `data/garmin/activities/` | то же |
| Вес, жир, висцеральный жир | Zepp API (CN3) | `data/zepp_export_latest.csv` | `scripts/import/zepp_api.py` (токен ~7 дней, reauth через `--code URL`) |
| Воздух дома | Netatmo API | `data/environment/netatmo_history.json` | `scripts/import/netatmo.py` |
| Погода | Open-Meteo | `data/weather/weather_history.json` | `scripts/import/weather.py` |
| Питание, добавки | PostgreSQL (сервер) | таблицы `nutrition_log`, `supplements_log` | `scripts/fetch_remote_nutrition.sh` |
| iPhone Screen Time | ActivityWatch + Biome | `data/activities/iphone_screentime_perapp.json` | `aw-import-screentime` + `scripts/import/activitywatch.py` |
| Mac Screen Time | ActivityWatch | `data/activities/mac_screentime_perapp.json` | `scripts/import/mac_screentime.py` |

### Только через Apple Health Shortcut (ежедневная автоматизация на iPhone)

**Эти метрики недоступны через Garmin/Zepp API — только iPhone/Omron → Apple Health → Shortcuts webhook:**

| Метрика | Источник устройства | Куда пишется |
|---|---|---|
| Давление (систолическое, диастолическое) | Omron → Apple Health | PostgreSQL: `activity_log.raw_data` |
| Походка: скорость, длина шага, асимметрия, двойная опора | iPhone motion sensors → Apple Health | PostgreSQL: `activity_log.raw_data` |

**Shortcut:** `HealthVault_Daily` на iPhone (запускать вручную или по автоматизации)
**Webhook:** `POST https://health.orangegate.cc/apple_health` (Bearer token в `.env`)
**Чтение в дашборде:** SSH → PostgreSQL → `SELECT raw_data FROM activity_log WHERE user_id=895655`

### НЕ используется (устаревшие пути)
- `data/apple_health_heart_rate.json` → заменено на Garmin daily-summary
- `data/apple_health_steps_daily.json` → заменено на Garmin daily-summary
- `data/apple_health_weight*.json` → заменено на Zepp CSV
- Ручной экспорт Apple Health XML → больше не нужен

## Skills (Claude Code)

- `/sync` — обновить все источники данных, показать таблицу актуальности
- `/cleanup` — коммит, пуш, бэкап БД, удаление мусора

## Хранение токенов и секретов

| Что | Где | Примечание |
|---|---|---|
| API-ключи (OpenAI, Gemini, Telegram) | `.env` / `.env.production` | Постоянные, не истекают |
| Пароли (Garmin, Zepp, Netatmo) | `.env` | Для OAuth-потоков |
| OAuth-токены (Zepp, и др.) | `data/cache/tokens.json` | Истекают через 5-7 дней, требуют `--reauth` |
| Netatmo refresh_token | `.env` (`NETATMO_REFRESH_TOKEN`) | Долгоживущий |

`data/cache/` в `.gitignore` — токены не попадают в git.

## Важные правила

- **Язык**: всегда общаться с пользователем на русском
- **AI_CHANGELOG**: после каждой задачи обновлять `docs/ai_context/AI_CHANGELOG.md`
- **Синк перед анализом**: всегда запускать `/sync` перед анализом данных здоровья
- **knowledge_base.json**: при добавлении новых анализов крови — обновлять этот файл
- **Бэкап**: БД на удалённом сервере, не на localhost. Для записи в БД нужен SSH к серверу.

## Правила аналитики и отображения данных

- **Факт vs среднее — не путать.** Когда пишешь «было X → стало Y», X и Y должны быть реальными замерами (первый и последний), а не средними за неделю. Средние за неделю — это отдельная метрика, которую нужно явно подписывать «(средняя за неделю)».
- **Не сглаживать молча.** Любая трансформация данных (усреднение, детренд, фильтрация) должна быть явно указана. Пользователь знает свои цифры — если написать 81.7 вместо реальных 82.75, он заметит и потеряет доверие к анализу.
- **Корреляция ≠ причина.** Два показателя могут коррелировать только потому что оба плавно меняются со временем (тренд). Перед выводами всегда проверять: это связь дневных колебаний (детренд) или ложная корреляция трендов? Пример: «вес падает + температура растёт» → r=−0.49, но после детренда r=+0.19 (ноль). Реальная причина потери веса — питание и тренировки, а не весна.
- **Указывать размер выборки.** Корреляция на 12 днях — предварительная гипотеза. На 70+ днях — устойчивый сигнал. Всегда писать (N дней) рядом с r.
- **Не дублировать числа.** Если число уже есть в одной колонке таблицы (например «29 до 21.03»), не повторять его в другой (например «29 тренировок» в статусе).

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
