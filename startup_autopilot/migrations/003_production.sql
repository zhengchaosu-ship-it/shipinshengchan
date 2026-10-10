-- operations.db增量迁移；既有Plan/Job不更新。
INSERT OR IGNORE INTO startup_publish_profiles VALUES('AUTOPILOT_DEFAULT','起号托管','','','[]','DEFAULT',strftime('%Y-%m-%dT%H:%M:%S+00:00','now'));
CREATE TABLE IF NOT EXISTS autopilot_authorizations(
 account_id TEXT PRIMARY KEY, employee_id TEXT NOT NULL, provider_account_id TEXT NOT NULL,
 status TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0, template_version INTEGER NOT NULL,
 template_hash TEXT NOT NULL, config_hash TEXT NOT NULL, config_json TEXT NOT NULL,
 autopilot_confirmed_by TEXT NOT NULL, autopilot_confirmed_at TEXT NOT NULL,
 updated_at TEXT NOT NULL, attention_reason TEXT, finish_choice TEXT);
CREATE TABLE IF NOT EXISTS autopilot_allocations(
 allocation_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, local_day TEXT NOT NULL,
 scheduled_at TEXT NOT NULL, composition_signature TEXT NOT NULL, template_version INTEGER NOT NULL,
 proposal_json TEXT NOT NULL, authorization_hash TEXT NOT NULL, state TEXT NOT NULL,
 generation_context_json TEXT, content_id TEXT UNIQUE, render_job_id TEXT,
 plan_id TEXT UNIQUE, job_id TEXT UNIQUE, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(account_id,scheduled_at), UNIQUE(account_id,composition_signature));
CREATE TABLE IF NOT EXISTS autopilot_events(
 event_id INTEGER PRIMARY KEY, account_id TEXT NOT NULL, actor_id TEXT NOT NULL,
 event TEXT NOT NULL, recorded_at TEXT NOT NULL, evidence_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS autopilot_metrics(
 account_id TEXT NOT NULL,work_id TEXT NOT NULL,window_hours INTEGER NOT NULL,
 snapshot_json TEXT NOT NULL, recorded_at TEXT NOT NULL,
 PRIMARY KEY(account_id,work_id,window_hours));
CREATE TRIGGER IF NOT EXISTS autopilot_events_immutable_update BEFORE UPDATE ON autopilot_events BEGIN SELECT RAISE(ABORT,'APPEND_ONLY_AUTOPILOT_AUDIT'); END;
CREATE TRIGGER IF NOT EXISTS autopilot_events_immutable_delete BEFORE DELETE ON autopilot_events BEGIN SELECT RAISE(ABORT,'APPEND_ONLY_AUTOPILOT_AUDIT'); END;
