# Botkin (ex-HealthVault) — Контекст для Claude Code

> Персональная система трекинга здоровья, питания, спорта и медицинских анализов.
> Владелец: Александр Лысковский, 48 лет, Москва.

## Расположение проекта

**Код проекта (эта папка):**
`~/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/Projects/Vibe coding/Botkin/`

Git remote: `git@github.com:Lyskovsky/Botkin.git` (переименовано 12.05.2026, было `HealthVault`)

**Медицинские данные семьи (отдельная папка, не путать!):**
`~/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/FamilyHealth/`

Там лежат папки с PDF-анализами и knowledge_base.json каждого. У каждой папки свой CLAUDE.md. Это данные — не код.

Если нужно обратиться к медданным из кода/скриптов — путь:
```python
FAMILY_HEALTH = Path.home() / "Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/FamilyHealth"
```

## Пользователи бота (Botkin)

⚠️ **ВНИМАНИЕ — миграция бота (12.05.2026):**
- **Активный бот:** `@Botkin_md_bot` (display name «Botkin», bot_id 8739688481)
- **Прямая ссылка для пользователей:** **t.me/Botkin_md_bot**
- **Старый бот `@HealthVault_bot`** (bot_id 8500310863) — архив, webhook удалён. Истории чатов у юзеров сохраняются, но новые сообщения не обрабатываются.

`@NutriLogBot` БЕЗ префикса — это **чужой украинский бот-двойник**, не наш. Не давать пользователям ссылку `t.me/NutriLogBot`.

Telegram ID и личные данные пользователей — в `~/.claude/CLAUDE.md` (приватный, не в git).

**ВАЖНО:** При SQL-запросах к `nutrition_log` и `supplements_log` ВСЕГДА добавлять `WHERE user_id = 895655` для данных владельца. Без фильтра суммируются калории всех пользователей.

## Навигация по проекту

| Файл | Что содержит |
|---|---|
| `HEALTH.md` | Профиль здоровья: вес, анализы, добавки, давление, цели |
| `knowledge_base.json` | Структурированные данные анализов (JSON) — источник истины |
| `KNOWLEDGE_BASE.md` | Человекочитаемый каталог анализов (дублирует JSON для удобства) |
| `todo.md` | Техдолг и роадмап проекта (без личных целей здоровья — они в HEALTH.md) |
| `docs/ai_context/` | Контекст для AI. **Начни с `README.md`** — там навигация. 01 архитектура · 02 источники данных · 03 схема БД · 04 workflows · 05 помощь с едой · `AI_CHANGELOG.md` |

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

### Ежедневный автоэкспорт через Health Auto Export (iOS)

**С мая 2026 — основной канал для всех Apple Health метрик.** Заменяет старый Shortcut, который был ненадёжный (требовал ручного запуска и часто падал на ошибках). Ставится один раз, дальше работает в фоне без участия пользователя.

**Метрики, которые приходят через этот канал** (все с iPhone/Apple Watch/Omron/Mi-весов через Apple Health):

| Метрика | Куда пишется |
|---|---|
| Шаги, дистанция ходьбы, активные ккал, этажи | `activity_log` (steps, distance_km, active_calories) |
| Пульс (avg/min/max), пульс покоя | `activity_log` + `raw_data` |
| Давление систолическое/диастолическое (Omron) | `blood_pressure_logs` |
| Походка: скорость, длина шага, двойная опора, асимметрия | `activity_log.raw_data` |
| Вес, % жира, мышечная масса (Mi-весы → Apple Health) | `weights` |
| VO2 Max, частота дыхания, температура запястья | `activity_log.raw_data` |

