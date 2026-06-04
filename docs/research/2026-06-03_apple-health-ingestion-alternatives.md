# Research: альтернативы платному Health Auto Export для забора данных Apple Health

Дата: 2026-06-03 · По запросу: «Как другие health-tracking / биохакинг проекты берут данные из Apple Health без того чтобы каждый юзер платил $25 за HAE»

## TL;DR

1. **У Apple Health НЕТ серверного API.** Apple принципиально не даёт облачного доступа к HealthKit — данные только on-device. Поэтому ВСЕ проекты упираются в один из трёх путей: (а) нативное приложение с HealthKit, (б) iOS Shortcuts (бесплатно, но читает Health только при разблокированном телефоне → ненадёжно в фоне), (в) платное приложение-мост с фоновым разрешением (HAE и аналоги). Магического четвёртого пути нет.
2. **HAE — не единственный, но самый надёжный мост.** Есть более дешёвые/бесплатные аналоги через Shortcuts: **Health Webhook**, **Health Exporter & Shortcuts** (бесплатное, on-device), **HealthSave**. Все упираются в то же ограничение «телефон должен быть разблокирован».
3. **Правильная стратегия — обходить Apple Health через прямые device-API.** Whoop, Garmin, Oura, Withings, Fitbit, Polar — у всех есть облачные OAuth API. Данные тянутся с сервера производителя напрямую, БЕЗ iPhone-посредника и без HAE. Для Botkin это главный вывод.
4. **Для Димы конкретно: Whoop подключается напрямую через WHOOP OAuth API** (developer.whoop.com) — сон, recovery, strain, RHR, HRV, SpO2. Apple Health/HAE ему не нужен вообще. Вес — отдельно через Mi Scale→Zepp (уже в коде) или ручной ввод.
5. **Open Wearables** (the-momentum, 1.8k⭐, MIT, FastAPI/Python — тот же стек) — готовые OAuth-интеграции со всеми носимыми. Целиком брать тяжело (Postgres+Redis+Celery+React), но **код их Whoop/Garmin/Oura интеграций можно переиспользовать**.

## Контекст

Botkin сейчас тянет Apple Health через платный HAE ($24.99 lifetime) на webhook `/apple_health_v2`. Стек проекта — Python/FastAPI/PostgreSQL/aiogram, уже есть прямые интеграции Garmin и Zepp (Xiaomi). Беспокойство владельца: при росте числа пользователей нельзя требовать, чтобы каждый покупал HAE. Нужен путь масштабирования: вес/давление/сон/пульс с iPhone многих юзеров без подушевой платы за стороннее приложение.

## Почему Apple Health так неудобен (фундамент)

Apple НЕ предоставляет server-to-server API к HealthKit (в отличие от Google Health Connect, Garmin, Whoop). Доступ к данным есть только у приложения на самом устройстве. Из этого следует, что любой «экспорт на сервер» — это либо приложение, которое читает HealthKit и шлёт POST, либо Shortcuts. И ключевое инженерное ограничение, которое подтвердили все источники:

> **HealthKit можно читать только когда телефон разблокирован.** Shortcut/приложение не может в фоне при заблокированном телефоне вытащить свежие данные.

Именно поэтому старый Shortcut в Botkin был «ненадёжным» (требовал ручного запуска, падал). HAE решает это специальным background-разрешением (а не магией) — поэтому за него и просят деньги.

## Лучшие подходы (ранжированный список)

### 1. Прямые device-API через OAuth — ГЛАВНЫЙ путь ⭐ рекомендация

Вместо борьбы с Apple Health — тянуть данные напрямую из облака производителя устройства. Apple Health становится не нужен.

