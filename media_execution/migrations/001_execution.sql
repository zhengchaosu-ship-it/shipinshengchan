-- 只添加执行关联/租约/发布门；不导入或更新任何历史业务任务。
CREATE TABLE IF NOT EXISTS media_execution_schema(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS media_execution_jobs(
 job_type TEXT NOT NULL CHECK(job_type IN ('RENDER','PUBLISH')),
 job_id TEXT NOT NULL, worker_id TEXT NOT NULL, business_account_id TEXT NOT NULL,
 content_id TEXT NOT NULL, payload_json TEXT NOT NULL, created_at REAL NOT NULL,
 state TEXT NOT NULL, scheduled_at REAL, retry_not_before REAL NOT NULL DEFAULT 0,
 submit_attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(submit_attempt_count IN (0,1)),
 intent_json TEXT, provider_response TEXT, provider_task_id TEXT, provider_video_id TEXT,
 reconciliation_status TEXT, failure_domain TEXT, error_json TEXT,
 PRIMARY KEY(job_type,job_id));
CREATE UNIQUE INDEX IF NOT EXISTS media_execution_content_publish ON media_execution_jobs(content_id)
 WHERE job_type='PUBLISH';
CREATE TABLE IF NOT EXISTS media_execution_leases(
 worker_id TEXT PRIMARY KEY, job_type TEXT NOT NULL, job_id TEXT NOT NULL,
 lease_token TEXT NOT NULL UNIQUE, acquired_at REAL NOT NULL, heartbeat_at REAL NOT NULL,
 expires_at REAL NOT NULL, stage TEXT NOT NULL,
 FOREIGN KEY(job_type,job_id) REFERENCES media_execution_jobs(job_type,job_id));
CREATE TABLE IF NOT EXISTS media_account_publish_gates(
 business_account_id TEXT PRIMARY KEY, gate TEXT NOT NULL, provider_account_status TEXT NOT NULL,
 block_reason TEXT, provider_error TEXT, first_seen_at REAL, checked_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS media_publisher_infrastructure(
 worker_id TEXT PRIMARY KEY, state TEXT NOT NULL, reason TEXT, checked_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS media_execution_outputs(
 content_id TEXT PRIMARY KEY, render_job_id TEXT NOT NULL, worker_id TEXT NOT NULL,
 local_output_path TEXT NOT NULL, output_sha256 TEXT NOT NULL, media_json TEXT NOT NULL,
 render_completed_at REAL NOT NULL, archive_state TEXT NOT NULL DEFAULT 'ARCHIVE_PENDING',
 archive_receipt TEXT, archive_error TEXT);
CREATE TABLE IF NOT EXISTS media_execution_events(
 id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, job_type TEXT, job_id TEXT,
 event TEXT NOT NULL, evidence_json TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS media_execution_latch_monotonic BEFORE UPDATE OF submit_attempt_count ON media_execution_jobs
 WHEN NEW.submit_attempt_count < OLD.submit_attempt_count
 BEGIN SELECT RAISE(ABORT,'SUBMIT_ONCE_LATCH_CONSUMED'); END;
CREATE TRIGGER IF NOT EXISTS media_execution_intent_immutable BEFORE UPDATE OF intent_json ON media_execution_jobs
 WHEN OLD.intent_json IS NOT NULL AND NEW.intent_json IS NOT OLD.intent_json
 BEGIN SELECT RAISE(ABORT,'SUBMIT_INTENT_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS media_execution_identity_immutable BEFORE UPDATE ON media_execution_jobs
 WHEN NEW.job_type<>OLD.job_type OR NEW.job_id<>OLD.job_id OR NEW.worker_id<>OLD.worker_id
 OR NEW.content_id<>OLD.content_id OR NEW.business_account_id<>OLD.business_account_id
 OR NEW.payload_json<>OLD.payload_json
 OR (OLD.provider_task_id IS NOT NULL AND NEW.provider_task_id IS NOT OLD.provider_task_id)
 OR (OLD.provider_video_id IS NOT NULL AND NEW.provider_video_id IS NOT OLD.provider_video_id)
 BEGIN SELECT RAISE(ABORT,'EXECUTION_IDENTITY_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS media_execution_no_delete BEFORE DELETE ON media_execution_jobs
 BEGIN SELECT RAISE(ABORT,'EXECUTION_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS media_execution_events_no_update BEFORE UPDATE ON media_execution_events
 BEGIN SELECT RAISE(ABORT,'EXECUTION_AUDIT_APPEND_ONLY'); END;
CREATE TRIGGER IF NOT EXISTS media_execution_events_no_delete BEFORE DELETE ON media_execution_events
 BEGIN SELECT RAISE(ABORT,'EXECUTION_AUDIT_APPEND_ONLY'); END;
