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
- `id`: Integer (Primary Key)
- `user_id`: Integer (Foreign Key -> users.id)
- `date`: Date (Дата приема пищи)
- `time`: Time (Опциональное время)
- `meal_type`: String (Завтрак, Обед, Ужин, Перекус, Напиток)
- `food_name`: String (Что съедено)
- `weight_g`: Float (Вес в граммах)
- `calories`: Float
- `protein`, `fat`, `carbs`: Float
- `source`: String (Источник: \`manual\`, \`llm_photo\`, \`llm_text\`)
- `raw_text`: String (Оригинальное описание пользователя)

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
