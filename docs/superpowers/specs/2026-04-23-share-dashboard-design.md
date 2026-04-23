# Share Dashboard — Design Spec
*2026-04-23*

## Цель
Каждый пользователь HealthVault может сгенерировать секретную ссылку на свой персональный дашборд здоровья и поделиться ею с друзьями.

## Архитектура

### URL
```
https://health.orangegate.cc/mc/{share_token}
```
`share_token` — UUID v4, хранится в БД. Кто знает URL — видит дашборд (security by obscurity). Пользователь может сбросить токен → старая ссылка перестаёт работать.

### Компоненты

#### 1. БД — новое поле `users.share_token`
```sql
ALTER TABLE users ADD COLUMN share_token VARCHAR(64) UNIQUE;
```
Nullable. UUID генерируется при первом `/share`. Один токен на пользователя.

#### 2. FastAPI endpoint `GET /mc/{token}`
Файл: `telegram-bot/webhook/dashboard.py`

Логика:
1. Lookup `user_id` по `share_token` в PostgreSQL
2. Если не найден → 404 (no hints)
3. Запросить агрегированные данные пользователя из БД
4. Сгенерировать HTML (адаптированный `build_html.py`)
5. Вернуть `HTMLResponse`

Регистрируется в существующем FastAPI `app` из `apple_health.py`.

#### 3. Генератор HTML `dashboard_generator.py`
Файл: `telegram-bot/dashboard_generator.py`

Читает из PostgreSQL (не из локальных JSON-файлов):
- `weights WHERE user_id=X ORDER BY measured_at` → вес/жир timeline
- `nutrition_log WHERE user_id=X` → ккал/белок/жир/углеводы по дням
- `supplements_log WHERE user_id=X` → дни добавок
- `activity_log WHERE user_id=X` → шаги, сон, HRV, стресс, Body Battery из `raw_data`
- `blood_tests WHERE user_id=X` → биомаркеры (если есть в БД)

Возвращает строку HTML. Дизайн — тот же Mission Control (dark Bloomberg, зелёный акцент).

#### 4. Бот-команда `/share`
Файл: `telegram-bot/handlers/commands.py`

Логика:
1. Если `users.share_token IS NULL` → `uuid.uuid4()` → сохранить в БД
2. Сформировать URL: `https://health.orangegate.cc/mc/{token}`
3. Отправить пользователю сообщение с URL + inline-кнопки:
   - `[🔗 Открыть дашборд]` — ссылка
   - `[🔄 Обновить данные]` — ничего не делает (данные live из БД)
   - `[🔁 Сбросить ссылку]` — генерирует новый UUID, старая ссылка умирает

## Поведение при просмотре
- Данные берутся из БД в момент открытия страницы → всегда свежие
- Нет кнопки "обновить" — не нужна
- Страница нейтральна: показывает то, что есть. Нет данных о весе → раздел скрыт.

## Что НЕ входит в MVP
- Кастомный дизайн или имя на дашборде (можно потом)
- Пароль на ссылку (UUID достаточен)
- Email-уведомления о просмотрах
- Аналитика просмотров

## Файловая структура (новые файлы)
```
telegram-bot/
  webhook/
    dashboard.py          # FastAPI endpoint GET /mc/{token}
  dashboard_generator.py  # HTML generator (DB → HTML string)
```

## Изменения в существующих файлах
```
database/models.py        # + share_token field на User
telegram-bot/handlers/commands.py  # + /share command handler
telegram-bot/webhook/apple_health.py  # + include_router(dashboard_router)
```

## Миграция БД
Простой `ALTER TABLE` — безопасен, nullable поле.
Запустить вручную или через скрипт миграции на сервере.
