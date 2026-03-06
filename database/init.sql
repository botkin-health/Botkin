-- SQL script for creating database schema
-- This file can be used to initialize PostgreSQL database

-- Create tables (SQLAlchemy will handle this, but keeping for reference)

CREATE TABLE IF NOT EXISTS users (
    telegram_id BIGINT PRIMARY KEY,
    username VARCHAR(255),
    first_name VARCHAR(255),
    last_name VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE,
    role VARCHAR(50) DEFAULT 'user',
    registered_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_active TIMESTAMP WITH TIME ZONE,
    timezone VARCHAR(50) DEFAULT 'Europe/Moscow',
    health_token VARCHAR(255) UNIQUE,
    garmin_email VARCHAR(255),
    garmin_password VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS nutrition_log (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
    date DATE NOT NULL,
    meal_time TIME,
    meal_name VARCHAR(255),
    items JSONB NOT NULL,
    totals JSONB NOT NULL,
    photo_paths TEXT[],
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, date, meal_time, meal_name)
);
CREATE INDEX IF NOT EXISTS idx_nutrition_user_date ON nutrition_log(user_id, date);

CREATE TABLE IF NOT EXISTS weights (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
    measured_at TIMESTAMP WITH TIME ZONE NOT NULL,
    weight FLOAT NOT NULL,
    body_fat FLOAT,
    muscle_mass FLOAT,
    water FLOAT,
    bmi FLOAT,
    visceral_fat INTEGER,
    bone_mass FLOAT,
    source VARCHAR(50),
    UNIQUE(user_id, measured_at)
);
CREATE INDEX IF NOT EXISTS idx_weights_user_date ON weights(user_id, measured_at);

CREATE TABLE IF NOT EXISTS supplements_log (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
    date DATE NOT NULL,
    time TIME,
    supplement_name VARCHAR(255) NOT NULL,
    dosage VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_supplements_user_date ON supplements_log(user_id, date);

CREATE TABLE IF NOT EXISTS activity_log (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
    date DATE NOT NULL,
    steps INTEGER,
    active_calories FLOAT,
    total_calories FLOAT,
    bmr_calories FLOAT,
    distance_km FLOAT,
    sleep_hours FLOAT,
    heart_rate_avg INTEGER,
    hrv INTEGER,
    stress_level INTEGER,
    source VARCHAR(50) DEFAULT 'apple_health',
    raw_data JSONB,
    synced_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, date)
);
CREATE INDEX IF NOT EXISTS idx_activity_user_date ON activity_log(user_id, date);

CREATE TABLE IF NOT EXISTS blood_tests (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
    test_date DATE NOT NULL,
    test_type VARCHAR(100),
    values JSONB NOT NULL,
    file_path TEXT,
    status VARCHAR(50) DEFAULT 'current',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_blood_tests_user_date ON blood_tests(user_id, test_date);

CREATE TABLE IF NOT EXISTS body_measurements (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
    date DATE NOT NULL,
    waist_cm FLOAT,
    neck_cm FLOAT,
    hips_cm FLOAT,
    chest_cm FLOAT,
    thigh_cm FLOAT,
    biceps_cm FLOAT,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_measurements_user_date ON body_measurements(user_id, date);
