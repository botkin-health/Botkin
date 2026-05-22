-- Migration: extend pack_name CHECK to allow 'respiratory_allergic'
-- Date: 2026-05-22
-- Context: New pack introduced in core/packs.py for users with asthma + allergy
-- history + regular screening focus (vitamin D, tick antibodies). First user:
-- Igor Lyskovsky (telegram_id 830908046). See:
--   docs/superpowers/specs/2026-05-22-igor-botkin-onboarding-design.md

ALTER TABLE users DROP CONSTRAINT IF EXISTS users_pack_name_check;
ALTER TABLE users ADD CONSTRAINT users_pack_name_check
  CHECK (pack_name IN ('generic', 'cardiac', 'bariatric', 'female-cycle', 'respiratory_allergic'));
