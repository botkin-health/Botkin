# 06 · Данные здоровья — источники и пайплайн

> Перенесено из корневого `CLAUDE.md` 23.09.2026 дословно: раздел справочный и нужен не в каждой задаче,
> а CLAUDE.md целиком загружается в каждую сессию Claude Code. Источник истины по этой теме — этот файл.


### 🩸 Анализы (KB) — 2-source pipeline + read-time канонизация (унифицировано 01.06.2026)

Источник истины — `~/FamilyHealth/<Имя>/knowledge_base.json` **на маке**. На сервере биомаркеры живут в **двух местах**, и канонизация ключей происходит **на чтении** через `core/health/kb_schema.py` (единый реестр алиасов + конверсия единиц с guard + US→метрика по признаку `_unit_system`):

В Postgres `blood_tests` импортируются KB-секции `blood_tests`/`biochemistry`/`hormones`/`vitamins` (`_extract_rows`). Записи в US-единицах (KB-поле `"units"` содержит `mg/dl`/`g/dl`) получают служебный ключ `_unit_system="US"` в JSONB `values` — `to_canonical` по нему конвертирует g/dL·mg/dL·µg/dL в метрику на чтении (таблица `US_TO_METRIC`).

| Канал на сервере | Кто читает | Формат | Как туда попадают данные |
|---|---|---|---|
| PostgreSQL `blood_tests` (сырые `values`) | **дашборд** (`dashboard_generator._load_biomarkers_from_db` → `aggregate_biomarkers`) **и агент** (`/recent_biomarkers`, `/phenoage`) | канонизируется на лету `to_canonical` | `scripts/import/kb_to_blood_tests.py` **и** `/doc` в боте (см. ниже) |
| `/app/data/kb/kb_<id>.json` (bind-mount) | агент (`/kb_value`, `/list_kb_keys`) | сырой полный KB | `scripts/sync_family_kb.py --apply` |

Дашборд **больше не читает файл** `biomarkers_<id>.json` — он берёт биомаркеры из Postgres (durable, не теряются при rebuild контейнера — раньше у 4 family-юзеров дашборды пустели после деплоя). Legacy-fallback `BOTKIN_LEGACY_BIOMARKERS_JSON` удалён 11.06.2026 (аудит): флаг нигде не включался.

