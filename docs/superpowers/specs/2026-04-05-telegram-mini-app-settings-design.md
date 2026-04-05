# Telegram Mini App — Настройки NutriLogBot

**Дата:** 2026-04-05
**Статус:** Согласован, готов к реализации

---

## Цель

Панель настроек внутри Telegram, открывается кнопкой меню бота. Позволяет каждому пользователю управлять своим списком добавок, параметрами питания и уведомлениями — без правки кода.

Главная боль, которую решает: список добавок сейчас захардкожен в коде, у каждого пользователя свой стек, он меняется. Плюс Ника хочет скрыть шкалу-бюджет калорий.

---

## Архитектура

### Стек

| Слой | Что |
|---|---|
| Frontend | Один файл `webapp/index.html` (~300 строк HTML/CSS/JS) |
| Хостинг | FastAPI `StaticFiles` на существующем сервере (`health.orangegate.cc/webapp/`) |
| Backend | Новый endpoint `GET/POST /api/settings` в существующем FastAPI (`telegram-bot/webhook_server.py`) |
| БД | Новая таблица `user_settings` в PostgreSQL |
| Авторизация | Telegram `initData` HMAC-SHA256, ключ — bot token |
| Точка входа | BotFather Menu Button → URL Mini App |

### Поток данных

```
Пользователь нажимает кнопку меню в боте
    → Telegram открывает WebView с health.orangegate.cc/webapp/
    → JS читает window.Telegram.WebApp.initData (подписанный user_id)
    → GET /api/settings (Authorization: tma <initData>)
    → Сервер проверяет HMAC, извлекает user_id
    → Возвращает JSON с настройками пользователя
    → Пользователь редактирует, нажимает «Сохранить»
    → POST /api/settings → сохраняется в user_settings
    → Бот читает настройки при каждой команде /day, /vitamins
```

---

## База данных

### Таблица `user_settings`

