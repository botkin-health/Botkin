# HealthVault — Контекст для Claude Code

> Персональная система трекинга здоровья, питания, спорта и медицинских анализов.
> Владелец: Александр Лысковский, 48 лет, Москва.

## Расположение проекта

**Код проекта (эта папка):**
`~/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/Projects/Vibe coding/HealthVault-engine/`

Git remote: `git@github.com:Lyskovsky/HealthVault.git`

**Медицинские данные семьи (отдельная папка, не путать!):**
`~/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/HealthVault/`

Там лежат папки с PDF-анализами и knowledge_base.json каждого. У каждой папки свой CLAUDE.md. Это данные — не код.

Если нужно обратиться к медданным из кода/скриптов — путь:
```python
FAMILY_HEALTH = Path.home() / "Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/HealthVault"
```

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

### sshpass и PATH

`sshpass` установлен в `/opt/homebrew/bin/sshpass`. В subshell-скриптах (bash, Python subprocess) `/opt/homebrew/bin` может отсутствовать в PATH, поэтому **всегда использовать полный путь** во всех скриптах. Все `.sh` и `.py` в `scripts/` уже исправлены. Если добавляешь новый скрипт с `sshpass` — сразу пиши полный путь.

### Zepp reauth — правильный порядок

1. Запустить `scripts/import/zepp_api.py --reauth` → скрипт выведет URL для логина
2. Открыть URL в браузере, залогиниться в Xiaomi
3. Скопировать redirect URL вида `hm.xiaomi.com/watch.do?code=...`
4. Запустить `scripts/import/zepp_api.py --code КОД` (только сам код после `?code=`)
5. Дождаться `✅ Токен получен!` — токен сохранён в `data/cache/tokens.json`
6. **Если после этого упала ошибка** (sshpass, сеть и т.п.) — **не передавать `--code` повторно!**
   OAuth-код одноразовый. Просто запустить `scripts/import/zepp_api.py` без флагов — токен уже в кэше.

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

## Семейное хранилище медицинских данных (FamilyHealth)

**Google Drive — единственный источник истины для медицинских документов всех членов семьи.**

Локальный путь (синхронизируется автоматически):
```
/Users/alexlyskovsky/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/HealthVault/
```

Короткая ссылка в коде: `GD_HEALTH` (задать через переменную окружения или хардкод).

### Структура

```
Google Drive / HealthVault/
├── Александр Лысковский — Здоровье/   # knowledge_base.json (564 значения), PROFILE.md
├── Валерия Лысковская — Здоровье/     # мама, 72 года, серьёзные диагнозы
├── Олег Лысковский — Здоровье/        # сын, 24 года, F21+СДВГ, описторхоз
├── Игорь Лысковский — Здоровье/       # сын, 21 год, аллергия, эозинофилия
├── Екатерина Лысковская — Здоровье/   # бывш. жена, мама Олега и Игоря
└── Ника Селезнева — Здоровье/         # жена, пока без медданных
```

### Правила работы с данными семьи

- **НИКОГДА не путать данные разных людей.** Каждый человек = отдельная папка, отдельный knowledge_base.json
- При вопросе "какой у Олега витамин D" — читать `HealthVault/Олег Лысковский — Здоровье/knowledge_base.json`, НЕ `knowledge_base.json` в корне проекта (там данные Александра)
- knowledge_base.json Александра (`~/HealthVault/knowledge_base.json`) — это данные ТОЛЬКО Александра
- Данные бота (PostgreSQL, nutrition_log) — только Александр (user_id=895655) и Ника (user_id=485132). Олег, Игорь, Катя, Валерия НЕ пользователи бота
- Именование файлов: `{тип}_{YYYY-MM-DD}_{лаборатория}_{подтип}.{ext}`

### Люди и их ключевые проблемы

| Человек | Возраст | Город | Главные проблемы |
|---|---|---|---|
| **Александр** | 48 | Москва | Витамин D ✅, ферритин ↑, LDL колеблется |
| **Валерия** (мама) | 72 | Новосибирск | ⚠️ Холестерин 10.23, NT-proBNP ↑↑, лимфоцитоз ↑↑, менингиома+аденома (МРТ 10 лет назад!) |
| **Олег** (сын) | 24 | Новосибирск | F21+СДВГ, витамин D дефицит 6 лет, описторхоз 2019, выпадение волос, вес ↑ |
| **Игорь** (сын) | 21 | Новосибирск | Витамин D 6.0 (!!!), эозинофилия, аллергия (берёза, кошка, плесень) |
| **Катя** (бывш. жена) | 48 | Новосибирск | Витамин D дефицит, ферритин ↓, магний ↓, цинк ↓, усталость |
| **Ника** (жена) | — | Москва | Данных пока нет |

## Архитектура проекта (код)

```
HealthVault/                     # ~/HealthVault/ — ТОЛЬКО КОД И OPERATIONAL DATA
├── config/                      # Настройки, пользователи
├── core/                        # Бизнес-логика (LLM, питание, парсеры)
├── database/                    # SQLAlchemy модели, CRUD, миграции
├── domain/                      # Доменные модели
├── services/                    # Сервисный слой
├── telegram-bot/                # Aiogram бот (handlers, middlewares)
├── scripts/                     # Импорт данных, анализ, бэкфилл
├── tests/                       # Pytest (unit + LLM prompt тесты)
├── data/                        # Operational data (JSON, CSV, кэш, медиа бота)
│   ├── garmin/                  # Garmin API данные (шаги, сон, HRV)
│   ├── nutrition/               # JSON-логи питания
│   ├── media/                   # Фото еды, голосовые
│   ├── cache/                   # Токены OAuth
│   └── ...                      # НЕ медицинские документы (те на Google Drive)
├── knowledge_base.json          # KB Александра (источник истины для его анализов)
├── docs/                        # Документация + ai_context/
└── archive/                     # Архив старого кода
```
