-- database/migrations/add_rls_biomarkers.sql
-- Добавляет RLS-изоляцию на таблицы с биомаркерами/композицией тела, которых
-- НЕ было в add_rls_policies.sql (там только 6 таблиц + agent_conversations).
-- blood_tests — самый чувствительный PHI (анализы крови), и до сих пор он не
-- покрыт ни одной политикой: при чтении ролью hv_app виден всем.
--
-- ⚠️ ВАЖНО — это НЕ самодостаточный фикс изоляции. На проде приложение ходит
-- ролью-владельцем `healthvault`, которая RLS ИГНОРИРУЕТ (см. шапку
-- add_rls_policies.sql). Поэтому:
--   1. Эти политики — no-op, пока приложение коннектится владельцем.
--   2. Чтобы RLS реально заработал, нужно ЛИБО переключить приложение на роль
--      hv_app (DATABASE_URL), ЛИБО включить FORCE ROW LEVEL SECURITY на таблицах.
--   3. И то, и другое требует аудита ВСЕХ путей чтения: дашборд
--      (webhook/dashboard.py → generate_dashboard_html) и админка читают БД БЕЗ
--      вызова set_user_session_var → под FORCE/hv_app они увидят 0 строк.
--      Сначала проставить RLS-контекст (или сервисную роль) на этих путях.
--
-- Применять ВРУЧНУЮ на сервере (как add_rls_policies.sql), не авто-миграцией:
--   docker exec -i healthvault_postgres psql -U healthvault -d healthvault \
--     -f /tmp/add_rls_biomarkers.sql

-- blood_tests: биомаркеры (PHI). FK по user_id = users.telegram_id.
ALTER TABLE blood_tests ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS user_isolation ON blood_tests;
CREATE POLICY user_isolation ON blood_tests
  FOR ALL TO hv_app
  USING (user_id = NULLIF(current_setting('app.user_id', TRUE), '')::bigint);

-- body_measurements: композиция тела (вес/жир/мышцы по сегментам).
ALTER TABLE body_measurements ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS user_isolation ON body_measurements;
CREATE POLICY user_isolation ON body_measurements
  FOR ALL TO hv_app
  USING (user_id = NULLIF(current_setting('app.user_id', TRUE), '')::bigint);

-- ── Опционально (включать ТОЛЬКО после аудита путей чтения, см. п.3 выше) ─────
-- Заставляет RLS применяться даже к владельцу таблицы (текущая прод-роль):
--   ALTER TABLE blood_tests        FORCE ROW LEVEL SECURITY;
--   ALTER TABLE body_measurements  FORCE ROW LEVEL SECURITY;
--   ALTER TABLE nutrition_log      FORCE ROW LEVEL SECURITY;
--   ALTER TABLE supplements_log    FORCE ROW LEVEL SECURITY;
--   ALTER TABLE weights            FORCE ROW LEVEL SECURITY;
--   ALTER TABLE activity_log       FORCE ROW LEVEL SECURITY;
--   ALTER TABLE blood_pressure_logs FORCE ROW LEVEL SECURITY;
--   ALTER TABLE user_settings      FORCE ROW LEVEL SECURITY;
