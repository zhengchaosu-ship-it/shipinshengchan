CREATE TABLE startup_job_metadata_new (
 job_id TEXT PRIMARY KEY REFERENCES publish_jobs(job_id),content_id TEXT NOT NULL REFERENCES startup_contents(content_id),
 employee_id TEXT NOT NULL REFERENCES employees(employee_id),account_id TEXT NOT NULL REFERENCES xiaovcat_accounts(account_id),
 business_type TEXT NOT NULL CHECK(business_type='STARTUP'),source_plan_id TEXT NOT NULL REFERENCES publish_plans(plan_id),
 source_plan_item_id TEXT NOT NULL REFERENCES publish_plan_items(item_id),batch_id TEXT NOT NULL,
 composition_signature TEXT NOT NULL,publish_profile_id TEXT NOT NULL REFERENCES startup_publish_profiles(profile_id),
 topics_json TEXT NOT NULL,cover_mode TEXT NOT NULL,schedule_signature TEXT NOT NULL UNIQUE,
 dispatch_mode TEXT NOT NULL CHECK(dispatch_mode IN ('SIMULATION_ONLY','SINGLE_ACCEPTANCE','CONFIRMED_NOT_DISPATCHED'))
);
INSERT INTO startup_job_metadata_new SELECT * FROM startup_job_metadata;
DROP TABLE startup_job_metadata;
ALTER TABLE startup_job_metadata_new RENAME TO startup_job_metadata;
CREATE TABLE startup_plan_confirmations (
 plan_id TEXT PRIMARY KEY REFERENCES publish_plans(plan_id),
 employee_id TEXT NOT NULL REFERENCES employees(employee_id),confirmed_at TEXT NOT NULL,
 preview_receipt TEXT NOT NULL,prior_status TEXT NOT NULL,
 worker_dispatches INTEGER NOT NULL DEFAULT 0 CHECK(worker_dispatches=0)
);
