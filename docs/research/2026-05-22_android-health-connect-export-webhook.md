# Research: Android Health Connect — экспорт данных в webhook/HTTP

Дата: 2026-05-22 · По запросу: «Android Health Connect export webhook open-source»

---

## TL;DR

- **Победитель для Botkin:** `mcnaveen/health-connect-webhook` — наиболее зрелое решение именно под задачу «отправить данные на свой сервер», активно развивается (последний коммит May 21, 2026), 24 типа данных, интервальная/расписание-синхронизация.
- **Большая платформа, если нужна агрегация:** `the-momentum/open-wearables` (1.7k ⭐, FastAPI + PostgreSQL, Docker Compose) — self-hosted платформа с нормализованным API поверх всех wearable источников, включая Android Health Connect. Но это полноценный сервер, а не просто форвардер.
- **HCGateway** (403 ⭐) — ближайший аналог Botkin по архитектуре (Python + MongoDB + Android), но требует Firebase и MongoDB вместо PostgreSQL, и синхронизирует раз в 2 часа.
- **Tasker + TaskerHealthConnect** — самое гибкое решение без отдельного приложения: достаточно правила в Tasker, которое читает HC через плагин и шлёт POST на Botkin webhook.
- **Home Assistant Companion App** — если у пользователя есть HA, Health Connect уже интегрирован нативно (11 сенсоров). Для Botkin это боковой путь, но интересен как паттерн.

---

## Контекст

Botkin уже принимает данные Apple Health через HAE (Health Auto Export) на эндпоинт `/apple_health_v2`. Для Android-пользователей (прежде всего Олег, возможно Андрей Походня) нужен симметричный канал. Android Health Connect — официальная платформа Google (заменила Google Fit с 2023), консолидирует данные из Samsung Health, Garmin Connect Mobile, Mi Fitness и др. Задача — найти готовое приложение/скрипт, которое читает данные из Health Connect и шлёт POST на `https://health.orangegate.cc/apple_health_v2` (или аналогичный эндпоинт для Android).

---

## Лучший open source (ранжированный список)

### 1. [health-connect-webhook](https://github.com/mcnaveen/health-connect-webhook) — ⭐81

