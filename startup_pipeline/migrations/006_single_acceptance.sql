CREATE TABLE publish_plan_items_new (
 item_id TEXT PRIMARY KEY,plan_id TEXT NOT NULL REFERENCES publish_plans(plan_id),
 content_id TEXT NOT NULL,account_id TEXT NOT NULL REFERENCES xiaovcat_accounts(account_id),
 group_id TEXT REFERENCES xiaovcat_groups(group_id),video_path TEXT NOT NULL,scheduled_at TEXT NOT NULL,
 schedule_signature TEXT NOT NULL UNIQUE,job_id TEXT NOT NULL UNIQUE REFERENCES publish_jobs(job_id),
 test_only INTEGER NOT NULL DEFAULT 1 CHECK(test_only IN (0,1))
);
INSERT INTO publish_plan_items_new SELECT * FROM publish_plan_items;
DROP TABLE publish_plan_items;
ALTER TABLE publish_plan_items_new RENAME TO publish_plan_items;
CREATE TABLE startup_job_metadata_new (
 job_id TEXT PRIMARY KEY REFERENCES publish_jobs(job_id),content_id TEXT NOT NULL REFERENCES startup_contents(content_id),
 employee_id TEXT NOT NULL REFERENCES employees(employee_id),account_id TEXT NOT NULL REFERENCES xiaovcat_accounts(account_id),
 business_type TEXT NOT NULL CHECK(business_type='STARTUP'),source_plan_id TEXT NOT NULL REFERENCES publish_plans(plan_id),
 source_plan_item_id TEXT NOT NULL REFERENCES publish_plan_items(item_id),batch_id TEXT NOT NULL,
 composition_signature TEXT NOT NULL,publish_profile_id TEXT NOT NULL REFERENCES startup_publish_profiles(profile_id),
 topics_json TEXT NOT NULL,cover_mode TEXT NOT NULL,schedule_signature TEXT NOT NULL UNIQUE,
 dispatch_mode TEXT NOT NULL CHECK(dispatch_mode IN ('SIMULATION_ONLY','SINGLE_ACCEPTANCE'))
);
INSERT INTO startup_job_metadata_new SELECT * FROM startup_job_metadata;
DROP TABLE startup_job_metadata;
ALTER TABLE startup_job_metadata_new RENAME TO startup_job_metadata;
CREATE TABLE startup_real_acceptance_jobs (
 job_id TEXT PRIMARY KEY REFERENCES publish_jobs(job_id),content_id TEXT NOT NULL UNIQUE REFERENCES startup_contents(content_id),
 run_id TEXT NOT NULL UNIQUE,account_id TEXT NOT NULL REFERENCES xiaovcat_accounts(account_id),
 scope_json TEXT NOT NULL,created_at TEXT NOT NULL
);
