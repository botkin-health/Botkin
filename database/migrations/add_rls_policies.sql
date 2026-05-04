-- database/migrations/add_rls_policies.sql
-- Creates hv_app role (app-level, RLS-restricted).
-- Admin role 'healthvault' bypasses RLS (it's the table owner).
--
-- Apply with:
--   PWD_VAL=$(grep '^HV_APP_DB_PASSWORD=' /opt/healthvault/.env | cut -d= -f2)
--   docker exec -i healthvault_postgres psql -U healthvault -d healthvault \
--     -v hv_app_pwd="$PWD_VAL" -f /tmp/add_rls_policies.sql

-- Create role (psql variable :hv_app_pwd must be passed via -v hv_app_pwd='...')
-- Using SELECT...WHERE NOT EXISTS + \gexec pattern for idempotency
SELECT 'CREATE ROLE hv_app LOGIN PASSWORD ' || quote_literal(:'hv_app_pwd')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hv_app')
\gexec

GRANT CONNECT ON DATABASE healthvault TO hv_app;
GRANT USAGE ON SCHEMA public TO hv_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO hv_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hv_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO hv_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO hv_app;

-- Restrict hv_app access to users table — read-only, no cross-user enumeration.
-- Agent containers should be able to SELECT their own user row (via FastAPI),
-- but must NOT insert, modify, or delete user records.
-- Note: SELECT on users is kept for now; RLS on users will be added in Sprint 2 if needed.
REVOKE INSERT, UPDATE, DELETE ON users FROM hv_app;

-- Enable RLS on all 6 data tables
ALTER TABLE nutrition_log         ENABLE ROW LEVEL SECURITY;
ALTER TABLE supplements_log       ENABLE ROW LEVEL SECURITY;
ALTER TABLE weights               ENABLE ROW LEVEL SECURITY;
ALTER TABLE activity_log          ENABLE ROW LEVEL SECURITY;
ALTER TABLE blood_pressure_logs   ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_settings         ENABLE ROW LEVEL SECURITY;

-- Drop existing policies if any (idempotent re-apply)
DROP POLICY IF EXISTS user_isolation ON nutrition_log;
DROP POLICY IF EXISTS user_isolation ON supplements_log;
DROP POLICY IF EXISTS user_isolation ON weights;
DROP POLICY IF EXISTS user_isolation ON activity_log;
DROP POLICY IF EXISTS user_isolation ON blood_pressure_logs;
DROP POLICY IF EXISTS user_isolation ON user_settings;

-- Create policies: hv_app can only see rows matching session variable
CREATE POLICY user_isolation ON nutrition_log
  FOR ALL TO hv_app
  USING (user_id = NULLIF(current_setting('app.user_id', TRUE), '')::bigint);

CREATE POLICY user_isolation ON supplements_log
  FOR ALL TO hv_app
  USING (user_id = NULLIF(current_setting('app.user_id', TRUE), '')::bigint);

CREATE POLICY user_isolation ON weights
  FOR ALL TO hv_app
  USING (user_id = NULLIF(current_setting('app.user_id', TRUE), '')::bigint);

CREATE POLICY user_isolation ON activity_log
  FOR ALL TO hv_app
  USING (user_id = NULLIF(current_setting('app.user_id', TRUE), '')::bigint);

CREATE POLICY user_isolation ON blood_pressure_logs
  FOR ALL TO hv_app
  USING (user_id = NULLIF(current_setting('app.user_id', TRUE), '')::bigint);

CREATE POLICY user_isolation ON user_settings
  FOR ALL TO hv_app
  USING (user_id = NULLIF(current_setting('app.user_id', TRUE), '')::bigint);
