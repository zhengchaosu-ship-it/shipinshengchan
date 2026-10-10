-- 附加到现有render_jobs.db；jobs及业务operations.db结构不变。
CREATE TABLE IF NOT EXISTS lan_workers(
    worker_id TEXT PRIMARY KEY,details TEXT NOT NULL,last_heartbeat REAL NOT NULL,
    status TEXT NOT NULL,current_job_id TEXT);
CREATE TABLE IF NOT EXISTS lan_leases(
    job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),worker_id TEXT NOT NULL,
    claim TEXT NOT NULL,expires_at REAL NOT NULL,stage TEXT NOT NULL,details TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS lan_receipt_requests(
    job_id TEXT PRIMARY KEY,request_sha256 TEXT NOT NULL,response TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS lan_heartbeat_history(
    worker_id TEXT NOT NULL,timestamp TEXT NOT NULL,received_at REAL NOT NULL,
    status TEXT NOT NULL,current_job_id TEXT,PRIMARY KEY(worker_id,timestamp));
CREATE TABLE IF NOT EXISTS lan_schema_migrations(version INTEGER PRIMARY KEY,applied_at TEXT NOT NULL);
INSERT OR IGNORE INTO lan_schema_migrations VALUES(1,datetime('now'));
