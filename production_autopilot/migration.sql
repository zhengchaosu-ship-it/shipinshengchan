CREATE TABLE IF NOT EXISTS production_incidents(
 incident_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, category TEXT NOT NULL,
 source_key TEXT NOT NULL, reason TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'OPEN',
 resume_allowed INTEGER NOT NULL DEFAULT 0, first_seen_at TEXT NOT NULL,
 last_seen_at TEXT NOT NULL, resolved_at TEXT, UNIQUE(account_id,category,source_key));
CREATE TABLE IF NOT EXISTS production_recovery_requests(
 request_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, requested_by TEXT NOT NULL,
 requested_at TEXT NOT NULL, state TEXT NOT NULL, finished_at TEXT, result_json TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_recovery ON production_recovery_requests(account_id) WHERE state='PENDING';
CREATE TABLE IF NOT EXISTS production_job_lineage(
 child_allocation_id TEXT PRIMARY KEY REFERENCES autopilot_allocations(allocation_id),
 parent_allocation_id TEXT NOT NULL UNIQUE REFERENCES autopilot_allocations(allocation_id),
 account_id TEXT NOT NULL, confirmed_by TEXT NOT NULL, confirmed_at TEXT NOT NULL,
 evidence_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS account_visual_profiles(
 business_account_id TEXT PRIMARY KEY, settings_json TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS production_health_snapshots(
 component TEXT PRIMARY KEY, state TEXT NOT NULL, checked_at TEXT NOT NULL, details_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS production_incident_account_state ON production_incidents(account_id,state);
CREATE INDEX IF NOT EXISTS plan_item_account_schedule ON publish_plan_items(account_id,scheduled_at);
