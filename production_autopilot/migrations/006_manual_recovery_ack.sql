-- 仅增加Server恢复证据；不更新历史任务/授权或005恢复检查。
CREATE TABLE IF NOT EXISTS account_manual_recovery_schema(version INTEGER PRIMARY KEY,sql_sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS account_recovery_probe_versions(
 check_id TEXT PRIMARY KEY,account_id TEXT NOT NULL,generation_json TEXT NOT NULL,
 FOREIGN KEY(check_id) REFERENCES account_recovery_checks(check_id));
CREATE TABLE IF NOT EXISTS account_manual_recovery_acks(
 manual_recovery_ack_id TEXT PRIMARY KEY,check_id TEXT NOT NULL UNIQUE,
 manual_recovery_ack_at REAL NOT NULL,business_account_id TEXT NOT NULL,provider_account_id TEXT NOT NULL,
 requested_by TEXT NOT NULL,previous_block_reason TEXT,probe_result TEXT NOT NULL CHECK(probe_result='UNKNOWN'),
 generation_before_json TEXT NOT NULL,generation_after_json TEXT NOT NULL,result_json TEXT NOT NULL,
 FOREIGN KEY(check_id) REFERENCES account_recovery_checks(check_id));
CREATE TABLE IF NOT EXISTS account_manual_recovery_submit_links(
 job_id TEXT PRIMARY KEY,manual_recovery_ack_id TEXT NOT NULL,submit_intent_at REAL NOT NULL,
 FOREIGN KEY(manual_recovery_ack_id) REFERENCES account_manual_recovery_acks(manual_recovery_ack_id));
CREATE TABLE IF NOT EXISTS account_manual_recovery_outcomes(
 manual_recovery_ack_id TEXT PRIMARY KEY,job_id TEXT,observed_at REAL NOT NULL,outcome TEXT NOT NULL,
 evidence_json TEXT NOT NULL,FOREIGN KEY(manual_recovery_ack_id) REFERENCES account_manual_recovery_acks(manual_recovery_ack_id));
CREATE TABLE IF NOT EXISTS account_manual_recovery_projection(
 business_account_id TEXT PRIMARY KEY,manual_recovery_ack_id TEXT NOT NULL,state_json TEXT NOT NULL,updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS server_outbox(
 event_id TEXT PRIMARY KEY,event_type TEXT NOT NULL,aggregate_id TEXT NOT NULL,
 idempotency_key TEXT NOT NULL UNIQUE,payload_json TEXT NOT NULL,payload_sha256 TEXT NOT NULL,
 created_at REAL NOT NULL,processed_at REAL,attempt_count INTEGER NOT NULL DEFAULT 0,
 last_error TEXT,next_attempt_at REAL NOT NULL DEFAULT 0,lease_token TEXT,lease_expires_at REAL);
CREATE TABLE IF NOT EXISTS server_action_inbox(
 consumer TEXT NOT NULL,event_id TEXT NOT NULL,payload_sha256 TEXT NOT NULL,processed_at REAL NOT NULL,
 PRIMARY KEY(consumer,event_id));
