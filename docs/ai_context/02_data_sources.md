# Реестр Источников Данных (Data Sources)

В этом файле описаны все интеграции HealthVault, методы получения данных, статус их актуальности и инструкции (SOP) по тому, как ИИ или пользователь могут подтянуть свежие данные.

---

## 🤖 Шпаргалка для ИИ: откуда брать данные при анализе

> [!WARNING]
> **Перед любым анализом данных** — сначала прочитай эту таблицу. Ошибочное чтение из локальных файлов вместо PostgreSQL (или наоборот) даёт неверные результаты.

| Метрика | Источник | Как читать |
|---|---|---|
| 🍽️ **Питание** (ккал, белки, жиры, углеводы) | **PostgreSQL** `nutrition_log` | SSH → psql (см. SQL ниже) |
| ⚖️ **Вес** (kg, % жира, мышцы) | **PostgreSQL** `weights` | SSH → psql |
| 💊 **Добавки** | **PostgreSQL** `supplements_log` | SSH → psql |
| 🩺 **АД** (систола, диастола, пульс) | Локально: `data/apple_health_blood_pressure.json` | `json.load()` |
| 👣 **Шаги** (ежедневные) | Локально: `data/apple_health_steps_daily.json` | `json.load()` |
| 💤 **Сон** (длительность, фазы, HRV ночи) | Локально: `data/garmin/sleep/YYYY-MM-DD.json` | glob по дням |
| ❤️ **ЧСС покоя, стресс, BB** | Локально: `data/garmin/daily-summary/YYYY-MM-DD.json` | glob по дням, поле `data['stats']` |
| 📊 **HRV** (weekly/lastNight) | Локально: `data/garmin/hrv/YYYY-MM-DD.json` | glob по дням, поле `data['hrvSummary']` |
| 🔋 **Body Battery** (charged/drained) | Локально: `data/garmin/body-battery/YYYY-MM-DD.json` | glob, `data[0]['charged']` |
| 🌬️ **CO₂, температура, влажность** | Локально: `data/environment/netatmo_history.json` | unix-ts ключи |
| 📱 **Экранное время iPhone** | Локально: `data/activities/iphone_screentime_perapp.json` | `{date: {total_minutes: N}}` |
| 💻 **Экранное время Mac** | Локально: `data/activities/mac_screentime_perapp.json` | `{date: {total_minutes: N}}` |
| 🌐 **Chrome история** | Локально: `data/activities/chrome_history.json` | `{date: {total_visits: N}}` |
| 🚶 **Характеристики ходьбы** | Локально: `data/activities/gait_metrics.json` | `{date: {walkingSpeed, stepLength, ...}}` |
| 🩸 **Анализы крови** | Локально: PDF в `data/blood-tests/` + `reports/COMPLETE_MEDICAL_DATA.md` | Читать MD-файл |

### ⚡ Быстрый SQL для питания

```python
# Питание из PostgreSQL через SSH — ЕДИНСТВЕННЫЙ правильный способ
import subprocess, json

result = subprocess.run([
    'ssh', 'root@116.203.213.137',
    'docker exec healthvault_postgres psql -U healthvault -d healthvault '
    '--no-align --field-separator=, --tuples-only -c "'
    'SELECT date, '
    'ROUND(SUM((totals->>\'\'calories\'\')::numeric),0) as kcal, '
    'ROUND(SUM((totals->>\'\'protein\'\')::numeric),1) as protein, '
    'ROUND(SUM((totals->>\'\'fat\'\')::numeric),1) as fat, '
    'ROUND(SUM((totals->>\'\'carbs\'\')::numeric),1) as carbs '
    'FROM nutrition_log '
    'WHERE date >= \'\'2026-01-06\'\' AND user_id = 895655 '
    'GROUP BY date ORDER BY date;"'
], capture_output=True, text=True)
```

Или напрямую через bash:
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

### ⚡ Быстрый SQL для веса

```bash
ssh root@116.203.213.137 "docker exec healthvault_postgres psql -U healthvault -d healthvault -c \"
SELECT date, AVG(weight_kg) as weight_kg, AVG(fat_percent) as fat_pct
FROM weights WHERE user_id = 895655
GROUP BY date ORDER BY date;\""
```

### ⚠️ Критические ошибки которые нельзя повторять

- ❌ **НЕ ищи локальные JSON-файлы с питанием** — их не существует. Питание только в PostgreSQL.
- ❌ **НЕ ищи `nutrition_log.calories`** — КБЖУ хранится в JSONB поле `totals->>'calories'`, не как отдельная колонка.
- ❌ **НЕ читай `activity_log` для HRV** — поле `hrv` там NULL. HRV только в `data/garmin/hrv/*.json`.
- ❌ **НЕ читай `sleep_records`** — таблица пустая. Сон только в `data/garmin/sleep/*.json`.
- ❌ **НЕ читай `workouts`** — таблица пустая. Тренировки только в `data/garmin/activities/*.json`.

