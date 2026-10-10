CREATE TABLE IF NOT EXISTS media_execution_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS media_execution_worker_health(worker_id TEXT PRIMARY KEY,received_at REAL NOT NULL,details_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS media_execution_receipts(worker_id TEXT NOT NULL,lease_token TEXT NOT NULL,kind TEXT NOT NULL,digest TEXT NOT NULL,response_json TEXT NOT NULL,PRIMARY KEY(worker_id,lease_token,kind));
CREATE TABLE IF NOT EXISTS media_execution_archive_jobs(content_id TEXT PRIMARY KEY,worker_id TEXT NOT NULL,destination TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'ARCHIVE_PENDING',updated_at REAL NOT NULL);
