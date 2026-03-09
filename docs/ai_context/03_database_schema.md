# Схемы Данных (Database Schema)

Проект HealthVault использует PostgreSQL для хранения основной информации. Взаимодействие происходит через SQLAlchemy.
Ниже представлена структура основных таблиц для понимания SQL-запросов и связей.

## 1. Таблица `users`
Хранит телеграм-пользователей бота (whitelist).
- `id`: Integer (Primary Key)
- `telegram_id`: BigInteger (Unique, Not Null)
- `username`: String
- `first_name`: String
- `is_active`: Boolean
- `target_calories`: Integer (Целевая норма калорий)
- `target_protein`: Integer
- `target_fat`: Integer
- `target_carbs`: Integer

## 2. Таблица `nutrition_log`
Хранит логи приемов пищи (ручной ввод, парсинг чека/фото).

> [!WARNING]
> **КБЖУ не в отдельных колонках!** Значения хранятся в JSONB поле `totals`.
> Правильный доступ: `(totals->>'calories')::numeric` — НЕ `calories` напрямую.
> Схема была изменена в процессе разработки; старые файлы документации неактуальны.

Реальная схема (верифицировано `\d nutrition_log`, 2026-03-10):
- `id`: Integer (Primary Key, автоинкремент)
- `user_id`: BigInteger (Foreign Key → `users.telegram_id` — **НЕ** `users.id`!)
- `date`: Date (NOT NULL — дата приёма пищи)
- `meal_time`: Time (опционально — время приёма)
- `meal_name`: String(255) (опционально — название блюда/приёма)
- `items`: JSONB (NOT NULL — список продуктов с детальным КБЖУ каждого)
- `totals`: JSONB (NOT NULL — суммарное КБЖУ за один приём пищи)
- `photo_paths`: Text[] (пути к фото, если парсинг из фото)
- `created_at`: TimestampTZ (автоматически — время создания записи)

**Структура поля `totals`:**
```json
{"calories": 450.0, "protein": 32.5, "fat": 18.0, "carbs": 41.0}
```

**Правильный SQL для суммирования по дням:**
```sql
SELECT
  date,
  COUNT(*) AS meal_entries,
  ROUND(SUM((totals->>'calories')::numeric), 0) AS kcal,
  ROUND(SUM((totals->>'protein')::numeric), 1) AS protein,
  ROUND(SUM((totals->>'fat')::numeric), 1)     AS fat,
  ROUND(SUM((totals->>'carbs')::numeric), 1)   AS carbs
FROM nutrition_log
WHERE user_id = 895655
  AND date >= '2026-01-06'
GROUP BY date
ORDER BY date;
```

**Уникальный индекс**: `(user_id, date, meal_time, meal_name)` — защита от дублей.
**Покрытие**: 63/63 дней с 2026-01-06 по 2026-03-09 (Alex, user_id=895655).

## 3. Таблица `weights`
История взвешиваний (в том числе с умных весов).
- `id`: Integer (Primary Key)
- `user_id`: Integer (Foreign Key -> users.id)
- `date`: Date
- `time`: Time
- `weight_kg`: Float
- `fat_percent`: Float (Опционально)
- `muscle_kg`: Float (Опционально)
- `water_percent`: Float (Опционально)
- `source`: String (\`manual\`, \`smart_scale\`, \`apple_health\`)

## 4. Таблица `supplements_log`
Учет приема витаминов, бадов, таблеток.
- `id`: Integer (Primary Key)
- `user_id`: Integer (Foreign Key -> users.id)
- `date`: Date
- `time`: Time
- `name`: String (Например: "Vitamin D3", "Omega-3")
- `dosage`: String (Например: "5000 IU", "2 pills")
- `source`: String

## 5. Таблица `activity_log`
Логи тренировок и сожженных калорий.
- `id`: Integer (Primary Key)
- `user_id`: Integer (Foreign Key -> users.id)
- `date`: Date
- `activity_type`: String (Например: "Running", "Walking", "Strength")
- `duration_min`: Integer
- `calories_burned`: Float
- `source`: String (\`garmin\`, \`apple_health\`, \`manual\`)

## Правила работы с датами и временем
- По умолчанию бот оперирует таймзоной сервера (или "Europe/Moscow", если задано явно).
- Запросы SQL для агрегации (например, функция `get_daily_stats()` в `database/crud.py`) фильтруются строго по полю `date` (для текущего или запрошенного дня).
- При парсинге данных из внешних систем (Garmin, Netatmo) временные метки (timestamp) должны конвертироваться в локальное время (Local Timezone), прежде чем будут записаны в `Date`/`Time` колонки.
