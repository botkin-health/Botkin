# Research: open-source клиенты-экспортёры Apple Health → свой сервер

Дата: 2026-06-09 · По запросу: «аналоги `baccula/health-dashboard-export` и Health Auto Export в более зрелом виде; применимость к Botkin; как сохранить чужой репо от удаления»

## TL;DR

- **Полностью open-source, зрелого, turnkey iOS-приложения «HealthKit → свой webhook» практически НЕТ.** Категорию держит закрытый коммерческий Health Auto Export (HAE) — тот, что мы уже используем. У HAE открыты только сервер, MCP и спека API, но не само приложение.
- OSS-«приложения-экспортёры» (baccula, `aderaaij/somatic`, `kempu/HealthBeat`) — все **сырые хобби-проекты на 0–2 ⭐**. Зрелее baccula среди них нет; somatic концептуально такой же, но тоже ранний.
- Зрелое и активное есть в **двух соседних категориях**: (а) фреймворки/SDK чтобы *построить* свой экспортёр — `the-momentum/open-wearables` (iOS SDK, 1839⭐) и `StanfordSpezi/SpeziHealthKit`; (б) серверы-приёмники под HAE — `irvinlim/apple-health-ingester`, официальный сервер HAE, `apple-health-grafana`.
- **Для Botkin:** срочной замены не нужно — HAE → наш `apple_health_v2` webhook работает. Если когда-нибудь захотим **свой** iOS-клиент (приватность/бренд/прямой коннект в Botkin) — строить не с нуля, а на **open-wearables iOS SDK** (если нужен мультиисточник) или **SpeziHealthKit** (медицинско-исследовательский грейд). baccula-код держать как минимальный референс плумбинга (BGTaskScheduler + Keychain).
- **Кроме GitHub — пусто.** GitLab / Bitbucket / Codeberg / SourceForge по теме Apple Health держат только **зеркала GitHub** и тривиальные демки (0–3 ⭐). Китайские форжи (Gitee / GitCode / Coding) для Apple-экосистемы — тоже зеркала GitHub (`gh_mirrors/*`); их реальная сила — домашние носимые (Xiaomi / Zepp / Huawei), но это уже **другой запрос**. По Apple Health / HealthKit **GitHub — де-факто монополия**. (Раздел «Источники кроме GitHub» ниже.)
- **Сохранение от удаления автором:** надёжнее всего `git clone --mirror` → push в свежий приватный репо (полная независимая копия, не в fork-сети upstream). Форк проще, но технически живёт в сети оригинала.

## Контекст

Botkin тянет Apple Health через коммерческий **Health Auto Export** (iOS, $24.99) на вебхук `POST /apple_health_v2`, парсер — `telegram-bot/webhook/apple_health.py`. Это работает и стабильно. Вопрос возник из находки сына Игоря — `baccula/health-dashboard-export`, минимального OSS-приложения той же идеи. Интерес: (1) застраховаться от исчезновения такого кода, (2) понять, есть ли зрелый OSS, на котором можно сделать **свой** клиент, если решим уйти от закрытого HAE.

## Категории (важно не путать)

| Тип | Что делает | Под наш кейс |
|---|---|---|
| **A. On-device push client** | Приложение/SDK на iPhone, читает HealthKit и непрерывно шлёт на сервер (BGTask/observer) | ✅ Это и есть «как baccula»/HAE |
| B. XML/ZIP парсеры | Разбирают ручной `export.zip` батчем | ❌ Не непрерывно, ручной экспорт |
| C. Серверы-приёмники | Принимают поток от HAE/клиента, кладут в БД/Influx/Grafana | 🔶 Это наша серверная сторона |
| D. AI/MCP-слой | Запросы к Health-данным через LLM | 🔶 Botkin-смежное |

Большинство «звёздных» репо по `apple-health` — это **B** (парсеры zip). Нам интересна **A**.

## Категория A — on-device push-клиенты (прямые аналоги)

