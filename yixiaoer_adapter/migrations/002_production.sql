CREATE TABLE IF NOT EXISTS provider_production_previews (
 plan_id TEXT PRIMARY KEY, employee_id TEXT NOT NULL REFERENCES employees(employee_id),
 content_ids_json TEXT NOT NULL, payload_json TEXT NOT NULL,
 profile_id TEXT NOT NULL, preparation_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS provider_plan_authorizations (
 plan_id TEXT PRIMARY KEY REFERENCES publish_plans(plan_id),
 employee_id TEXT NOT NULL REFERENCES employees(employee_id),
 content_ids_json TEXT NOT NULL, confirmed_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS provider_authorization_no_update BEFORE UPDATE ON provider_plan_authorizations
 BEGIN SELECT RAISE(ABORT,'PROVIDER_CONFIRM_AUTHORIZATION_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS provider_authorization_no_delete BEFORE DELETE ON provider_plan_authorizations
 BEGIN SELECT RAISE(ABORT,'PROVIDER_CONFIRM_AUTHORIZATION_IMMUTABLE'); END;