---

> [!IMPORTANT]
> **ЕДИНАЯ ТОЧКА ВХОДА:** Чтобы гарантировать 100% актуальность всех потоков данных при начале аналитической сессии, **используй скилл `/sync`** или запусти мастер-скрипт вручную:
> `bash scripts/sync_all_data.sh`
> Скрипт: (1) синхронизирует БД с удалённого сервера (питание, добавки, вес), (2) скачивает свежие данные Гармина, (3) обновляет Netatmo климат, (4) обновляет экранное время iPhone/Mac/Chrome.

> [!NOTE]
> **Данные Гармина — два слоя:**
> - **PostgreSQL `activity_log`** — шаги, калории, ЧСС, стресс, часы сна. Обновляется автоматически при отправке `/day` в Telegram-бот.
> - **Локальные JSON файлы** (`data/garmin/`) — фазы сна, HRV, Body Battery, детали тренировок. Обновляются скриптом `download_garmin_data.py` (запускается через `sync_all_data.sh`).
> ⚠️ `activity_log.hrv` всегда NULL — HRV доступен только из JSON. Таблицы `sleep_records` и `workouts` в PostgreSQL пустые.

---

## 1. 🩸 Медицинские анализы
* **Данные**: Холестерин и фракции (ЛПНП, ЛПВП, ТГ), витамины (D, B12, ферритин), гормоны (тестостерон, ГСПГ, кортизол), HbA1c, общий белок.
* **Канал**: PDF-файлы лабораторий (Invitro, ЕМИАС, CMD) в `data/blood-tests/` и `data/hormones/`. Сводный отчёт — `reports/COMPLETE_MEDICAL_DATA.md`.
* **ВАЖНО**: Таблица `blood_tests` в PostgreSQL **пустая** (данные живут только в PDF + COMPLETE_MEDICAL_DATA.md).
* **Актуальность**: 14 срезов с 2014 по 2026 год. Последний анализ: **7 января 2026** (Invitro): холестерин 5.86, ЛПНП 3.79 (↑), тестостерон 12.09 (нижняя граница ISSAM), витамин D 33.5, HbA1c 5.2, ферритин 41.7 (↑).
* 💡 **Статус**: ⚠️ ТРЕБУЕТ ОБНОВЛЕНИЯ (план: раз в 3 месяца, следующий ~апрель 2026).
* 🛠 **Инструкция**: Пользователь сдаёт биохимию и загружает PDF в чат бота или кладёт в `data/blood-tests/`. ИИ парсит PDF и обновляет `COMPLETE_MEDICAL_DATA.md`.

---

## 2. 💤 Сон
* **Данные (PostgreSQL)**: Длительность сна (sleep_hours) — в `activity_log`. Покрытие: 98.2% дней с 6 января.
* **Данные (JSON)**: Фазы сна (глубокий/REM/лёгкий), дыхание во сне (avg_respiration), SpO2, время засыпания/пробуждения — в `data/garmin/sleep/`.
* **ВАЖНО**: Таблица `sleep_records` в PostgreSQL **пустая**. Фазы сна — только в локальных JSON.
* **Актуальность**: PostgreSQL — **9 марта 2026** ✅. JSON файлы — **1 марта 2026** (отстают на 8 дней, обновляются через `/sync`).
* 📊 **Базовая линия дыхания**: 12.07 ± 0.84 вд/мин (54 дня, янв–март 2026). Значение ≥14 = аномалия (болезнь/алкоголь/стресс).
* 💡 **Статус**: ✅ (длительность) / ⚠️ (фазы — JSON могут отставать).
* 🛠 **Как обновить**: `/sync` или `python3 scripts/garmin/download_garmin_data.py`.

---

## 3. 🏋️‍♂️ Тренировки и Активность
* **Данные (PostgreSQL)**: Шаги, активные калории, суммарные калории, расстояние — в `activity_log`. Покрытие: с 5 января 2025 по 9 марта 2026.
* **Данные (JSON)**: Детали тренировок (тип, ЧСС зоны, лапы, темп) — в `data/garmin/activities/`. 51 тренировка всего, 24 с 6 января, последняя **28 февраля 2026**.
* **ВАЖНО**: Таблица `workouts` в PostgreSQL **пустая**. Детали тренировок — только в локальных JSON.
* **Актуальность**: PostgreSQL — **9 марта 2026** ✅. JSON активности — **28 февраля 2026** (обновляются через `/sync`).
* 💡 **Статус**: ✅ (ежедневная активность) / ⚠️ (детали тренировок — JSON).
* 🛠 **Как обновить**: `/sync` или `python3 scripts/garmin/download_garmin_data.py`.

