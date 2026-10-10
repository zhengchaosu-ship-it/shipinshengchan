-- 只新增交接附表；不改变旧production_status约束、权限表或发布表。
CREATE TABLE startup_content_registrations (
    content_id TEXT PRIMARY KEY REFERENCES startup_contents(content_id),
    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    generation_id TEXT NOT NULL REFERENCES startup_generation_runs(generation_id),
    batch_id TEXT NOT NULL,
    video_index INTEGER NOT NULL CHECK(video_index > 0),
    composition_signature TEXT NOT NULL,
    draft_name TEXT NOT NULL,
    draft_path TEXT NOT NULL,
    business_type TEXT NOT NULL CHECK(business_type = 'STARTUP'),
    created_at TEXT NOT NULL,
    production_status TEXT NOT NULL CHECK(production_status IN ('DRAFT_READY','RENDER_PENDING','RENDER_JOB_CREATE_FAILED')),
    render_job_id TEXT UNIQUE,
    error TEXT,
    UNIQUE(batch_id, video_index)
);
CREATE TABLE startup_registration_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    generation_id TEXT NOT NULL,
    batch_id TEXT,
    content_id TEXT,
    status TEXT NOT NULL,
    event_at TEXT NOT NULL,
    detail TEXT
);
