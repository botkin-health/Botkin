-- Добавление полей BMR и активных калорий для пользователей без Garmin
-- Выполнить на сервере: docker exec healthvault_postgres psql -U healthvault -d healthvault -f /path/to/this/file
-- Или: psql -U healthvault -d healthvault -f add_user_calorie_settings.sql

ALTER TABLE users ADD COLUMN IF NOT EXISTS bmr FLOAT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS avg_active_calories FLOAT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS target_weight_kg FLOAT;