---

## 4. ❤️ Пульс, Стресс, ВСР (HRV), Body Battery
* **Данные**:
  - **Пульс**: Apple Health → `data/apple_health_heart_rate.json`. 2 037 измерений, последнее **9 марта 2026** ✅.
  - **Стресс**: PostgreSQL `activity_log.stress_level` — ✅ **9 марта 2026**.
  - **HRV**: Только в `data/garmin/hrv/` JSON — **1 марта 2026**. ⚠️ `activity_log.hrv` = NULL (не заполняется).
  - **Body Battery**: Только в `data/garmin/body-battery/` JSON — **1 марта 2026**.
* **Актуальность**: Пульс и стресс — ✅ актуальны. HRV и Body Battery — ⚠️ JSON могут отставать.
* 💡 **Статус**: ✅ (пульс, стресс) / ⚠️ (HRV, Body Battery — только JSON).
* 🛠 **Как обновить пульс**: Экспорт Apple Health → `workflows/apple-health-import.md`. HRV/BB — `/sync`.

---

## 5. 🩺 Артериальное давление (АД)
* **Данные**: Систолическое/диастолическое давление, пульс при измерении.
* **Канал**: Apple Health → `data/apple_health_blood_pressure.json`. 141 измерение.
* **Актуальность**: Последнее измерение — **9 марта 2026** ✅.
* 💡 **Статус**: ✅
* 🛠 **Как обновить**: Экспорт Apple Health → `python3 scripts/import_apple_health.py`.

---

## 5b. 👣 Шаги (ежедневные)
* **Данные**: Суммарное количество шагов в день (объединяет данные Garmin + iPhone).
* **Канал**: Apple Health → `data/apple_health_steps_daily.json`. 4063 дня истории (с 2015).
* **ВАЖНО**: Этот файл точнее, чем `activity_log.steps` в PostgreSQL, т.к. суммирует **оба источника** (Garmin Watch + iPhone). PostgreSQL содержит только данные Garmin Watch.
* **ВАЖНО**: Apple Health НЕ дедуплицирует. Garmin + iPhone + Zepp Life суммировались бы. Скрипт берёт только **Garmin (Connect)** как единственный надёжный источник, fallback на iPhone если нет данных Garmin.
* **Актуальность**: **9 марта 2026** ✅. Среднее с 6 января: **7,489 шагов/день** (63 дня, покрытие 100%). Диапазон: 1,960–13,841 шагов/день.
* 💡 **Статус**: ✅
* 🛠 **Как обновить**: Ручной экспорт Apple Health → `python3 scripts/import_apple_health.py` (автопоиск export.xml в ~/Downloads/).

---

## 5c. 🚶 Характеристики ходьбы (Gait)
* **Данные**: Скорость ходьбы (km/h), длина шага (cm), двойная опора (%), асимметрия (%). Пассивно измеряется iPhone при ходьбе.
* **Канал**: Apple Health → `data/apple_health_gait.json`. 1987 дней истории (с 2020).
* **Биохакерское значение**:
  - **Двойная опора (double_support_pct)**: норма 25-30%. Рост >30% → усталость/болезнь/недовосстановление.
  - **Асимметрия (asymmetry_pct)**: норма <4%. Рост >5% → дисбаланс, риск травмы.
  - **Скорость ходьбы**: косвенный показатель уровня энергии (снижается при болезни/стрессе).
* **Актуальность**: **9 марта 2026** ✅. 63 дня с 6 января. Текущие: 4.94 км/ч, опора 26.8%, асимм 0%.
* 💡 **Статус**: ✅
* 🛠 **Как обновить**: Ручной экспорт Apple Health → `python3 scripts/import_apple_health.py`.

---

## 6. 🥗 Питание
* **Данные**: Приёмы пищи (время), КБЖУ, названия продуктов, клетчатка.
* **Канал**: PostgreSQL `nutrition_log` на сервере Hetzner. 318 записей, **6 января — 9 марта 2026** (покрытие 98.2%).
* **Актуальность**: **9 марта 2026** ✅.
* 💡 **Статус**: ✅
* 🛠 **Как обновить**: Данные вводятся через Telegram-бот в реальном времени. `/sync` синхронизирует локальный дамп.

---

## 7. 💊 Витамины и Добавки
* **Данные**: Приёмы витаминов и добавок (Омега 3-6-9, Псиллиум, Витамин D3, Магний, Стеролы и др.).
* **Канал**: PostgreSQL `supplements_log` на сервере Hetzner. 263 записи, **11 января — 9 марта 2026** (покрытие ~80%).
* **Актуальность**: **9 марта 2026** ✅.
* 💡 **Статус**: ✅
* 🛠 **Как обновить**: Данные вводятся через Telegram-бот. `/sync` синхронизирует локальный дамп.

