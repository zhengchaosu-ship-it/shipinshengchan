-- 增量迁移：用户授权不变；运行态与轻量对账独立保存。
CREATE TABLE IF NOT EXISTS autopilot_account_runtime(
 account_id TEXT PRIMARY KEY, status TEXT NOT NULL,
 reason_code TEXT, human_message TEXT, action_required TEXT,
 paused_at REAL, resumed_at REAL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS media_reconciliation_leases(
 worker_id TEXT PRIMARY KEY, job_type TEXT NOT NULL, job_id TEXT NOT NULL,
 lease_token TEXT NOT NULL UNIQUE, acquired_at REAL NOT NULL, heartbeat_at REAL NOT NULL,
 expires_at REAL NOT NULL, stage TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS media_reconciliation_schedule(
 job_id TEXT PRIMARY KEY, next_check_at REAL NOT NULL, last_error TEXT);
CREATE TABLE IF NOT EXISTS production_faults(
 id INTEGER PRIMARY KEY AUTOINCREMENT, domain TEXT NOT NULL CHECK(domain IN ('JOB','ACCOUNT','SYSTEM')),
 account_id TEXT, job_id TEXT, reason_code TEXT NOT NULL, human_message TEXT NOT NULL,
 recorded_at REAL NOT NULL);