### 1. [the-momentum/open-wearables](https://github.com/the-momentum/open-wearables) — ⭐1839 · MIT
**Стек:** FastAPI (Python) + React/TS + PostgreSQL + Redis + Celery; **есть нативный iOS SDK (Swift)** для push-based синка из HealthKit, плюс Android/Flutter/RN SDK.
**Что делает:** self-hosted платформа-унификатор: Apple Health, Garmin, Oura, Whoop, Polar, Suunto, Ultrahuman, Strava, Fitbit, Samsung, Google Health Connect → единый «AI-ready» API. Активность: коммиты на 2026-06-08, v0.5.2 (май 2026), 324 форка.
**Применимость к Botkin:** самый серьёзный кандидат. Не само приложение, а **SDK + референс-архитектура**: если делаем свой клиент — берём их Swift SDK для HealthKit-push; серверная часть на FastAPI/PostgreSQL близка нашему стеку. Можно даже подсмотреть нормализацию мультиисточника.
**Чего не хватает:** pre-1.0, 135 open issues, «under active development» — на проде пока рискованно; это платформа, а не готовая аппа.

### 2. [StanfordSpezi/SpeziHealthKit](https://github.com/StanfordSpezi/SpeziHealthKit) — ⭐40 · MIT
**Стек:** Swift, часть большого фреймворка Stanford Spezi (десятки модулей, 37 релизов, апрель 2026).
**Что делает:** промышленный модуль чтения HealthKit + **long-lived background data collection** + визуализация (`HealthKitQuery`, `HealthChart`). Используется в реальных медисследовательских приложениях Стэнфорда.
**Применимость к Botkin:** самый «взрослый» фундамент чтобы написать СВОЙ iOS-экспортёр аккуратно (фоновая доставка, типы данных). Аплоад на сервер — **пишем сами** (встроенного нет), но это как раз тонкий слой `URLSession` → наш webhook.
**Чего не хватает:** нет готового «отправь на мой сервер» — это библиотека-фундамент, не аппа. Нужен Swift-разработчик.

### 3. [aderaaij/somatic](https://github.com/aderaaij/somatic) — ⭐2 · license TBD
**Стек:** 100% Swift/SwiftUI, WorkoutKit, HealthKit background observers; сервер — FastAPI + PostgreSQL + MCP.
**Что делает:** «privacy-first training companion»: планы тренировок, Apple Watch scheduling, автосинк HealthKit (сон, HRV, вес, VO2Max, шаги, GPS/HR/power тренировок) на **свой self-hosted backend**, опционально интеграция с open-wearables.
**Применимость:** концептуально ближайший двойник идеи Botkin (HealthKit + AI-коуч + self-hosted + MCP!) — полезен как **референс**, но 13 коммитов, лицензия не определена, ранний.

### 4. [grongierisc/Swift-FHIR-Iris](https://github.com/grongierisc/Swift-FHIR-Iris) — ⭐10 · MIT
iOS-приложение: HealthKit → **FHIR** (InterSystems IRIS или любой FHIR-репозиторий). Реальный on-device push-клиент к серверу. Маленький и stale (2023-08), но как пример «iOS-аппа шлёт HealthKit на медицинский сервер» — годный референс, особенно если когда-нибудь захотим FHIR-совместимость.

### 5. [oreno-dinner/HLExport](https://github.com/oreno-dinner/HLExport) — free · open-source (SwiftUI)
**Offline**-аппа: выбор диапазона дат → экспорт HealthKit-сэмплов (шаги, пульс, сон, HRV) в `.json` через share-sheet/буфер. **Без сервера и телеметрии**, плюс mood-логирование (iOS 18+). Не push-клиент (на сервер не шлёт), но самый «приватный» и живой OSS-экспортёр; автор активно общается в Quantified Self форуме. Полезен как референс чистой выгрузки HealthKit без бэкенда.

