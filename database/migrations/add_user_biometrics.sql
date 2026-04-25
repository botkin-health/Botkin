-- Migration: add biometric profile fields to users
-- Required for multi-user medical calculations (BMI, PhenoAge, LE8, Framingham)
-- birth_date → age computation (PhenoAge chrono_age, LE8, Framingham)
-- height_cm  → BMI (LE8 component)
-- sex        → reference ranges, Framingham risk model

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS birth_date     DATE,
    ADD COLUMN IF NOT EXISTS height_cm      SMALLINT,
    ADD COLUMN IF NOT EXISTS sex            VARCHAR(10) DEFAULT 'male';

-- Seed Alexander Lyskovsky's profile
UPDATE users
SET birth_date = '1977-05-15',
    height_cm  = 170,
    sex        = 'male'
WHERE telegram_id = 895655;
