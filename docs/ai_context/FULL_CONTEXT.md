# HealthVault — Полный контекст проекта для ИИ-ассистента

> Этот файл создан для передачи контекста при смене чата/IDE/ИИ-ассистента.
> Содержит всё необходимое для немедленной продуктивной работы над проектом.
> Дата создания: 2026-03-14

---

## 0. О проекте

**HealthVault** — личная система трекинга здоровья для двух пользователей:
- **Alex Lyskovsky** — Telegram ID `895655`
- **Nika Selezneva** — Telegram ID `485132`

**Репозиторий:** `github.com:Lyskovsky/HealthVault.git`, ветка `main`
**Локальный путь:** `/Users/alexlyskovsky/HealthVault/`

Система состоит из:
1. **Telegram-бота** — трекинг питания, веса, добавок через фото и текст
2. **19 источников данных** — Garmin, Apple Health, Zepp, Netatmo, Chrome History, Screen Time и др.
3. **PostgreSQL на Hetzner** — центральная база данных
4. **~49 скриптов синхронизации** — сбор данных из всех источников

---

## 1. Инфраструктура

- **Сервер:** Hetzner VPS, IP `116.203.213.137`
- **SSH:** `ssh root@116.203.213.137`
- **Docker-контейнеры:** `healthvault_bot`, `healthvault_postgres`
- **Доступ к БД:** `docker exec healthvault_postgres psql -U healthvault -d healthvault`
- **PostgreSQL:** user `healthvault`, db `healthvault`
- **Deploy:** `deploy.sh` — rsync + rebuild Docker + restart
- **Backup:** `scripts/backup_db.sh` → `healthvault_backup_YYYYMMDD_HHMMSS.sql`
- **Диск:** ~53-54% занят (build cache не трогать при уборке)
- **Тесты:** 125 unit + 8 LLM E2E тестов запускаются перед каждым деплоем

### Стек
- Python + **aiogram** (Telegram-бот)
- **PostgreSQL** (основная БД)
- **GPT-4o Vision** / Gemini — распознавание еды
- **Google Vision OCR** — чтение скриншотов весов
- Docker на Hetzner VPS

---

## 2. Структура директорий

```
/Users/alexlyskovsky/HealthVault/
  telegram-bot/
    bot.py                    ← entry point, aiogram Dispatcher
    handlers/
      photo.py                ← обработка фото (еда, весы)
      text.py                 ← текстовые сообщения
      commands.py             ← /start, /help, /day, /week, /vitamins
    middlewares/
      auth.py                 ← whitelist auth, инжектирует user_id
      idempotency.py          ← дедупликация Telegram updates
  core/
    llm_router.py             ← вызов OpenAI/Gemini, ожидает JSON
    llm_food_processor.py     ← нормализует LLM JSON → meal_items/meal_totals
    ocr_weight.py             ← Google Vision OCR для скриншотов Zepp Life
    menu_parser.py            ← парсер фото меню/еды
    product_search.py         ← поиск в локальной БД продуктов
    garmin_data.py            ← чтение данных Garmin для /day
    caloric_budget.py         ← калорийный бюджет (14-дневный avg TDEE)
  services/
    nutrition_service.py      ← дневная статистика: потреблено / цель / остаток
    state.py                  ← in-memory state machine для диалогов
  database/
    models.py                 ← SQLAlchemy models
    crud.py                   ← CRUD операции и агрегации
    repository.py             ← legacy psycopg2 слой
  helpers/
    db_save.py                ← трансформация данных хендлеров → БД
  config/
    users.py                  ← whitelist Telegram ID
  scripts/                    ← ~49 скриптов синхронизации и импорта
    sync_all_data.sh
    download_garmin_data.py
    import_apple_health.py
    import_blood_pressure.py
    import_netatmo.py
    import_activitywatch.py
    import_mac_screentime.py
    import_chrome_history.py
    parse_workouts.py
  tools/
    scaleconnect/             ← SmartScaleConnect + Xiaomi OAuth2 (обновлять ~каждые 30 дней)
  data/
    garmin/{sleep,hrv,stress,body-battery,activities,daily-summary}/
    apple_health_*.json
    activities/{iphone_screentime,mac_screentime,chrome_history,clearspace}
    environment/netatmo_history.json
    blood-tests/              ← PDF анализы
    hormones/                 ← PDF гормоны
    zepp_export_latest.csv
    weights/body_measurements.json
    media/                    ← фото еды из бота
  reports/
    COMPLETE_MEDICAL_DATA.md  ← история анализов с 2014 года
  docs/ai_context/
    01_architecture.md
    02_data_sources.md
    03_database_schema.md
    04_workflows.md
    AI_CHANGELOG.md
    FULL_CONTEXT.md           ← этот файл
```

