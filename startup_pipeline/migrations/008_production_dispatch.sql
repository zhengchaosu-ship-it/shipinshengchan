CREATE TABLE startup_production_dispatch (
 job_id TEXT PRIMARY KEY REFERENCES publish_jobs(job_id),
 plan_id TEXT NOT NULL REFERENCES publish_plans(plan_id),
 state TEXT NOT NULL CHECK(state IN ('QUEUED','CLAIMED','SCHEDULED_QUEUED','BLOCKED','SUBMIT_RESULT_UNCERTAIN')),
 worker_id TEXT, claim_token TEXT, context_json TEXT,
 created_at TEXT NOT NULL, claimed_at TEXT, completed_at TEXT, error_code TEXT,
 UNIQUE(claim_token)
);
CREATE TABLE startup_publish_config_audit (
 id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL REFERENCES publish_jobs(job_id),
 employee_id TEXT NOT NULL REFERENCES employees(employee_id),
 old_json TEXT NOT NULL, new_json TEXT NOT NULL, changed_at TEXT NOT NULL
);
CREATE INDEX startup_dispatch_plan_state ON startup_production_dispatch(plan_id,state);