**Третий писатель — `/doc` в боте (#281, 25.07.2026).** Когда пользователь сам грузит анализ через `/doc` и жмёт «Сохранить», `handlers/doc_upload._save_to_blood_tests` пишет показатели прямо в `blood_tests` (маппер `core/health/doc_to_blood_test.py` → `crud.upsert_blood_test`), минуя мак и `sync_user_health`. Правила те же: сырые ключи, канонизация на чтении. Ключ идемпотентности — `(user_id, test_date, test_type)`, где `test_type` = `«<лаборатория> · <8hex контент-хэша файла>»`. Нелабораторные документы (УЗИ, заключения) в `blood_tests` не попадают — их отсекает гейт `to_canonical`; они остаются в `documents[]`. Нет даты в документе — строки нет (дату не выдумываем).

**Что отдаёт экстрактор `/doc` (ADR-0010, #558, 25.09.2026).** `core/health/doc_extractor.py` (модель — `config/models.py::DOC_EXTRACT_MODEL`, Sonnet 5) возвращает помимо `date`/`laboratory`/`values`/`allergies`/`conditions`: `date_label` (подпись у даты; берётся дата взятия/приёма, не печати — иначе `date=null` и `_date_rejected`), `doc_kind` (`lab_panel`/`imaging`/`smear_pcr`/`doctor_note`/`other`), `doc_type` (название документа — его читают превью и `list_documents`), `summary` (качественные результаты и заключение; у `lab_panel` — всегда `null`, оценкам модели «в норме» доверять нельзя), `units` (единицы по ключам; СРБ мг/дл → мг/л пересчитывается, `_unit_conversions`). У `smear_pcr` числа отбрасываются (`_dropped_values`), коды Z убираются из `conditions` (`_dropped_conditions`), строка в `blood_tests` не пишется для `smear_pcr`/`other`. Активный B12 — отдельный канонический `holotranscobalamin`. Сводная таблица за несколько дат (досье, «в динамике») отдаётся полем `series` — записи `{date, laboratory, values}`, верхние `date`/`values` пусты; в `blood_tests` уходит строка на каждую дату (`build_blood_test_rows`), длинный текстовый PDF разбирается по частям (#559). Повторную фотографию уже сохранённого бланка превью помечает предупреждением (`core/health/doc_duplicates.py`). Правила после ответа модели и свойства типов документа — `core/health/doc_normalize.py` (`normalize_extracted`, `KINDS`, #561); переприменить к сохранённым документам без модели — `scripts/renormalize_documents.py` (сухой прогон). Качество меряется `scripts/eval/doc_extractor_eval.py` (эталон — только на сервере, `data/eval/doc/`).

⚠️ **Следствие:** данные от `/doc` живут только на сервере, в локальном `~/FamilyHealth/<юзер>/knowledge_base.json` их нет. `sync_user_health` их **не затрёт** (upsert без DELETE), но и не подтянет обратно на мак. Если нужно свести — переносить в локальный KB руками.

**Когда добавил новый анализ в KB → одна команда для ЛЮБОГО юзера:**
```bash
python3 scripts/sync_user_health.py --user <telegram_id> --apply   # или --all
```
Две идемпотентные стадии: KB → bind-mount `kb_<id>.json` + KB → Postgres `blood_tests`. Маппинг `telegram_id → папка` — в `config/users.py::KB_USERS` (единый, не дублировать).

⚠️ `sync_user_health` льёт из **локального** KB. Если у юзера на сервере данные богаче локального (прецедент: KB Андрея беднее его старого дашборда) — сперва дополнить локальный `knowledge_base.json`, иначе перезатрёшь.

**Прецеденты:** 24.05.2026 — забывали стадии синка (теперь одна команда). 01.06.2026 — унификация: 3 формата ключей (`LDL`/`ldl`/`ldl_mmol_l`) и битый ad-hoc файл Димы (сырые pmol/L под каноническими именами) → единый `kb_schema` с конверсией единиц. 16.06.2026 (#95) — секция `biochemistry` вообще не импортировалась → phenoage не видел альбумин/железо/ALKP; плюс панель Маккаби в US-единицах писалась без конверсии (молча неверный bio_age). Фикс: импорт `biochemistry` + признак `_unit_system` + конверсия US→метрика на чтении + алиас `ALKP`→`ALP`.

**Follow-up:** консолидировать `core/reports/biomarker_dynamics.py::MARKER_CONFIG` (4-й case-sensitive маппинг) на `kb_schema`.

### Автоматические (скрипты тянут сами)

| Метрика | Источник | Файл/таблица | Скрипт |
|---|---|---|---|
| Шаги, дистанция | Garmin API | `data/garmin/daily-summary/YYYY-MM-DD.json` → `stats.totalSteps`, `totalDistanceMeters` | `scripts/garmin/download_garmin_data.py` |
| Пульс покоя, min/max HR | Garmin API | `data/garmin/daily-summary/` → `stats.restingHeartRate` | то же |
| Сон, стресс, HRV, Body Battery | Garmin API | `data/garmin/{sleep,stress,hrv,body-battery}/` | то же |
| Тренировки | Garmin API | `data/garmin/activities/` | то же |
| Вес, жир, висцеральный жир | Zepp API (CN3) | `data/zepp_export_latest.csv` | `scripts/import/zepp_api.py` (токен ~7 дней, reauth через `--code URL`) |
| Вес + ПОЛНЫЙ состав тела (мышцы, вода, кости, висцеральный жир) | Withings API (весы Body Smart) | таблица `weights` (`source='withings'`) | `scripts/import/withings_api.py --user <tg_id> --push-api --min-weight <кг>` (пишет через `POST /api/agent/log_body_composition` с `BOTKIN_PAT`, доступ к серверу не нужен). Нужен, потому что **в HealthKit нет типов** для мышечной массы/воды/костной массы/висцерального жира — через HAE доходят только вес, % жира и безжировая масса. Апсерт с COALESCE (канал HAE не перетирается). Креды `WITHINGS_CLIENT_ID/SECRET/REFRESH_TOKEN`; refresh **ротируется** → `data/cache/withings_tokens.json` |
| ↳ *канал записи для внешних весов* | — | таблица `weights` | `POST /api/agent/log_body_composition` (PAT+JWT, scope `rw`). **Предпочтительный путь** для импортёров с чужой машины: `user_id` берётся из токена, RLS изолирует данные, доступ к прод-серверу и суперюзер Postgres не нужны. `measured_at` обязан нести офсет (это ключ идемпотентности), `source` — имя канала; `manual`/`llm_text` зарезервированы за ручным вводом (#170). Заменяет схему «ssh + `docker exec psql`» из `zepp_csv.py`, которая требует членства в docker-группе = root на хосте |
| Воздух дома | Netatmo API | `data/environment/netatmo_history.json` | `scripts/import/netatmo.py` |
| Погода | Open-Meteo | `data/weather/weather_history.json` | `scripts/import/weather.py` |
| Глюкоза (CGM) | LibreLinkUp API (Abbott FreeStyle Libre 3) | таблица `glucose_readings` (mmol/L) | `scripts/import/librelinkup.py` (follower `dr@botkin.health`, регион EU; маппинг `cgm_connections`; онбординг `/connect_cgm`) |
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

**Тренировки** приходят **отдельным POST** `data.workouts[]` (своя автоматизация HAE типа Workouts, не Health Metrics) → таблица `workouts`, дедуп по `source=hae_<id>`. Парсинг в `webhook/apple_health.py` (`_hae_workouts_to_rows`/`_insert_new_workouts`). Формат, грабли и ручная настройка — [docs/researches/2026-06-18-hae-workouts.md](docs/researches/2026-06-18-hae-workouts.md) (#100). HAE не умеет шэрить конфиги автоматизаций — настройка только ручная.

**Стек:**
- **iOS-приложение:** [Health Auto Export – JSON+CSV](https://apps.apple.com/app/health-auto-export-json-csv/id1115567069) (Lybron Sobers, $24.99 lifetime)
- **Webhook:** `POST https://health.orangegate.cc/apple_health_v2` (Bearer token из `.env: APPLE_HEALTH_TOKEN`)
- **Серверный адаптер:** `telegram-bot/webhook/apple_health.py` — функция `_hae_to_daily_payloads()` парсит формат `data.metrics[]`, группирует по дням, упсертит в БД

**Настройки в HAE (важные):**
- Тип: REST API · Формат: JSON · Версия: v2 · Диапазон: «Вчера» · Суммировать: ON · Группировка: «День» · Частота: 1 / Дни
- Header: `Authorization: Bearer <APPLE_HEALTH_TOKEN>`
- 17 метрик выбрано (см. таблицу выше)

**Когда срабатывает:** iOS-планировщик решает сам (~1 раз в сутки, обычно ночью когда iPhone на зарядке). Точное время не задаётся — разброс ±1-2 часа. Требования: iPhone разблокирован, Background App Refresh для HAE включён, Low Power Mode выключен.

**Ручной экспорт:** в HAE → автоматизация Botkin (на iPhone может ещё называться «HealthVault» если не переименовали в HAE-приложении — переименовать) → внизу зелёная кнопка «Ручной экспорт» → выбрать диапазон → POST уйдёт сразу. Полезно для проверки свежей тренировки/замера на дашборде, не дожидаясь ночного автозапуска.

**Endpoint `/apple_health` (v1)** — поддерживаемый канал **бесплатного пути через iOS Shortcuts** (iCloud-шаблон из `docs/user_guide/ru/apple-health.md`, per-user токены `hvt_`). Принимает плоский JSON. Это не legacy: HAE v2 — надёжный платный путь, Shortcut v1 — официальный бесплатный (требует ручного/автоматизированного запуска Shortcut).

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
- `data/apple_health_steps_daily.json` → `steps_by_day[{date, steps, primary_source}]` — шаги с 2015 (см. ⚠️ ниже)
- `data/apple_health_steps_by_source.json` → `by_day[{date, primary, primary_steps, all_sources}]` — разбивка шагов по источникам (для аудита/дебага)
- `data/apple_health_gait.json` → `gait_by_day[{date, speed_km_h, step_length_cm, double_support_pct, asymmetry_pct}]` — походка с 2020
- `data/apple_health_weight_daily.json` + `apple_health_weight.json` — вес с 2015

**ВАЖНО:** эти файлы НЕ устарели. /sync читает их, /dashboard тоже. Каждый раз когда приходит новый Apple Health экспорт — перезаписываем их через `scripts/import/parse_apple_health_xml.py` и удаляем сырой XML (он 700 МБ+).

⚠️ **Текущий `apple_health_steps_daily.json` ЗАДВОЕН для 2023+** (баг старого парсера: суммировал все sourceName без дедупликации; в 2026 даёт ≈ ×2.57 от Garmin). Парсер починен 14.05.2026 — теперь выбирает один primary-источник по приоритету `Garmin → Apple Watch → iPhone → fallback-max`. Чтобы исправить flat-файлы — нужен **свежий экспорт Apple Health XML** (Health → Профиль → Экспорт всех данных) и повторный запуск `parse_apple_health_xml.py`. Сравнить можно через новый `apple_health_steps_by_source.json` (там видны все источники за день). Для аналитики **2023+ года** до этого момента — использовать **только** Garmin `data/garmin/daily-summary/`, а не AH-flat. История **до 2022** в файле корректна (тогда был фактически один источник).

### Apple Health — исторический архив (не читается автоматически)

Дополнительно из того же XML-экспорта вытащены данные, которых нет в боте/Garmin/Zepp:

- **`data/apple_health/workouts.json`** — 502 тренировки за 11 лет (2015–2026), поля: `type`, `duration`, `distance`, `energy`, `start`, `source`. Использовать когда нужно посмотреть долгосрочную динамику спорта ("сколько HIIT в 2022 vs 2026", "пробежки до 2020").
- **`data/apple_health/daily_metrics.json`** — 16 дополнительных метрик с дневной агрегацией: SpO2, активные ккал, этажи, температура тела, плавание, громкость наушников и т.д. Покрытие: см. файл.
- **`data/apple_health/types_summary.json`** — каталог всех 31 типов записей из последнего экспорта с диапазонами дат (метадата, для справки).

Эти файлы НЕ читают `/sync` и `/dashboard` — они лежат как архив. Если пользователь спросит что-то из истории ("тренировки за 2017", "плавание в 2024") — читаем напрямую через `Read`/`python3`.