---

## 3. Архитектура Telegram-бота

### Точка входа
- **`telegram-bot/bot.py`** — загружает `.env`, настраивает логирование в `logs/bot.log`, создаёт `Dispatcher` (aiogram), подключает middleware и routers.

### Middleware
- **`auth.py`** — whitelist-доступ через `config/users.py`, прокидывает `user_id`, `username`, `first_name` в handler data.
- **`idempotency.py`** — дедупликация апдейтов.

### Команды бота
- `/day` — дневная сводка: TDEE × 0.85 целевые калории, прогресс-бары КБЖУ
- `/week` — недельная сводка
- `/vitamins` — лог витаминов и добавок
- `/start`, `/help`

### Поток: фото еды (основной сценарий)
1. Пользователь отправляет фото
2. `ocr_weight.py` проверяет, не скриншот ли это весов Zepp Life
3. Если нет — `menu_parser.py` / GPT-4o Vision распознаёт блюдо → КБЖУ в JSON
4. Бот показывает результат + кнопки **Сохранить / Отмена**
5. На сохранении → запись в `nutrition_log` PostgreSQL + сообщение с бюджетом:

```
✅ Ужин · 620 ккал
Б 45г · Ж 22г · У 58г

📊 🟩🟩🟩🟩🟩🟩🟩⬜⬜⬜ 72%
Сегодня: 1 490 / 1 820 ккал · осталось 330 ккал
```
- 🟩 до 80%, 🟧 от 80%, 🟥 при перерасходе

### Поток: скриншоты весов Zepp Life
- Google Vision OCR → вес, жир%, висцеральный жир, мышцы, вода%, BMR, кости
- Сохраняется в таблицу `weights`

### Калорийный бюджет
- **TDEE** = 14-дневное среднее `total_calories` из `activity_log`
- **Цель** = TDEE × 0.85 (дефицит −15%)

### LLM пайплайн
- **`core/llm_router.py`** — формирует system prompt, вызывает OpenAI/Gemini/Claude, ожидает строго JSON
- **`core/llm_food_processor.py`** — переводит JSON → `meal_items` / `meal_totals`, сверяет с локальной продуктовой базой (`core/product_search.py`)

### Машина состояний
- **`services/state.py`** — простой in-memory `state_manager`
- ⚠️ При пересоздании `UserState` легко потерять поля (например, `menu_data`)

### Слои работы с БД
- **SQLAlchemy** (основной): `database/models.py`, `database/crud.py`
- **psycopg2** (legacy): `database/repository.py` — таблицы `*_logs`, `nutrition_entries`
- ⚠️ Перед изменениями всегда проверяй, какой слой используется в целевом участке кода

---

## 4. База данных — схема

### ⚠️ КРИТИЧЕСКИ ВАЖНО: КБЖУ в JSONB, не в колонках!

```sql
-- ПРАВИЛЬНО:
SELECT (totals->>'calories')::numeric FROM nutrition_log;

-- НЕПРАВИЛЬНО (колонки не существует):
SELECT calories FROM nutrition_log;
```

