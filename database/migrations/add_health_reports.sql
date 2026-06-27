-- Миграция: таблица health_reports (#203)
-- Применять: psql -U healthvault -d healthvault -f add_health_reports.sql
-- Alembic-эквивалент: rep0health01_add_health_reports.py

CREATE TABLE IF NOT EXISTS health_reports (
    id         SERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
    token      TEXT NOT NULL UNIQUE,
    html       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_health_reports_user_id ON health_reports(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS ix_health_reports_token ON health_reports(token);
