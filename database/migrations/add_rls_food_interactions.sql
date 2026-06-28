-- database/migrations/add_rls_food_interactions.sql
-- RLS-изоляция таблицы food_interactions (#193) — наблюдаемость пищевого
-- pipeline. Содержит сырые сообщения пользователя и ответы бота → PHI-чувствительно,
-- изолируем по user_id, как agent_conversations / blood_tests.
--
-- ⚠️ ВАЖНО — это НЕ самодостаточный фикс изоляции (как и add_rls_biomarkers.sql).
-- На проде приложение ходит ролью-владельцем `healthvault`, которая RLS ИГНОРИРУЕТ.
-- Поэтому:
--   1. Политика — no-op, пока приложение коннектится владельцем.
--   2. Чтобы RLS реально заработал — переключить приложение на роль hv_app
--      (DATABASE_URL) ЛИБО включить FORCE ROW LEVEL SECURITY, предварительно
--      проставив RLS-контекст (app.user_id) на всех путях чтения этой таблицы
--      (аудит-читалка /review-conversations, scripts/review_food_interactions.py).
--
-- Применять ВРУЧНУЮ на сервере (как add_rls_biomarkers.sql), не авто-миграцией:
--   docker exec -i healthvault_postgres psql -U healthvault -d healthvault \
--     -f /tmp/add_rls_food_interactions.sql

-- food_interactions: сырые пищевые сообщения + ответы бота. user_id = users.telegram_id.
ALTER TABLE food_interactions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS user_isolation ON food_interactions;
CREATE POLICY user_isolation ON food_interactions
  FOR ALL TO hv_app
  USING (user_id = NULLIF(current_setting('app.user_id', TRUE), '')::bigint);

-- ── Опционально (включать ТОЛЬКО после аудита путей чтения) ───────────────────
-- Заставляет RLS применяться даже к владельцу таблицы (текущая прод-роль):
--   ALTER TABLE food_interactions FORCE ROW LEVEL SECURITY;