### Таблица `nutrition_log`
- `id` — Integer PK
- `user_id` — BigInteger FK → `users.telegram_id` (**НЕ** `users.id`!)
- `date` — Date NOT NULL
- `meal_time` — Time
- `meal_name` — String(255)
- `items` — JSONB NOT NULL (список продуктов с детальным КБЖУ)
- `totals` — JSONB NOT NULL → `{"calories": 450.0, "protein": 32.5, "fat": 18.0, "carbs": 41.0}`
- `photo_paths` — Text[]
- `created_at` — TimestampTZ
- Unique: `(user_id, date, meal_time, meal_name)`

### Таблица `weights`
- `weight_kg`, `fat_percent`, `muscle_kg`, `water_percent`
- `body_fat`, `visceral_fat`, `bone_mass`, `bmi`, `bmr`
- `source`: `screenshot_ocr` | `json_import` | `apple_health` | `zepp_life` | `carry_forward`

### Таблица `supplements_log`
- `name` (Vitamin D3, Omega-3, Psyllium, Sterols, Магний…), `dosage`, `source`

### Таблица `activity_log`
- `steps`, `active_calories`, `total_calories`, `distance_km`
- `resting_hr`, `stress_level`, `sleep_hours`
- `hrv` — **ВСЕГДА NULL** (HRV живёт в JSON-файлах, не в БД!)
- `source`: `garmin`

### Таблица `users`
- `telegram_id` (BigInteger, Unique) — FK-цель для других таблиц
- `target_calories`, `target_protein`, `target_fat`, `target_carbs`
- `bmr`, `avg_active_calories` (могут быть NULL)

### Таблицы, которые СУЩЕСТВУЮТ но ПУСТЫЕ
- `sleep_records` — сон только в `data/garmin/sleep/*.json`
- `workouts` — тренировки только в `data/garmin/activities/*.json`
- `blood_tests` — анализы только в PDF + `reports/COMPLETE_MEDICAL_DATA.md`
- `blood_pressure_logs` — давление только в `data/apple_health_blood_pressure.json`

---

## 5. Шпаргалка: откуда брать данные

| Метрика | Источник | Как читать |
|---|---|---|
| 🍽️ Питание (ккал, БЖОУ) | **PostgreSQL** `nutrition_log` | SSH → psql (SQL ниже) |
| ⚖️ Вес (kg, % жира, мышцы) | **PostgreSQL** `weights` | SSH → psql |
| 💊 Добавки | **PostgreSQL** `supplements_log` | SSH → psql |
| 🩺 АД (систола, диастола) | `data/apple_health_blood_pressure.json` | json.load() |
| 👣 Шаги (ежедневные) | `data/apple_health_steps_daily.json` | json.load() |
| 💤 Сон (длительность, фазы) | `data/garmin/sleep/YYYY-MM-DD.json` | glob по дням |
| ❤️ ЧСС покоя, стресс | **PostgreSQL** `activity_log` | SSH → psql |
| 📊 HRV | `data/garmin/hrv/YYYY-MM-DD.json` | `data['hrvSummary']` |
| 🔋 Body Battery | `data/garmin/body-battery/YYYY-MM-DD.json` | `data[0]['charged']` |
| 🌬️ CO₂, темп, влажность | `data/environment/netatmo_history.json` | unix-ts ключи |
| 📱 Экранное время iPhone | `data/activities/iphone_screentime_perapp.json` | `{date: {total_minutes: N}}` |
| 💻 Экранное время Mac | `data/activities/mac_screentime_perapp.json` | аналогично |
| 🌐 Chrome история | `data/activities/chrome_history.json` | `{date: {total_visits: N}}` |
| 🩸 Анализы крови | `reports/COMPLETE_MEDICAL_DATA.md` | читать MD |

### ❌ Критические ошибки — не повторять
- **НЕ ищи локальные JSON с питанием** — их нет. Питание только в PostgreSQL.
- **НЕ ищи `nutrition_log.calories`** — КБЖУ в JSONB `totals->>'calories'`.
- **НЕ читай `activity_log.hrv`** — там NULL. HRV только в `data/garmin/hrv/*.json`.
- **НЕ читай `sleep_records`** — пустая. Сон только в JSON.
- **НЕ читай `workouts`** — пустая. Тренировки только в JSON.

