-- Adds BMR source selection + activity_level for Mifflin-St Jeor calculator.
-- bmr_source = 'auto'  → use Garmin → Apple Health → default (current logic)
-- bmr_source = 'manual'→ use bmr_override + activity_avg_override entered by user

ALTER TABLE user_settings
  ADD COLUMN IF NOT EXISTS bmr_source VARCHAR(10) NOT NULL DEFAULT 'auto',
  ADD COLUMN IF NOT EXISTS activity_level VARCHAR(20),
  ADD COLUMN IF NOT EXISTS activity_avg_override INTEGER;

-- Backfill: if user already has bmr_override set, mark as manual.
UPDATE user_settings SET bmr_source = 'manual' WHERE bmr_override IS NOT NULL;
