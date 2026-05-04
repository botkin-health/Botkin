-- Migration: add cohort/container/pack/jwt/byok columns to users
-- Sprint 1a — multi-user cohort support

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS cohort VARCHAR(20) NOT NULL DEFAULT 'external'
    CHECK (cohort IN ('owner', 'family', 'early_user', 'external')),
  ADD COLUMN IF NOT EXISTS container_id VARCHAR(50),
  ADD COLUMN IF NOT EXISTS container_port INTEGER,
  ADD COLUMN IF NOT EXISTS pack_name VARCHAR(50) NOT NULL DEFAULT 'generic'
    CHECK (pack_name IN ('generic', 'cardiac', 'bariatric', 'female-cycle')),
  ADD COLUMN IF NOT EXISTS jwt_secret VARCHAR(64),
  ADD COLUMN IF NOT EXISTS encrypted_openai_key TEXT,
  ADD COLUMN IF NOT EXISTS encrypted_anthropic_key TEXT;

-- Backfill existing users
UPDATE users SET cohort = 'owner',       pack_name = 'bariatric'    WHERE telegram_id = 895655;
UPDATE users SET cohort = 'family',      pack_name = 'female-cycle' WHERE telegram_id = 485132;
UPDATE users SET cohort = 'early_user',  pack_name = 'cardiac'      WHERE telegram_id = 836757955;