### SQL: питание
```bash
ssh root@116.203.213.137 "docker exec healthvault_postgres psql -U healthvault -d healthvault -c \"
SELECT date,
  ROUND(SUM((totals->>'calories')::numeric), 0) as kcal,
  ROUND(SUM((totals->>'protein')::numeric), 1) as protein,
  ROUND(SUM((totals->>'fat')::numeric), 1) as fat,
  ROUND(SUM((totals->>'carbs')::numeric), 1) as carbs
FROM nutrition_log
WHERE date >= '2026-01-06' AND user_id = 895655
GROUP BY date ORDER BY date;\""
```

### SQL: вес
```bash
ssh root@116.203.213.137 "docker exec healthvault_postgres psql -U healthvault -d healthvault -c \"
SELECT date, AVG(weight_kg) as weight_kg, AVG(fat_percent) as fat_pct
FROM weights WHERE user_id = 895655
GROUP BY date ORDER BY date;\""
```

---

## 6. Все 19 источников данных

### 1. Garmin Connect
- **Что:** сон (фазы, SpO₂, дыхание), HRV, Body Battery, стресс, ЧСС покоя, тренировки, дневная сводка
- **Как:** `garminconnect` → `scripts/download_garmin_data.py`
- **Где:** `data/garmin/{sleep,hrv,stress,body-battery,activities,daily-summary}/*.json`
- **В БД:** `activity_log` (шаги, калории, ЧСС, стресс); HRV и сон только в JSON

### 2. Apple Health
- **Что:** вес, давление, ЧСС, шаги, походка (gait)
- **Как:** ручной XML-экспорт с iPhone → `scripts/import_apple_health.py` (iterparse, ~2.3M записей)
- **Где:** `data/apple_health_*.json`

### 3. Zepp Life / Xiaomi Scale
- **Что:** вес, жир%, мышцы, вода%, BMR, висцеральный жир, кости
- **Каналы:**
  1. Скриншоты → Telegram-бот → `core/ocr_weight.py` (Google Vision OCR)
  2. Полный экспорт → `tools/scaleconnect/` SmartScaleConnect (Xiaomi OAuth2, токен ~каждые 30 дней)
- **Где:** таблица `weights` + `data/zepp_export_latest.csv` (407 измерений с 2020)

### 4. Netatmo
- **Что:** CO₂, температура, влажность (только станция "Большевик"; "Гнездышко" отключена с нояб. 2023)
- **Как:** Netatmo API → `scripts/import_netatmo.py`
- **Где:** `data/environment/netatmo_history.json`

### 5. ActivityWatch + iPhone Biome
- **Что:** экранное время по приложениям (iPhone)
- **Как:** iCloud-синхронизация Biome-файлов → ActivityWatch → `scripts/import_activitywatch.py`
- **Где:** `data/activities/iphone_screentime_perapp.json`
- **Автозапуск:** LaunchAgent в 8:00

### 6. Mac Screen Time
- **Что:** использование приложений на Mac (~30 дней скользящего окна)
- **Как:** прямое чтение SQLite `knowledgeC.db` macOS Screen Time
- **Требует:** Full Disk Access для Terminal
- **Где:** `data/activities/mac_screentime_perapp.json`
- **Автозапуск:** LaunchAgent в 8:00

### 7. Clearspace Screen Time API
- **Что:** общее экранное время iPhone в минутах (не по-приложениям)
- **Как:** REST API Clearspace
- **Где:** `data/activities/clearspace_iphone_screentime.json`

### 8. Chrome History
- **Что:** история браузинга с категоризацией (Work, YouTube, AI tools…), переключения контекста, серфинг перед сном
- **Как:** прямое чтение SQLite `~/Library/Application Support/Google/Chrome/Default/History`
- **Где:** `data/activities/chrome_history.json` (26 383 визита, 84 дня)
- **Автозапуск:** LaunchAgent в 8:00

