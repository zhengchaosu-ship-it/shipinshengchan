CREATE TABLE yixiaoer_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE provider_account_bindings (
 business_account_id TEXT NOT NULL REFERENCES xiaovcat_accounts(account_id),
 platform TEXT NOT NULL, provider TEXT NOT NULL CHECK(provider='yixiaoer'),
 provider_account_id TEXT NOT NULL, provider_account_status TEXT NOT NULL,
 provider_last_verified_at TEXT, raw_account_json TEXT NOT NULL,
 PRIMARY KEY(business_account_id,provider), UNIQUE(provider,provider_account_id)
);
CREATE TABLE provider_publish_jobs (
 job_id TEXT PRIMARY KEY REFERENCES publish_jobs(job_id),
 plan_id TEXT NOT NULL REFERENCES publish_plans(plan_id),
 provider TEXT NOT NULL DEFAULT 'yixiaoer', provider_account_id TEXT NOT NULL,
 state TEXT NOT NULL, worker_id TEXT, claim_token TEXT,
 submit_attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(submit_attempt_count IN (0,1)),
 provider_task_set_id TEXT UNIQUE, provider_task_id TEXT UNIQUE,
 provider_video_id TEXT, provider_video_url TEXT,
 provider_status TEXT, provider_stage_status TEXT,
 provider_submitted_at TEXT, provider_last_checked_at TEXT,
 provider_raw_status TEXT, payload_sha256 TEXT, request_hash TEXT,
 video_sha256 TEXT NOT NULL, intent_json TEXT, last_error TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE provider_audit_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT REFERENCES publish_jobs(job_id),
 business_account_id TEXT, event TEXT NOT NULL, previous_state TEXT,
 new_state TEXT, recorded_at TEXT NOT NULL, evidence_json TEXT NOT NULL
);
CREATE TRIGGER provider_audit_no_update BEFORE UPDATE ON provider_audit_events
 BEGIN SELECT RAISE(ABORT,'PROVIDER_AUDIT_APPEND_ONLY'); END;
CREATE TRIGGER provider_audit_no_delete BEFORE DELETE ON provider_audit_events
 BEGIN SELECT RAISE(ABORT,'PROVIDER_AUDIT_APPEND_ONLY'); END;
CREATE TRIGGER provider_submit_latch_monotonic BEFORE UPDATE OF submit_attempt_count ON provider_publish_jobs
 WHEN NEW.submit_attempt_count < OLD.submit_attempt_count
 BEGIN SELECT RAISE(ABORT,'PROVIDER_SUBMIT_LATCH_CONSUMED'); END;
CREATE TRIGGER provider_job_no_delete BEFORE DELETE ON provider_publish_jobs
 BEGIN SELECT RAISE(ABORT,'PROVIDER_JOB_HISTORY_IMMUTABLE'); END;
CREATE TRIGGER provider_job_identity_immutable BEFORE UPDATE ON provider_publish_jobs
 WHEN NEW.job_id<>OLD.job_id OR NEW.plan_id<>OLD.plan_id OR NEW.provider_account_id<>OLD.provider_account_id
 OR (OLD.provider_task_set_id IS NOT NULL AND NEW.provider_task_set_id IS NOT OLD.provider_task_set_id)
 OR (OLD.provider_task_id IS NOT NULL AND NEW.provider_task_id IS NOT OLD.provider_task_id)
 OR (OLD.provider_video_id IS NOT NULL AND NEW.provider_video_id IS NOT OLD.provider_video_id)
 BEGIN SELECT RAISE(ABORT,'PROVIDER_JOB_IDENTITY_IMMUTABLE'); END;
CREATE TABLE yixiaoer_canary_plans (
 plan_id TEXT PRIMARY KEY, employee_id TEXT NOT NULL REFERENCES employees(employee_id),
 content_ids_json TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
);
