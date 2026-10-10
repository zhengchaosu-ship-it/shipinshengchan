CREATE TABLE xiaovcat_groups (
    group_id TEXT PRIMARY KEY, group_name TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1, last_synced_at TEXT NOT NULL,
    identity_status TEXT NOT NULL DEFAULT 'SOURCE_ID',
    source_group_id TEXT UNIQUE, source_mapping_key TEXT UNIQUE
);
CREATE TABLE xiaovcat_accounts (
    account_id TEXT PRIMARY KEY, group_id TEXT REFERENCES xiaovcat_groups(group_id),
    display_name TEXT NOT NULL, platform TEXT NOT NULL, avatar TEXT, bio TEXT,
    online_status TEXT NOT NULL, is_available INTEGER NOT NULL,
    is_active INTEGER NOT NULL, last_synced_at TEXT NOT NULL,
    observed_group_name TEXT, identity_evidence TEXT NOT NULL
);
CREATE INDEX idx_xiaovcat_account_group ON xiaovcat_accounts(group_id);
CREATE TABLE employees (
    employee_id TEXT PRIMARY KEY, employee_name TEXT NOT NULL,
    login_name TEXT NOT NULL UNIQUE, role TEXT NOT NULL CHECK(role IN ('ADMIN','EMPLOYEE')),
    xiaovcat_group_id TEXT REFERENCES xiaovcat_groups(group_id),
    enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    password_hash TEXT NOT NULL
);
CREATE TABLE planner_sessions (
    session_hash TEXT PRIMARY KEY, employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    expires_at TEXT NOT NULL
);
CREATE TABLE planner_login_attempts (
    login_name TEXT PRIMARY KEY, failures INTEGER NOT NULL, retry_after TEXT NOT NULL
);
CREATE TABLE publish_plans (
    plan_id TEXT PRIMARY KEY, employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    payload_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'TEST_ONLY', created_at TEXT NOT NULL
);
CREATE TABLE publish_plan_items (
    item_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES publish_plans(plan_id),
    content_id TEXT NOT NULL, account_id TEXT NOT NULL REFERENCES xiaovcat_accounts(account_id),
    group_id TEXT REFERENCES xiaovcat_groups(group_id), video_path TEXT NOT NULL,
    scheduled_at TEXT NOT NULL, schedule_signature TEXT NOT NULL UNIQUE,
    job_id TEXT NOT NULL UNIQUE REFERENCES publish_jobs(job_id),
    test_only INTEGER NOT NULL DEFAULT 1 CHECK(test_only=1)
);
CREATE TABLE group_sync_runs (
    run_id TEXT PRIMARY KEY, captured_at TEXT NOT NULL, result_json TEXT NOT NULL
);