### 9. Медицинские анализы
- **Что:** кровь + гормоны, история с 2014 года (14 срезов)
- **Где:** `data/blood-tests/*.pdf`, `data/hormones/*.pdf`, `reports/COMPLETE_MEDICAL_DATA.md`
- **Последний:** 7 января 2026 (Invitro): холестерин 5.86, ЛПНП 3.79↑, тест 12.09, vit D 33.5
- **Следующий:** ~апрель 2026

### 10. Шаги (Apple Health, ежедневные)
- **Что:** суммарные шаги/день (Garmin Watch primary, fallback iPhone)
- **Где:** `data/apple_health_steps_daily.json` (4063 дня с 2015)
- **Среднее с 6 янв:** 7 489 шагов/день

### 11. Характеристики ходьбы (Gait)
- **Что:** скорость ходьбы (km/h), длина шага, двойная опора (норма 25-30%), асимметрия (норма <4%)
- **Где:** `data/apple_health_gait.json`
- **Биохакерское значение:** двойная опора >30% → усталость/болезнь; асимметрия >5% → риск травмы

### 12. Артериальное давление
- **Что:** систола/диастола/пульс
- **Где:** `data/apple_health_blood_pressure.json` (141 измерение)

### 13. Тренировки (Garmin JSON)
- **Что:** тип, ЧСС-зоны, лапы, темп
- **Где:** `data/garmin/activities/*.json` (51 тренировка, 24 с 6 января)
- ⚠️ Таблица `workouts` в PostgreSQL пустая

### 14. Сон (фазы, Garmin JSON)
- **Что:** глубокий/REM/лёгкий, дыхание во сне, SpO2
- **Где:** `data/garmin/sleep/YYYY-MM-DD.json`
- **Базовая линия дыхания:** 12.07 ± 0.84 вд/мин; ≥14 = аномалия (болезнь/алкоголь/стресс)
- ⚠️ Таблица `sleep_records` в PostgreSQL пустая

### 15. HRV (Garmin JSON)
- **Где:** `data/garmin/hrv/YYYY-MM-DD.json`, поле `data['hrvSummary']`
- ⚠️ `activity_log.hrv` = NULL, не заполняется

### 16. Body Battery (Garmin JSON)
- **Где:** `data/garmin/body-battery/YYYY-MM-DD.json`, поле `data[0]['charged']`

### 17. Замеры тела (сантиметром)
- **Что:** талия, шея, бёдра, грудь, бицепс, бедро
- **Где:** `data/weights/body_measurements.json` (4 записи: Jan 8, Feb 1, Feb 10, Mar 1)

### 18. Генетика
- **Что:** предрасположенности, риски, происхождение (Atlas Biomed 2009, доп. тест 2016)
- **Где:** `data/genetics/*.pdf`
- **Статус:** архивные, не обновляются

### 19. Алкоголь
- **Что:** флаг употребления (вычисляется из `nutrition_log`)
- **Как:** поиск по ключевым словам (вино, пиво, ром и т.д.) при анализе

---

## 7. Статус данных на 2026-03-09

| Источник | Покрытие | Статус |
|---|---|---|
| Питание (nutrition_log) | 318 записей, 63/63 дней | ✅ |
| Добавки (supplements_log) | 44/63 дней (80%) | ✅ |
| Вес (weights) | 670 записей, 60 с янв | ✅ |
| Сон/HRV/Body Battery (JSON) | 63/63 дней | ✅ (JSON отставал на 8 дней) |
| Шаги | 63/63 дней, среднее 7 489 | ✅ |
| АД | 141 измерение | ✅ |
| Неtatmo климат | 60 суточных записей | ✅ |
| iPhone Screen Time | 29 дней (фев-март) | ✅ |
| Mac Screen Time | 10 дней | ✅ |
| Chrome History | 84 дня, 26 383 визитов | ✅ |
| Анализы крови | 14 срезов 2014-2026 | ⚠️ (план: апрель 2026) |

---

## 8. Известные исправленные баги