**Стек:**
- **iOS-приложение:** [Health Auto Export – JSON+CSV](https://apps.apple.com/app/health-auto-export-json-csv/id1115567069) (Lybron Sobers, $24.99 lifetime)
- **Webhook:** `POST https://health.orangegate.cc/apple_health_v2` (Bearer token из `.env: APPLE_HEALTH_TOKEN`)
- **Серверный адаптер:** `telegram-bot/webhook/apple_health.py` — функция `_hae_to_daily_payloads()` парсит формат `data.metrics[]`, группирует по дням, упсертит в БД

**Настройки в HAE (важные):**
- Тип: REST API · Формат: JSON · Версия: v2 · Диапазон: «Вчера» · Суммировать: ON · Группировка: «День» · Частота: 1 / Дни
- Header: `Authorization: Bearer <APPLE_HEALTH_TOKEN>`
- 17 метрик выбрано (см. таблицу выше)

**Когда срабатывает:** iOS-планировщик решает сам (~1 раз в сутки, обычно ночью когда iPhone на зарядке). Точное время не задаётся — разброс ±1-2 часа. Требования: iPhone разблокирован, Background App Refresh для HAE включён, Low Power Mode выключен.

**Ручной экспорт:** в HAE → автоматизация HealthVault → внизу зелёная кнопка «Ручной экспорт» → выбрать диапазон → POST уйдёт сразу. Полезно для проверки свежей тренировки/замера на дашборде, не дожидаясь ночного автозапуска.

**Старый endpoint `/apple_health` (v1)** — оставлен для обратной совместимости со старыми Shortcuts (если их ещё кто-то использует). Принимает плоский JSON. Рабочий, но новые автоматизации делать на v2.

**Документация HAE:**
- [Help Center — REST API automation](https://help.healthyapps.dev/en/health-auto-export/automations/rest-api/)
- [GitHub: Lybron/health-auto-export](https://github.com/Lybron/health-auto-export) — спецификация JSON формата
- [Wiki: API Export JSON Format](https://github.com/Lybron/health-auto-export/wiki/API-Export---JSON-Format) — структура `data.metrics[]`

### Apple Health XML экспорт (ручной, редко)

Когда пользователь делает Health → Export All Health Data и присылает zip (`экспорт.zip`), распаковываем и запускаем парсер:

```bash
# 1. Распаковать zip в /tmp/apple_health/apple_health_export/
# 2. Запустить парсер (путь к XML захардкожен — поправить при необходимости)
python3 scripts/import/parse_apple_health_xml.py
# 3. Удалить сырой XML — он 700 МБ+
```

Это обновляет **плоские файлы, которые читают `/sync` и `/dashboard`**:
- `data/apple_health_blood_pressure.json` → `measurements[{date, time, systolic, diastolic}]` — история АД с 2018
- `data/apple_health_heart_rate.json` → `measurements[{date, avg, min, max, n}]` — дневная агрегация пульса
- `data/apple_health_steps_daily.json` → `steps_by_day[{date, steps}]` — шаги с 2015
- `data/apple_health_gait.json` → `gait_by_day[{date, speed_km_h, step_length_cm, double_support_pct, asymmetry_pct}]` — походка с 2020
- `data/apple_health_weight_daily.json` + `apple_health_weight.json` — вес с 2015

**ВАЖНО:** эти файлы НЕ устарели. /sync читает их, /dashboard тоже. Каждый раз когда приходит новый Apple Health экспорт — перезаписываем их через `regen_flat_files.py` и удаляем сырой XML (он 700 МБ+).

### Apple Health — исторический архив (не читается автоматически)

Дополнительно из того же XML-экспорта вытащены данные, которых нет в боте/Garmin/Zepp:

- **`data/apple_health/workouts.json`** — 502 тренировки за 11 лет (2015–2026), поля: `type`, `duration`, `distance`, `energy`, `start`, `source`. Использовать когда нужно посмотреть долгосрочную динамику спорта ("сколько HIIT в 2022 vs 2026", "пробежки до 2020").
- **`data/apple_health/daily_metrics.json`** — 16 дополнительных метрик с дневной агрегацией: SpO2, активные ккал, этажи, температура тела, плавание, громкость наушников и т.д. Покрытие: см. файл.
- **`data/apple_health/types_summary.json`** — каталог всех 31 типов записей из последнего экспорта с диапазонами дат (метадата, для справки).

Эти файлы НЕ читают `/sync` и `/dashboard` — они лежат как архив. Если пользователь спросит что-то из истории ("тренировки за 2017", "плавание в 2024") — читаем напрямую через `Read`/`python3`.

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
- **knowledge_base.json**: при добавлении новых анализов/УЗИ/МРТ/ЭКГ — обновлять этот файл
- **Бэкап**: БД на удалённом сервере, не на localhost. Для записи в БД нужен SSH к серверу.

## Протокол чтения медданных (КРИТИЧНО)

**При ЛЮБОМ вопросе о здоровье Александра (или члена семьи) — порядок чтения строго такой:**

1. **`PROFILE.md`** в папке человека (`FamilyHealth/{Имя} — Здоровье/PROFILE.md`):
   - **Сначала «🩺 Журнал обследований»** (между маркерами `<!-- EXAM_JOURNAL_START -->...END -->`) — это автогенерируемый индекс **что и когда** обследовалось. Никогда не предлагать сделать обследование, не сверившись с журналом.
   - Затем основная часть — карта диагнозов и хронических состояний.
2. **`knowledge_base.json`** в той же папке — детали из журнала. Секции:
   - `blood_tests`, `urine_tests`, `hormones`, `vitamins`, `genetics` — лабораторные
   - `ultrasound` — УЗИ (все типы: ОБП, почки, простата, щитовидка, ЭхоКГ, БЦА, малый таз, молочные)
   - `medical_records` — **приёмы врачей часто содержат embedded summary с ЭКГ/ЭхоКГ/УЗДГ/ЭГДС/колоноскопией** (например, 2021-03-01 atlas_therapist — там весь комплекс Атласа)
   - `ecg`, `spirometry`, `sports_tests` — функциональные тесты
3. **Только после этого** — читать отдельные PDF/docx для деталей, которых нет в JSON.

**Если добавили новые анализы/УЗИ в `knowledge_base.json` — обязательно регенерировать журнал:**
```bash
python3 scripts/generate_exam_journal.py "Имя — Здоровье" --update-profile
```

**Главные ошибки прошлого** (не повторять!):
- ❌ Игнорировать `medical_records.summary` — там часто весь комплекс приёма (УЗИ + ЭКГ + ЭхоКГ).
- ❌ Цитировать прозу из HEALTH.md/PROFILE.md как «снимок состояния» — она может устаревать. JSON и журнал обследований — единственный источник истины.
- ❌ Предлагать сделать ЭКГ/УЗИ ОБП/колоноскопию, не глянув в журнал — там может быть свежее. **Прецедент 09.05.2026:** AI забыл про УЗИ ОБП в МЕДСИ от 19.04.2026 и предложил сделать его «впервые с 2021».

**Никаких параллельных md-черновиков к обследованиям.** Развёрнутая интерпретация — в `knowledge_base.json` в полях `summary`/`conclusion`/`recommendations`. JSON — единственный источник истины, PDF/docx — архив оригиналов.

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
/Users/alexlyskovsky/Library/CloudStorage/GoogleDrive-lyskovsky@gmail.com/Мой диск/FamilyHealth/
```

Короткая ссылка в коде: `GD_HEALTH` (задать через переменную окружения или хардкод).

### Структура

Папки по каждому члену семьи — см. `~/.claude/CLAUDE.md` (имена, возраст, диагнозы там).

### Правила работы с данными семьи

- **НИКОГДА не путать данные разных людей.** Каждый человек = отдельная папка, отдельный knowledge_base.json
- Каждая папка содержит `PROFILE.md` (диагнозы) и `knowledge_base.json` (все обследования)
- knowledge_base.json в корне проекта — данные ТОЛЬКО владельца (Александра)
- Данные бота (PostgreSQL) — только пользователи бота (см. `~/.claude/CLAUDE.md`)
- Именование файлов: `{тип}_{YYYY-MM-DD}_{лаборатория}_{подтип}.{ext}`

## Архитектура проекта (код)

```
Botkin/                          # ~/Botkin/ — ТОЛЬКО КОД И OPERATIONAL DATA
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