- **WHOOP API** — [developer.whoop.com](https://developer.whoop.com/api/). OAuth 2.0 + webhooks (уведомление о новых данных). Отдаёт sleep, recovery (RHR, HRV, SpO2, skin temp), strain, physiological cycles. Бесплатно для разработчика. **Прямо подходит Диме.**
- **Garmin** — уже в Botkin (`python-garminconnect`).
- **Zepp/Xiaomi** — уже в Botkin (`zepp_api.py`). Mi-весы → Zepp cloud → сервер. Бесплатно.
- **Withings** — публичный OAuth Health API, бесплатный. Весы/тонометры Withings.
- **Oura, Fitbit, Polar, Strava, Ultrahuman** — все имеют OAuth API.

**Применимость к Botkin:** добавить по OAuth-интеграции на популярные устройства. У кого Garmin → Garmin API; Xiaomi → Zepp; Whoop → Whoop API; Withings весы → Withings. Apple Health нужен только как «последняя миля» для тех, у кого данные ТОЛЬКО в iPhone и нет ни одного устройства с облаком.

### 2. [Open Wearables](https://github.com/the-momentum/open-wearables) — ⭐1.8k, MIT, FastAPI/Python

**Язык:** Python (FastAPI) + React. **Активность:** релиз 0.5.2 от 2026-05-20, активная разработка.
**Что делает:** self-hosted платформа, унифицирует Whoop/Garmin/Oura/Fitbit/Polar/Suunto/Strava/Ultrahuman (cloud OAuth) + Apple HealthKit и Samsung Health (SDK) через один API. `docker compose up`.
**Применимость к Botkin:** целиком — избыточно (тянет Postgres+Redis+Celery+React, early-stage, 130 issues, API меняется). НО стек идентичен Botkin (FastAPI/Python/Postgres) → **переиспользовать их код OAuth-интеграций** (особенно Whoop, Garmin, Oura) как референс/донор. Apple Health у них = свой Swift/Flutter SDK, т.е. всё равно требует приложения — это не решает проблему «без приложения».
**Чего не хватает:** для Apple Health всё равно нужно их приложение; тяжёлая инфра для простого бота.

### 3. iOS Shortcuts → свой webhook (бесплатно, DIY) — для Apple-only юзеров

Бесплатный встроенный путь. У Botkin **уже есть endpoint `/apple_health` (v1)**, принимающий данные от Shortcuts.
- Пример пайплайна: [Maxime Heckel — personal health API на Shortcuts + serverless](https://blog.maximeheckel.com/posts/build-personal-health-api-shortcuts-serverless/). Shortcut читает метрики → POST на функцию → БД.
- [emreloper/apple-health-api](https://github.com/emreloper/apple-health-api) — Shortcuts + Firebase, open-source.
**Минус (критичный):** работает только при разблокированном телефоне, фоновая автоматизация ненадёжна. Подходит как бесплатная опция для замотивированных, но не как дефолт для всех.

### 4. Бесплатные/дешёвые приложения-мосты (аналоги HAE)

Если Shortcuts недостаточно надёжны, а платить $25 не хочется:
- **Health Webhook** ([hcwebhook.com/ios](https://hcwebhook.com/ios)) — читает Health, шлёт JSON на любой webhook по расписанию через Shortcuts, данные не уходят на чужие серверы. (Цену проверить — fetch домена заблокировался; по описанию дешевле/бесплатнее HAE.)
- **Health Exporter & Shortcuts** ([App Store](https://apps.apple.com/us/app/health-exporter-shortcuts/id6759006922)) — 100% on-device, без аккаунта, экспорт JSON + Shortcuts, загрузка на API. Заявлено бесплатным.
- **HealthSave** — фоновый sync на свой сервер как one-time покупка.

### 5. Готовые приёмники HAE-формата (если остаёшься на HAE)

- [irvinlim/apple-health-ingester](https://github.com/irvinlim/apple-health-ingester) — ⭐106, Go. HTTP-сервер, принимает HAE → LocalFile/InfluxDB. Референс формата.
- [HealthyApps/health-auto-export-mcp-server](https://github.com/HealthyApps/health-auto-export-mcp-server) — ⭐45, TS. MCP-сервер поверх HAE (любопытно для AI-доступа).
- [the-momentum AI fitness coach](https://www.themomentum.ai/blog/turning-apple-health-data-into-actionable-personal-fitness-insights) — блог тех же авторов Open Wearables про Apple Health → AI.

## Сообщества и форумы

- [Quantified Self Forum — Apple Health API](https://forum.quantifiedself.com/t/is-there-an-apple-health-api-app/1477) — старо (2015), но показывает что фрустрация «нет нормального API» — давняя и системная. Консенсуса на бесплатное решение нет.
- [Home Assistant Community — AppleHealth AutoExport](https://community.home-assistant.io/t/applehealth-autoexport/419983) — как HA-юзеры заводят Apple Health (тоже через HAE/Shortcuts на webhook).
- r/QuantifiedSelf, r/Biohackers — точечные треды, единого «лучшего бесплатного» нет; большинство либо платит за HAE, либо тянет device-API напрямую.

## Устройства / сервисы (ценники)

| Путь | Стоимость | Надёжность |
|---|---|---|
| Whoop API (OAuth) | бесплатно (нужен Whoop у юзера) | высокая (webhooks) |
| Garmin / Zepp / Withings API | бесплатно (нужно устройство) | высокая |
| iOS Shortcuts → /apple_health v1 | бесплатно | низкая (только разблокир. телефон) |
| Health Webhook / Health Exporter | бесплатно–дёшево | средняя (через Shortcuts) |
| Health Auto Export (HAE) | $24.99 разово | высокая (фоновый sync) |
| Ручной ввод в чат | бесплатно | зависит от юзера |
| Xiaomi Mi Body Scale 2 | ~3000 ₽ | высокая (через Zepp) |

## Рекомендация

**Не делать HAE обязательным. Перейти на модель «много дорог под устройство юзера»:**

1. **Приоритет — прямые OAuth device-API.** Добавить в Botkin интеграции Whoop и Withings (Garmin/Zepp уже есть), код подсмотреть в Open Wearables. Это покрывает большинство носимых без Apple Health и без подушевой платы.
2. **Apple Health — только «последняя миля»** для тех, у кого данные исключительно в iPhone. Предлагать на выбор: бесплатный Shortcut (`/apple_health` v1, честно предупредив про разблокировку) ИЛИ HAE для тех, кому критична надёжность и не жалко $25. Не навязывать платную опцию.
3. **Вес/давление — ручной ввод** как мгновенный нулевой барьер (уже работает).

**Для Димы прямо сейчас:** не трогать Apple Health вообще. Whoop → подключить через WHOOP OAuth API (сон/recovery/strain/HRV). Вес → Mi Scale через Zepp (бесплатный канал, уже в коде) или ручной ввод «вес 91». Это снимает с него и HAE, и Apple Health целиком.

## Следующие шаги для Botkin

- [ ] Добавить **Whoop OAuth-интеграцию** (`scripts/import/whoop_api.py` по образцу `zepp_api.py`), референс — Open Wearables. Первый бенефициар — Дима.
- [ ] Добавить **Withings OAuth** для весов/тонометров (бесплатный API, покрывает вес+АД одним устройством).
- [ ] Привести в порядок **бесплатный Shortcut на `/apple_health` v1** (документировать настройку, честно про ограничение разблокировки) — как бесплатная альтернатива HAE.
- [ ] В онбординг-флоу бота: спрашивать устройство и роутить на нужный канал (Garmin→Garmin, Whoop→Whoop, Xiaomi→Zepp, «только iPhone»→Shortcut/HAE).
- [ ] HAE оставить как опциональный «премиум-мост», не дефолт.
- [ ] Изучить лицензию/код Open Wearables Whoop-интеграции на предмет прямого переиспользования (MIT — можно).

## Источники

- [WHOOP API Docs](https://developer.whoop.com/api/) · [OAuth](https://developer.whoop.com/docs/developing/oauth/) · [Webhooks](https://developer.whoop.com/docs/developing/webhooks/)
- [Open Wearables — GitHub](https://github.com/the-momentum/open-wearables) · [openwearables.io](https://openwearables.io/) · [интеграции](https://openwearables.io/integrations)
- [Maxime Heckel — Shortcuts + serverless health API](https://blog.maximeheckel.com/posts/build-personal-health-api-shortcuts-serverless/)
- [emreloper/apple-health-api (Shortcuts+Firebase)](https://github.com/emreloper/apple-health-api)
- [irvinlim/apple-health-ingester](https://github.com/irvinlim/apple-health-ingester)
- [Health Webhook for iOS](https://hcwebhook.com/ios) · [Health Exporter & Shortcuts](https://apps.apple.com/us/app/health-exporter-shortcuts/id6759006922)
- [HealthyApps — REST API automation (HAE)](https://help.healthyapps.dev/en/health-auto-export/automations/rest-api/)
- [Quantified Self Forum — Apple Health API](https://forum.quantifiedself.com/t/is-there-an-apple-health-api-app/1477)
- [Home Assistant — AppleHealth AutoExport](https://community.home-assistant.io/t/applehealth-autoexport/419983)