1. **`product_search.py`** — алиас без guard длины давал 45 ккал вместо 250 (короткий алиас "черри" матчился с длинным блюдом). Добавлен guard `len(query_significant) > len(alias_significant) + 1`
2. **`db_save.py`** — `create_body_measurement` не экспортировался из `database/__init__.py`
3. **`caloric_budget.py`** — использовал сегодняшние калории вместо 14-дневного среднего
4. **OCR** — `body_fat` и `visceral_fat` перепутаны в 3 записях (Feb 5, Feb 27)
5. **Шаги** — тройной счёт Garmin+iPhone+Zepp → исправлено на Garmin-primary + iPhone fallback
6. **Netatmo** — станция "Гнездышко" фильтруется через `SKIP_STATIONS` (физически удалить через API невозможно)

---

## 9. Стандартные операционные процедуры (SOP)

### Синхронизация данных
Перед анализом всегда обновляй данные:
```bash
bash scripts/sync_all_data.sh
```
Или `/sync` скилл в Claude Code.

Скрипт делает:
1. Синхронизирует PostgreSQL дамп с сервера (питание, добавки, вес)
2. Скачивает свежие данные Garmin
3. Обновляет Netatmo климат
4. Обновляет Screen Time iPhone/Mac/Chrome

### Добавление новой интеграции
1. Создать `scripts/import_X.py`
2. Ключи через `os.getenv()` из `.env`, никогда не хардкодить
3. Данные боту прямо сейчас → PostgreSQL через `database/crud.py`
4. Сырые данные/аналитика → `data/source_name/log_name.json`
5. Добавить в `02_data_sources.md`
6. Записать в `AI_CHANGELOG.md`

### Изменение LLM промптов
- Менять только **системный промпт** в `core/llm_router.py`, не логику
- Проверить локально перед деплоем
- Записать в `AI_CHANGELOG.md`

### Миграция БД
1. Изменить `database/models.py`
2. SQL-скрипт в `database/migrations/` или `ALTER TABLE` напрямую
3. Обновить `03_database_schema.md`
4. Обновить функции в `database/crud.py`

### Запись в AI_CHANGELOG.md
**Обязательно** после каждой завершённой задачи:
```
[YYYY-MM-DD] Описание (затронутые файлы) - Автор (Claude/Cursor/etc)
```

---

## 10. Claude Code скиллы

- **`/sync`** — проверяет свежесть всех 19 источников, запускает Garmin/Zepp/Screen Time, выводит таблицу актуальности
- **`/cleanup`** — удаляет мусор (`__pycache__`, `.pyc`, `.DS_Store`), коммит и пуш в GitHub, бэкап БД на сервере

---

## 11. История ключевых изменений (AI Changelog)

- **2026-03-01** — Создана база знаний `docs/ai_context/` — *Antigravity*
- **2026-03-01** — Настроен Mac Screen Time (`import_screentime.py`, Full Disk Access) — *Antigravity*
- **2026-03-01** — Интеграция Netatmo с Refresh Token авторизацией — *Antigravity*
- **2026-03-01** — Исправлен баг алиасного матча в `product_search.py` — *Claude*
- **2026-03-09** — iPhone Screen Time pipeline: ActivityWatch v0.13.2 + Biome → `iphone_screentime_perapp.json`, LaunchAgent 8:00 — *Claude*
- **2026-03-09** — Mac Screen Time: knowledgeC.db + AW-watcher → `mac_screentime_perapp.json`, LaunchAgent 8:00 — *Claude*
- **2026-03-09** — Chrome History: 26k визитов, 12 категорий, предсонная зона 22-00, контекст-переключения → `chrome_history.json`, LaunchAgent 8:00 — *Claude*
- **2026-03-09** — Netatmo: станция "Гнездышко" исключена через `SKIP_STATIONS` — *Claude*
- **2026-03-09** — Аудит 19 источников, скилл `/sync`, обновлён `sync_all_data.sh` — *Claude*
- **2026-03-09** — Apple Health: шаги (`apple_health_steps_daily.json`) и gait-метрики (`apple_health_gait.json`) — *Claude*
- **2026-03-10** — Исправлена документация схемы: КБЖУ в JSONB `totals`, не отдельных колонках; контейнер `healthvault_postgres` — *Claude*