```sql
CREATE TABLE user_settings (
    user_id         BIGINT PRIMARY KEY REFERENCES users(telegram_id),
    show_calorie_budget_bar     BOOLEAN NOT NULL DEFAULT TRUE,
    bmr_override                INTEGER,          -- NULL = использовать Garmin
    target_weight_kg            FLOAT,
    target_weight_date          DATE,
    supplement_reminders_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    supplement_reminder_time    TIME NOT NULL DEFAULT '08:00',
    supplements                 JSONB NOT NULL DEFAULT '[]',
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### Формат `supplements` (JSONB)

```json
[
  {"name": "Псиллиум",    "slot": "morning_before"},
  {"name": "Витамин D3",  "slot": "morning_with"},
  {"name": "Омега 3",     "slot": "morning_with"},
  {"name": "Plant Sterols","slot": "morning_with"},
  {"name": "Метилфолат",  "slot": "morning_with"},
  {"name": "Plant Sterols","slot": "evening"},
  {"name": "Магний",      "slot": "evening"},
  {"name": "Креатин",     "slot": "evening"}
]
```

Слоты: `morning_before` | `morning_with` | `evening`

---

## UI — структура экранов

### Главный экран (плитки 2×2)

```
┌─────────────┬─────────────┐
│  🥗 Питание  │  💊 Добавки  │
│ BMR · шкала │  8 активных │
├─────────────┼─────────────┤
│ 🔔 Уведомл. │  📖 Справка  │
│   Выкл      │             │
└─────────────┴─────────────┘
```

### Раздел «Питание»

- **BMR** — поле ввода числа (ккал/день). Если настроен Garmin: показывает текущее значение с меткой «из Garmin». Кнопка «🧮 Рассчитать» разворачивает мини-форму (рост/вес/возраст) и заполняет поле по формуле Миффлина-Сан Жеора.
- **Цель по весу** — числовое поле (кг) + поле даты (дедлайн).
- **Шкала калорий в /day** — тоггл (по умолчанию: вкл). Скрывает полоску 🟩🟥 с процентами в ответе `/day`. Добавлено по просьбе Ники.

### Раздел «Добавки»

- Список сгруппирован по трём слотам: ☀️ Утро (до еды) / 🌅 Утро (с завтраком) / 🌙 Вечер.
- Каждый элемент: название + кнопка ✕ (удалить).
- Кнопка «+ Добавить добавку» → поле ввода названия + выбор слота → добавляет в список.
- Кнопка «Сохранить» записывает весь список в `supplements` JSONB.
- **Миграция при первом открытии:** если в `user_settings` нет записи, создаётся с дефолтным списком из текущего кода `supplements.py`.

### Раздел «Уведомления»

- **Напоминание о добавках** — тоггл (по умолчанию: **выкл**) + поле времени (08:00). Бот присылает сообщение в указанное время. Реализация: APScheduler внутри бота (добавляется к существующему `asyncio.gather()`), при старте создаёт job на каждого пользователя с `enabled=True`.
- **Утренний брифинг** — тоггл, задизейблен с меткой «скоро». Задел на будущее.

### Раздел «Справка»

Статический текст, четыре блока:

1. **Как логировать еду** — 4 способа: текст, фото тарелки, фото упаковки, голосовое сообщение.
2. **Как отмечать добавки** — написать названия в чат, список настраивается выше.
3. **Команды бота** — `/day`, `/week`, `/vitamins`, `/settings` с описанием.
4. **Как считается лимит калорий** — 14-дневное среднее Garmin × 0.85, fallback на BMR из настроек.

---

## Изменения в боте

### `SupplementService` (`core/health/supplements.py`)

Перестаёт читать захардкоженный список. При инициализации:
1. Читает `user_settings.supplements` для данного `user_id`.
2. Если записи нет → мигрирует дефолтный список в `user_settings`, возвращает его.

### `format_budget_line()` (`core/health/caloric_budget.py`)

Добавляется параметр `show_bar: bool`. Если `False` — возвращает только текст без полоски. Значение читается из `user_settings.show_calorie_budget_bar`.

### `cmd_day()` (`telegram-bot/handlers/commands.py`)

Читает `show_calorie_budget_bar` из `user_settings` и передаёт в `format_budget_line()`.

---

## Авторизация (Telegram WebApp)

```python
import hmac, hashlib

def verify_telegram_init_data(init_data: str, bot_token: str) -> dict:
    # Парсим init_data, извлекаем hash
    # Считаем HMAC-SHA256(data_check_string, HMAC-SHA256("WebAppData", bot_token))
    # Сравниваем с hash из init_data
    # Возвращаем распарсенный user dict (id, first_name, username)
```

Бот-токен уже есть в `.env` как `BOT_TOKEN`.

---

## Файловая структура (новые файлы)

```
telegram-bot/
  webapp/
    index.html          ← весь фронтенд (~300 строк)
  webhook_server.py     ← добавить /api/settings endpoint (уже существует)

database/
  models.py             ← добавить UserSettings модель
  crud.py               ← добавить get/upsert user_settings

core/health/
  supplements.py        ← читать из user_settings вместо хардкода
  caloric_budget.py     ← добавить параметр show_bar
```

---

## Значения по умолчанию

| Настройка | По умолчанию |
|---|---|
| `show_calorie_budget_bar` | `True` |
| `bmr_override` | `NULL` (используется Garmin) |
| `supplement_reminders_enabled` | `False` |
| `supplement_reminder_time` | `08:00` |
| `supplements` | Текущий захардкоженный список |

---

## Что не входит в v1

- Дни недели для отдельных добавок (можно добавить в v2)
- Вечерний чекин и утренний брифинг (задел есть, тоггл задизейблен)
- Push-уведомления через Firebase (напоминания — через бот-сообщение, не push)
- Тема оформления (светлая/тёмная)