**Язык:** Kotlin (Jetpack Compose + Material 3)
**Активность:** последний коммит **May 21, 2026** (вчера!)
**Show HN:** [январь 2026](https://news.ycombinator.com/item?id=46572102), [март 2026](https://hn.algolia.com/api/v1/search?query=health+connect+webhook) — автор активно продвигает

**Что делает:**
Android-приложение читает агрегированные данные из Health Connect и отправляет их POST-запросом на настроенный webhook URL. Три способа запуска синхронизации:
- Ручной (кнопка «Sync Now»)
- Интервальный через WorkManager (минимум 15 мин)
- По расписанию через AlarmManager (заданное время суток)

**Данные (24 типа):**
Steps, Sleep, Heart Rate, HRV (RMSSD), Distance, Active Calories, Total Calories, Weight, Height, Blood Pressure, Blood Glucose, SpO2, Body Temperature, Skin Temperature, Respiratory Rate, Resting Heart Rate, Exercise Sessions, Hydration, Nutrition, BMR, Body Fat, Lean Body Mass, VO2 Max, Bone Mass.

**Payload (JSON):**
```json
{
  "timestamp": "...",
  "app_version": "...",
  "steps": [...],
  "heart_rate": [...],
  ...
}
```

**Применимость к Botkin:** Максимальная. Нужно написать только один эндпоинт `/android_health_v1` (или `/health_connect_v1`) в `telegram-bot/webhook/`, который парсит этот формат и маппит на существующие таблицы Botkin (аналог `apple_health.py`). Пользователь устанавливает APK, вводит URL сервера и Bearer-токен.

**Плюсы:**
- Самое прямолинейное решение для задачи Botkin
- Очень активно разрабатывается
- 24 типа данных (больше, чем у любого конкурента в этом сегменте)
- Retry с exponential backoff (3 попытки)
- Backup/restore конфига (удобно для новых пользователей)
- Logs все запросы и ответы в приложении (удобно для дебага)

**Минусы:**
- 48-часовое rolling window — если телефон был оффлайн дольше, данные потеряются
- Doze mode может задерживать фоновую синхронизацию
- Только интервальная синхронизация (не event-driven)
- 81 звезда — проект небольшой, нет гарантии долгосрочной поддержки

---

### 2. [open-wearables](https://github.com/the-momentum/open-wearables) — ⭐1700

**Язык:** Python (FastAPI) + TypeScript (React) + Kotlin (Android SDK)
**Активность:** последний коммит **May 20, 2026** (вчера)

**Что делает:**
Self-hosted платформа для агрегации данных со всех wearable-источников: Garmin, Apple Health, Samsung Health, Google Health Connect, Polar, Suunto, Oura Ring. Нормализованный REST API поверх всех источников, webhook-уведомления, встроенный дашборд.

**Архитектура:**
FastAPI + PostgreSQL + Redis + Celery. Docker Compose (`docker compose up -d`). Android SDK — нативный Kotlin, синхронизирует Health Connect и Samsung Health в фоне. iOS — через React Native SDK.

**Применимость к Botkin:**
Скорее как источник вдохновения и возможный заменитель Botkin в будущем, чем как инструмент для немедленного использования. Можно было бы поднять рядом с Botkin и использовать как прокси для нормализации данных от Android. Но это полноценная альтернативная платформа — перекрытие с Botkin очень большое.

**Плюсы:**
- Наиболее полная self-hosted платформа в экосистеме (аналог OpenHealthKit)
- Работает со всеми крупными источниками, включая Garmin (очень актуально)
- Активное сообщество, 1700+ звёзд
- FastAPI + PostgreSQL — ровно тот же стек что у Botkin
- v0.4+ включает raw payload storage в S3

**Минусы:**
- Это отдельная полная платформа, не просто мост для Health Connect
- Android SDK — через React Native (не нативный Kotlin), требует дополнительной настройки
- Webhook events пока в разработке (не MVP-ready для Android)
- Требует инвайт-код для онбординга пользователей

---

### 3. [HCGateway](https://github.com/ShuchirJ/HCGateway) — ⭐403

**Язык:** JavaScript (51%) + Python (40%) + Kotlin (9%)
**Активность:** последний релиз **v2.2.1, May 31, 2025**

**Что делает:**
Двусторонний REST API-шлюз для Android Health Connect. Android-приложение каждые 2 часа шлёт данные на сервер. Сервер шифрует (Fernet) и хранит в MongoDB. Разработчики получают доступ через REST API с аутентификацией.

**Данные (35 типов):**
Всё что есть у #1 плюс reproductive health (менструация, овуляция).

**Архитектура:**
```
Android App → Python Server → MongoDB
Developer API ← Python Server
```
Деплой через Docker Compose. Требует Firebase (push-уведомления для Android-приложения).

**Применимость к Botkin:**
Ближайший аналог по задаче (Python backend + Android app → self-hosted server). Но MongoDB вместо PostgreSQL и обязательный Firebase делают это плохо совместимым с Botkin без переписывания.

**Плюсы:**
- Наиболее зрелое решение с двусторонней синхронизацией
- 35 типов данных
- Шифрование данных на сервере
- Большой стек — полная система

**Минусы:**
- MongoDB вместо PostgreSQL (не вписывается в Botkin)
- Требует Firebase для Android push — лишняя зависимость
- 2-часовой интервал синхронизации (долго)
- Последний релиз май 2025 — нет активности в 2026

---

### 4. [life-dashboard-companion-app](https://github.com/owen282000/life-dashboard-companion-app) — ⭐19

**Язык:** Kotlin (Jetpack Compose + Material 3)
**Активность:** последний релиз **v1.2.1, March 10, 2026**

**Что делает:**
Privacy-first Android-приложение, синхронизирует Health Connect + Screen Time на пользовательский webhook. 23 типа данных здоровья + Screen Time по приложениям (через UsageStatsManager). Несколько URL с разными HTTP-заголовками per category.

**Уникальная фича:** Screen Time — автоматически отправляет время экрана за 7 дней по приложениям. Аналог того что делает `scripts/import/activitywatch.py` в Botkin, но нативно на Android.

**Применимость к Botkin:**
Очень высокая. Особенно Screen Time — это то, чего у Botkin нет для Android-пользователей. Требует Android 14+ (API 34) — ограничение для части пользователей.

**Плюсы:**
- Screen Time — уникальная фича среди конкурентов
- Несколько webhook-URL с разными заголовками
- Чистый, минималистичный проект

**Минусы:**
- Требует Android 14+ (API 34) — только новые телефоны
- 19 звёзд, маленькое сообщество
- Нет активности после марта 2026

---

### 5. [TaskerHealthConnect](https://github.com/RafhaanShah/TaskerHealthConnect) — ⭐76

**Язык:** Kotlin (Tasker plugin)
**Активность:** последний коммит **March 1, 2026**

**Что делает:**
Плагин для Tasker (платное Android-приложение для автоматизации). Читает данные из Health Connect как JSON. Tasker сам может отправить HTTP POST запрос на любой URL.

**Как это работает для Botkin:**
```
Tasker Schedule (каждый час)
  → Action: TaskerHealthConnect → получить steps/heart_rate за последние 24ч как JSON
  → Action: HTTP Request POST https://health.orangegate.cc/android_health
             Headers: Authorization: Bearer TOKEN
             Body: [JSON из предыдущего шага]
```

**Применимость к Botkin:**
Хороший вариант для продвинутых пользователей, у которых уже есть Tasker. Максимальная гибкость — любой тип данных, любой интервал, любой постобработчик.

**Плюсы:**
- Максимальная гибкость (Tasker умеет всё)
- Не нужно устанавливать отдельное приложение если Tasker уже есть
- Поддерживает запись данных обратно в HC (write)
- Нет лимита в 48 часов

**Минусы:**
- Tasker платный (~$3.49)
- Требует настройки руками — не для обычных пользователей
- Плагин не умеет сам делать HTTP — нужен Tasker flow
- Health Connect API не поддерживает event-based triggers (только polling)

---

### 6. [HealthConnect_to_HomeAssistant](https://github.com/AyraHikari/HealthConnect_to_HomeAssistant) — ⭐41

**Язык:** Kotlin
**Активность:** последний релиз **v0.4, October 2025**

**Что делает:**
Синхронизирует Health Connect в Home Assistant как сенсоры. Пользователь вводит URL HA instance + Long-Lived Access Token. Данные появляются как HA-entities.

**Применимость к Botkin:**
Не прямая, но интересна как паттерн. Если у пользователя есть HA, можно настроить HA → webhook → Botkin через автоматизацию. Нативный HA Companion App уже поддерживает 11 Health Connect сенсоров (steps, heart rate, blood pressure, blood glucose, SpO2, distance, calories, VO2 Max, weight, floors, elevation).

**Плюсы:**
- Работает с нативным HA — никакой дополнительной инфры
- Если у пользователя есть HA, данные сразу попадают в историю

**Минусы:**
- Требует Home Assistant
- Непрямой путь к Botkin (нужна HA-автоматизация для проброса)
- HA Companion вероятно заменит этот репо в будущем

---

### 7. [openclaw-healthconnect-bridge](https://github.com/DavideGarbi/openclaw-healthconnect-bridge) — ⭐2

**Язык:** Kotlin (61%) + TypeScript (39%)
**Активность:** последний релиз **v0.2.0, March 30, 2026**

**Что делает:**
Мост Health Connect → OpenClaw AI assistant через `POST /health-connect/sync` с Bearer-токеном. Аналог Botkin-подхода, но заточен под другую платформу.

**Применимость к Botkin:**
Интересен как доказательство паттерна и как пример кода. PolyForm Noncommercial лицензия (ограничение на коммерческое использование). Код можно изучить как референс для написания своего клиента.

---

## Китайские источники (переведено)

**Landiannews.com** (крупный китайский IT-ресурс): Google добавил в Health Connect встроенный экспорт данных. Особенности:
- Поддерживает только Google Drive и Dropbox в качестве бекапа
- **Нет ручного экспорта** — только по расписанию (ежедневно/еженедельно/ежемесячно)
- Данные экспортируются как ZIP-архив
- Первые версии экспортировали 0KB (баг, исправлен)
- Google обосновывает ограничения соображениями приватности

**V2EX и sspai.com:** Нет обсуждений webhook-экспорта из Health Connect. Китайское сообщество больше обсуждает Xiaomi Mi Fitness и Huawei Health, которые используют собственные закрытые API, а не стандартный Health Connect.

---

## Сообщества и форумы

- **r/selfhosted** — крайне мало обсуждений Health Connect. Тема нишевая.
- **r/quantifiedself** — есть упоминания, но в основном про iOS HealthKit и Oura/Whoop
- **Home Assistant Community** — активные обсуждения ([тред с июня 2025](https://community.home-assistant.io/t/health-and-fitness-data-into-home-assistant-ha-companion-app-and-health-connect/905477)), фокус на интеграцию с HA, а не на raw webhook
- **HN** — автор health-connect-webhook постил дважды (январь и март 2026), оба раза без особого резонанса (1-2 upvote)
- **XDA Developers** — нет активных тредов по HC webhook export

**Вывод по сообществу:** ниша Health Connect → self-hosted webhook крайне мала. Большинство людей идут через HA Companion App или вообще не занимаются этим. Эта фича будет конкурентным преимуществом Botkin.

---

## Нативный экспорт Google (важный контекст)

Google добавил встроенный экспорт в Health Connect (Android 14+):
- Только Google Drive / Dropbox
- Только по расписанию, нет ручного экспорта
- ZIP-архив (не webhook, не API)
- Это НЕ замена для Botkin — это backup-инструмент, не real-time sync

---

## Рекомендация

**Не форкать. Строить эндпоинт на стороне Botkin-сервера.**

Причина: все существующие Android-приложения (health-connect-webhook, life-dashboard-companion-app) уже умеют отправлять данные на произвольный URL. Задача Botkin — принять этот payload, не создавать своё приложение.

**Конкретный план:**

1. **Шаг 1 (1-2 часа):** Создать `telegram-bot/webhook/android_health.py` — обработчик `POST /android_health_v1`. Принимает JSON-формат от `health-connect-webhook`, маппит на таблицы Botkin (шаги → `activity_log`, пульс → `activity_log`, вес → `weights`, давление → `blood_pressure_logs`). Аналог существующего `apple_health.py`.

2. **Шаг 2 (30 мин):** Задокументировать для пользователей (`docs/user_guide/android_setup.md`): установить APK, ввести URL сервера + Bearer-токен из `.env: APPLE_HEALTH_TOKEN` (тот же токен).

3. **Шаг 3 (опционально):** Для Игоря — Screen Time через `life-dashboard-companion-app` (если у него Android 14+). Добавить эндпоинт `/android_screen_time` аналогично.

**Не трогать:** HCGateway (MongoDB), Open Wearables (отдельная платформа), openclaw-bridge (нет совместимости).

**Если кто-то из пользователей использует Tasker** — TaskerHealthConnect + HTTP-таск в Tasker это самое гибкое решение, не требующее дополнительного APK.

---

## Следующие шаги для Botkin

- [ ] Создать `telegram-bot/webhook/android_health.py` — парсер формата `health-connect-webhook` (24 типа данных → таблицы Botkin)
- [ ] Зарегистрировать эндпоинт `/android_health_v1` в `main.py` / `webhook.py`
- [ ] Протестировать на реальном устройстве: установить [mcnaveen/health-connect-webhook](https://github.com/mcnaveen/health-connect-webhook) APK, настроить на `https://health.orangegate.cc/android_health_v1`
- [ ] Написать `docs/user_guide/android_health_connect.md` — инструкция для Олега/Андрея
- [ ] Опционально: добавить Screen Time endpoint для Android 14+ пользователей (`life-dashboard-companion-app`)
- [ ] Долгосрочно: следить за Open Wearables v0.5+ — когда Android webhook events стабилизируются, рассмотреть интеграцию как нормализующий слой для всех wearable источников

---

## Источники

- https://github.com/mcnaveen/health-connect-webhook
- https://github.com/owen282000/life-dashboard-companion-app
- https://github.com/ShuchirJ/HCGateway
- https://github.com/angeloanan/HealthConnectExports
- https://github.com/the-momentum/open-wearables
- https://github.com/AyraHikari/HealthConnect_to_HomeAssistant
- https://github.com/RafhaanShah/TaskerHealthConnect
- https://github.com/DavideGarbi/openclaw-healthconnect-bridge
- https://github.com/topics/health-connect
- https://community.home-assistant.io/t/health-and-fitness-data-into-home-assistant-ha-companion-app-and-health-connect/905477
- https://www.landiannews.com/archives/106620.html
- https://www.themomentum.ai/blog/open-wearables-0-3-android-google-health-connect-samsung-health-railway