---

## 8. 🍷 Алкоголь
* **Данные**: Флаг употребления алкоголя (день/нет), тип напитка.
* **Канал**: Вычисляется «на лету» из `nutrition_log` — поиск по ключевым словам (вино, пиво, ром и т.д.).
* **Актуальность**: **9 марта 2026** ✅ (синхронно с питанием).
* 💡 **Статус**: ✅
* 🛠 **Как обновить**: Специальных действий не требуется — метрика извлекается при анализе.

---

## 9. ⚖️ Вес и Состав тела
* **Данные**: Вес, процент жира, мышечная масса, % воды, висцеральный жир, ИМТ, масса костей.
* **Канал**: PostgreSQL `weights` на сервере Hetzner. 670 записей всего, 63 с 6 января. Источник: скриншоты приложения Zepp Life → OCR в Telegram-боте.
* **Дополнительно**: `data/apple_health_weight_daily.json` — 563 дня ежедневных средних значений веса (только вес, без состава).
* **Актуальность**: **9 марта 2026** ✅.
* 💡 **Статус**: ✅
* 🛠 **Как обновить**:
  - *Состав (Zepp):* Скинуть скриншот Zepp в Telegram-бот → OCR → `weights` таблица.
  - *Вес (Apple Health):* Экспорт Apple Health → `workflows/apple-health-import.md`.

---

## 10. 📏 Замеры тела (сантиметром)
* **Данные**: Талия, шея, бёдра, грудь, бицепс, бедро.
* **Канал**: Ручной ввод в `data/weights/body_measurements.json`.
* **Актуальность**: 4 записи: 2026-01-08, 2026-02-01, 2026-02-10, **2026-03-01** ✅.
* 💡 **Статус**: ✅
* 🛠 **Как обновить**: Сделать замеры лентой и попросить ИИ добавить запись в `data/weights/body_measurements.json`.

---

## 11. 🌬️ Климат спальни (Netatmo)
* **Данные**: Температура, влажность, CO2, шум (dB). Только станция «Большевик».
* **Канал**: `data/environment/netatmo_history.json`. 60 суточных записей.
* **Актуальность**: **2026-01-09 → 2026-03-09** ✅. Текущие: ~21.6°C, CO2 ~1051 ppm.
* 💡 **Статус**: ✅
* 🛠 **Как обновить**: `/sync` или `python3 scripts/import_netatmo.py`.

---

## 12. 📱 Экранное время (iPhone, по приложениям)
* **Данные**: Время использования каждого приложения по категориям (соцсети, продуктивность, развлечения и т.д.).
* **Канал**: `data/activities/iphone_screentime_perapp.json`. 29 дней. Источник: Biome/ActivityWatch (`aw-import-screentime`).
* **Актуальность**: **2026-02-09 → 2026-03-09** ✅.
* 💡 **Статус**: ✅ (LaunchAgent запускается автоматически в 8:00 каждый день).
* 🛠 **Как обновить**: Автоматически или `/sync`. Скрипт: `python3 scripts/import_activitywatch.py`.

---

## 13. 💻 Экранное время (Mac, по приложениям)
* **Данные**: Время активного использования каждого приложения на MacBook.
* **Канал**: `data/activities/mac_screentime_perapp.json`. 10 дней. Источник: `macOS knowledgeC.db` (системная БД Screen Time).
* **Актуальность**: **2026-02-28 → 2026-03-09** ✅.
* 💡 **Статус**: ✅ (LaunchAgent 8:00). ⚠️ Данные хранятся в ОС ~11 дней — пропуск в синке = потеря истории.
* 🛠 **Как обновить**: Автоматически или `/sync`. Скрипт: `python3 scripts/import_mac_screentime.py`. Требует Full Disk Access у Terminal.

---

## 14. 🌐 История браузера (Chrome)
* **Данные**: URL визиты с временными метками. Категоризируется при анализе (работа, развлечения, медицина).
* **Канал**: `data/activities/chrome_history.json`. 84 дня, **26 383 визита**.
* **Актуальность**: **2025-12-10 → 2026-03-09** ✅.
* 💡 **Статус**: ✅ (LaunchAgent 8:00).
* 🛠 **Как обновить**: Автоматически или `/sync`. Скрипт: `python3 scripts/import_chrome_history.py`.

---

## 15. 🧬 Генетика
* **Данные**: Генетические предрасположенности (риски по здоровью, происхождение, носительство).
* **Канал**: PDF-файлы в `data/genetics/`. 2 документа: Atlas Biomed (2009), дополнительный тест (2016).
* **Актуальность**: Архивные данные. Не обновляются.
* 💡 **Статус**: ✅ (статичные данные).
* 🛠 **Как обновить**: Не требуется. При новом тестировании — загрузить PDF в `data/genetics/`.