### 6. Мелочь для референса плумбинга
- [kempu/HealthBeat](https://github.com/kempu/HealthBeat) — HealthKit → MySQL непрерывно (0⭐, май 2026).
- [shailendra-kindlebit/Health_kbs](https://github.com/shailendra-kindlebit/Health_kbs) — «production-ready SwiftUI HealthKit Background Sync» sample (3⭐) — пример именно BGTask-синка.
- [baccula/health-dashboard-export](https://github.com/baccula/health-dashboard-export) — находка Игоря (2⭐): HealthKit → configurable dashboard API, Keychain, BGTaskScheduler, Shortcuts. Минимальный, но честный референс «как послать на свой webhook».

### Библиотеки-обёртки HealthKit (для своего клиента)
- [kvs-coder/HealthKitReporter](https://github.com/kvs-coder/HealthKitReporter) — ⭐89, Swift, read/write обёртка (+ Flutter-порт). Активность 2024.
- [microsoft/healthkit-on-fhir](https://github.com/microsoft/healthkit-on-fhir) — ⭐118, Swift, авто-экспорт HealthKit → FHIR. **Заброшен (2022)** — не брать.

## Категория C — серверы-приёмники (наша сторона, для сравнения)

- [irvinlim/apple-health-ingester](https://github.com/irvinlim/apple-health-ingester) — ⭐106, Go, MIT. HTTP-сервер под **поток от Health Auto Export** → InfluxDB/файл, Bearer-auth, Docker. По сути open-source аналог нашего `apple_health.py`, но на Go и в Influx. v0.5.0 (фев 2025).
- [HealthyApps/health-auto-export-server](https://github.com/HealthyApps/health-auto-export-server) — ⭐143, TS, **официальный** сервер HAE → Grafana.
- [HealthyApps/health-auto-export-mcp-server](https://github.com/HealthyApps/health-auto-export-mcp-server) — ⭐48, TS, **официальный MCP** поверх HAE — Botkin-смежно (наш агент тоже ходит по Health-данным).
- [Lybron/health-auto-export](https://github.com/Lybron/health-auto-export) — ⭐239, спека JSON-формата HAE (то, по чему написан наш парсер).
- [k0rventen/apple-health-grafana](https://github.com/k0rventen/apple-health-grafana) — ⭐570, Python — но это парсер `export.zip` → InfluxDB+Grafana (категория B, батч).

## Категория D — AI/MCP над Apple Health (Botkin-смежное, на заметку)

- [StanfordBDHG/HealthGPT](https://github.com/StanfordBDHG/HealthGPT) — ⭐1951, Swift, «запросы к Apple Health на естественном языке».
- [the-momentum/apple-health-mcp-server](https://github.com/the-momentum/apple-health-mcp-server) — ⭐208, Python, DuckDB.
- [RuochenLyu/apple-health-analyst](https://github.com/RuochenLyu/apple-health-analyst) — ⭐52, TS, «privacy-first» кросс-метричные инсайты (апрель 2026).

## Источники кроме GitHub (GitLab / Bitbucket / Codeberg / китайские форжи)

Проверено через публичные API и веб-поиск (2026-06-09). **Краткий вывод: по Apple Health / HealthKit GitHub — де-факто монополия; всё остальное — зеркала и мелочь.**

| Форж | Что нашлось по Apple Health / HealthKit | Вердикт |
|---|---|---|
| **GitLab.com** | Только тривиальные демки и **зеркала GitHub**: `petleo-and-iatros/flutter_health` (зеркало cph-cachet), `tidepool-gitlab-admin/healthkit-uploader` (зеркало Tidepool), `*/apple-health-to-fitbit` (конвертер). Максимум 3 ⭐. | ❌ Ничего уникального/зрелого |
| **Codeberg** (Gitea, EU) | 1 проект: `selfawaresoup/apple-health-r` (R-скрипт для графиков export, 0 ⭐). | ❌ Пусто |
| **Bitbucket** (Atlassian) | Нет публичного discovery репозиториев; платформа давно ушла в приватные команды. Поиск выводит обратно на GitHub. | ❌ Не источник для OSS-находок |
| **SourceForge** | Легаси-хостинг; по теме ничего живого. | ❌ Пусто |
| **GitCode** (CSDN, 中国) | Apple/HealthKit-проекты — это явные **`gh_mirrors/*`** (авто-зеркала GitHub: `healthkit-to-sqlite`, `rn-apple-healthkit`, `Granola`). Оригинального нет. | 🪞 Только зеркала GitHub |
| **Gitee (码云)** | API без access-token результатов не отдала (требует авторизации / возможно недоступна из региона сервера). По веб-поиску — оригинального Apple-контента не видно, есть общий каталог `explore/ios-modules`. | ⚠️ Не подтверждено, но признаков нет |
| **Coding.net** (Tencent) | Корпоративный DevOps-портал, публичного discovery OSS нет. | ❌ Не источник |

**Важный нюанс для Botkin (на будущее, НЕ про Apple Health):** реальная сила китайских форжей — **реверс-инжиниринг домашних носимых**: Xiaomi Mi Band, **Zepp / Amazfit**, Huawei Health. Поскольку мы тянем вес с **Zepp (CN3 API)**, отдельный прицельный поиск по Gitee/GitCode именно по `小米手环 / Zepp / 华为健康` может дать то, чего нет на GitHub. Но это **другой запрос** — здесь мы искали Apple Health-экспортёры, а по ним там пусто.

## Рекомендация

1. **Сейчас ничего не менять** — HAE → `apple_health_v2` работает; OSS turnkey-замены нет.
2. **Сохранить находку Игоря** от удаления автором: зеркало в приватный репо (см. ниже). baccula + somatic + Health_kbs — держать как референс-набор «как написать свой клиент».
3. **Если решим делать свой iOS-клиент** (ради приватности/прямого коннекта в Botkin без посредника-HAE): не с нуля. Бейзлайн — **SpeziHealthKit** (читалка + фоновый сбор, медицинский грейд) + тонкий слой аплоада на наш webhook; либо **open-wearables iOS SDK**, если захотим заодно Garmin/Oura/Whoop единым каналом. Это требует Swift-разработчика — отдать Игорю как эксперимент.

## Как сохранить чужой GitHub-репо, чтобы автор не удалил

**Варианты по надёжности:**

1. **Mirror в приватный репо (золотой стандарт против удаления):**
   ```bash
   git clone --mirror https://github.com/baccula/health-dashboard-export.git
   gh repo create Lyskovsky/health-dashboard-export-mirror --private
   cd health-dashboard-export.git
   git push --mirror https://github.com/Lyskovsky/health-dashboard-export-mirror.git
   ```
   Полная независимая копия (все ветки/теги/история), **вне fork-сети** оригинала → переживает удаление автором гарантированно.

2. **Форк** (`gh repo fork baccula/health-dashboard-export`): 1 команда, удобно Игорю (clone/build/PR upstream). Переживает удаление (GitHub переназначает корень fork-сети), но формально часть сети оригинала и помечен «forked from».

3. **Локальный архив** на Mac/Google Drive: `git clone --mirror` без push — самое простое, но только на твоей машине.

**Рекомендация:** форк **для Игоря** (удобно работать) + mirror в приватный репо **как страховку**. Оба требуют у токена scope `repo`.

## Следующие шаги для Botkin

- [ ] Сохранить `baccula/health-dashboard-export` (fork и/или mirror в `Lyskovsky/...`) — решение за Александром.
- [ ] (опц.) Передать Игорю как эксперимент: оценить, насколько JSON-формат baccula близок нашему `apple_health_v2`, и можно ли нацелить его POST прямо на Botkin без правок сервера.
- [ ] (LATER, если уйдём от HAE) Прототип своего iOS-клиента на SpeziHealthKit / open-wearables SDK → `apple_health_v2`.
- [ ] (на заметку) `health-auto-export-mcp-server` и `apple-health-mcp-server` — посмотреть как референс MCP-слоя над Health-данными для BotkinClaw.
