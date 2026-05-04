-- Audit trail for admin DML access to sensitive tables.
-- Trigger fires on INSERT/UPDATE/DELETE by role 'healthvault' (admin).
-- SELECT logging handled via log_statement='all' on role level (goes to PG log, not this table).

CREATE TABLE IF NOT EXISTS audit_log (
  id            BIGSERIAL PRIMARY KEY,
  ts            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  db_user       TEXT        NOT NULL,
  query_type    TEXT        NOT NULL,  -- INSERT, UPDATE, DELETE
  table_name    TEXT,
  query_excerpt TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts DESC);
CREATE INDEX IF NOT EXISTS idx_audit_user_table ON audit_log(db_user, table_name);

-- Trigger function: only audits the admin role
CREATE OR REPLACE FUNCTION audit_admin_access() RETURNS TRIGGER AS $$
BEGIN
  IF current_user = 'healthvault' THEN
    INSERT INTO audit_log(db_user, query_type, table_name, query_excerpt)
    VALUES (
      current_user,
      TG_OP,
      TG_TABLE_NAME,
      LEFT(current_query(), 500)
    );
  END IF;
  RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Attach trigger to all sensitive tables
DO $$
DECLARE
  t TEXT;
BEGIN
  FOR t IN SELECT unnest(ARRAY['nutrition_log','supplements_log','weights','activity_log','blood_pressure_logs','users'])
  LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS audit_admin ON %I', t);
    EXECUTE format('CREATE TRIGGER audit_admin AFTER INSERT OR UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION audit_admin_access()', t);
  END LOOP;
END $$;

-- Optionally add user_settings if it exists
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'user_settings') THEN
    DROP TRIGGER IF EXISTS audit_admin ON user_settings;
    CREATE TRIGGER audit_admin AFTER INSERT OR UPDATE OR DELETE ON user_settings FOR EACH ROW EXECUTE FUNCTION audit_admin_access();
  END IF;
END $$;

-- audit_log itself: hv_app cannot read it (privacy — agents shouldn't see audit trail)
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY audit_admin_only ON audit_log FOR ALL TO hv_app USING (FALSE);

-- Enable SELECT logging for admin role
ALTER ROLE healthvault SET log_statement = 'all';
ALTER ROLE healthvault SET log_min_duration_statement = 0;
