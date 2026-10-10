CREATE TABLE startup_batches (
    batch_id TEXT PRIMARY KEY, employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    manifest_path TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, materials_json TEXT NOT NULL
);
CREATE TABLE startup_generation_runs (
    generation_id TEXT PRIMARY KEY, employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    started_at TEXT NOT NULL, batch_id TEXT UNIQUE REFERENCES startup_batches(batch_id)
);
CREATE TABLE startup_contents (
    content_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES startup_batches(batch_id),
    video_index INTEGER NOT NULL, composition_signature TEXT NOT NULL,
    video_path TEXT UNIQUE COLLATE NOCASE, created_at TEXT NOT NULL, business_type TEXT NOT NULL CHECK(business_type='STARTUP'),
    production_status TEXT NOT NULL CHECK(production_status IN ('GENERATING','READY','FAILED')),
    publish_status TEXT NOT NULL CHECK(publish_status IN ('NOT_SCHEDULED','SCHEDULED','SUBMITTED','PUBLISHED','FAILED','NEEDS_MANUAL')),
    duration_seconds REAL, size_bytes INTEGER, mtime_ns INTEGER, media_json TEXT,
    materials_json TEXT NOT NULL, error TEXT,
    UNIQUE(batch_id,video_index)
);
CREATE TABLE startup_publish_profiles (
    profile_id TEXT PRIMARY KEY, profile_name TEXT NOT NULL, title_template TEXT NOT NULL,
    description_template TEXT NOT NULL, topics_json TEXT NOT NULL,
    cover_mode TEXT NOT NULL CHECK(cover_mode='DEFAULT'), created_at TEXT NOT NULL
);
CREATE TABLE startup_account_profiles (
    account_id TEXT PRIMARY KEY REFERENCES xiaovcat_accounts(account_id),
    publish_profile_id TEXT REFERENCES startup_publish_profiles(profile_id)
);
CREATE TABLE startup_plan_items (
    item_id TEXT PRIMARY KEY REFERENCES publish_plan_items(item_id),
    content_id TEXT NOT NULL REFERENCES startup_contents(content_id), batch_id TEXT NOT NULL,
    composition_signature TEXT NOT NULL, business_type TEXT NOT NULL CHECK(business_type='STARTUP')
);
CREATE TABLE startup_job_metadata (
    job_id TEXT PRIMARY KEY REFERENCES publish_jobs(job_id), content_id TEXT NOT NULL REFERENCES startup_contents(content_id),
    employee_id TEXT NOT NULL REFERENCES employees(employee_id), account_id TEXT NOT NULL REFERENCES xiaovcat_accounts(account_id),
    business_type TEXT NOT NULL CHECK(business_type='STARTUP'), source_plan_id TEXT NOT NULL REFERENCES publish_plans(plan_id),
    source_plan_item_id TEXT NOT NULL REFERENCES publish_plan_items(item_id), batch_id TEXT NOT NULL,
    composition_signature TEXT NOT NULL, publish_profile_id TEXT NOT NULL REFERENCES startup_publish_profiles(profile_id),
    topics_json TEXT NOT NULL, cover_mode TEXT NOT NULL, schedule_signature TEXT NOT NULL UNIQUE,
    dispatch_mode TEXT NOT NULL CHECK(dispatch_mode='SIMULATION_ONLY')
);
CREATE TABLE startup_pipeline_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
