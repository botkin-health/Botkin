-- Add onboarding state columns to users table (Sprint 1a Task 9)
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS onboarding_step VARCHAR(30) DEFAULT 'done',
  ADD COLUMN IF NOT EXISTS onboarding_data JSONB DEFAULT '{}'::jsonb;

-- Existing users are already onboarded
UPDATE users SET onboarding_step = 'done' WHERE onboarding_step IS NULL OR onboarding_step = '';
