-- 既有Job的公开观察、组合溯源和指标窗口；不另建发布队列，不修改历史任务。
CREATE TABLE IF NOT EXISTS production_publications(
 job_id TEXT PRIMARY KEY REFERENCES provider_publish_jobs(job_id),
 business_account_id TEXT NOT NULL, provider_account_id TEXT NOT NULL,
 provider_video_id TEXT NOT NULL, content_id TEXT NOT NULL, scheduled_at TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('WAITING_PUBLIC','PUBLISHED','STOPPED')),
 next_check_at TEXT NOT NULL, checked_at TEXT, published_at TEXT, evidence_json TEXT,
 composition_id TEXT, template_version INTEGER, trace_status TEXT NOT NULL,
 trace_json TEXT NOT NULL, last_error TEXT, created_at TEXT NOT NULL,
 UNIQUE(provider_account_id,provider_video_id));
CREATE TABLE IF NOT EXISTS production_metric_tasks(
 job_id TEXT NOT NULL REFERENCES production_publications(job_id), window_hours INTEGER NOT NULL CHECK(window_hours IN (2,24,72)),
 due_at TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('WAITING','RETRY','COMPLETE','LATE','UNAVAILABLE')),
 checked_at TEXT, snapshot_json TEXT, last_error TEXT, PRIMARY KEY(job_id,window_hours));
CREATE TABLE IF NOT EXISTS production_material_demands(
 account_id TEXT NOT NULL, local_day TEXT NOT NULL, slot_position TEXT NOT NULL,
 generated_at TEXT NOT NULL, payload_json TEXT NOT NULL, PRIMARY KEY(account_id,local_day,slot_position));
CREATE TABLE IF NOT EXISTS production_integration_audit(
 id INTEGER PRIMARY KEY, at TEXT NOT NULL, job_id TEXT, event TEXT NOT NULL, evidence_json TEXT NOT NULL);
CREATE VIEW IF NOT EXISTS production_metric_trace AS
 SELECT t.*,p.provider_video_id,p.business_account_id,p.provider_account_id,p.content_id,p.composition_id,
 p.template_version,p.published_at,p.trace_status,p.trace_json
 FROM production_metric_tasks t JOIN production_publications p USING(job_id);
CREATE TRIGGER IF NOT EXISTS production_publication_identity BEFORE UPDATE ON production_publications
 WHEN NEW.job_id<>OLD.job_id OR NEW.business_account_id<>OLD.business_account_id OR NEW.provider_account_id<>OLD.provider_account_id
 OR NEW.provider_video_id<>OLD.provider_video_id OR NEW.content_id<>OLD.content_id OR NEW.scheduled_at<>OLD.scheduled_at
 OR NEW.trace_json<>OLD.trace_json OR (OLD.published_at IS NOT NULL AND NEW.published_at IS NOT OLD.published_at)
 BEGIN SELECT RAISE(ABORT,'PUBLICATION_IDENTITY_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS production_publication_terminal BEFORE UPDATE OF state ON production_publications
 WHEN OLD.state='PUBLISHED' AND NEW.state<>OLD.state
 BEGIN SELECT RAISE(ABORT,'PUBLICATION_PUBLIC_EVIDENCE_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS production_integration_audit_immutable BEFORE UPDATE ON production_integration_audit
 BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
CREATE TRIGGER IF NOT EXISTS production_integration_audit_no_delete BEFORE DELETE ON production_integration_audit
 BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
