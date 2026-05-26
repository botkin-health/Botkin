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

-- Backfill existing users (one-time data migration, executed on initial deployment)
-- UPDATE users SET cohort = 'owner', pack_name = ... WHERE telegram_id = <owner_id>;
-- UPDATE users SET cohort = 'family', pack_name = ... WHERE telegram_id = <family_member_id>;
-- UPDATE users SET cohort = 'early_user', pack_name = ... WHERE telegram_id = <early_user_id>;
-- Run onboard_family_user.py to configure users in new deployments.
