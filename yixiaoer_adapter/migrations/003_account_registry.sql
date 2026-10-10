CREATE TABLE IF NOT EXISTS business_account_registry (
 business_account_id TEXT PRIMARY KEY REFERENCES xiaovcat_accounts(account_id),
 provider TEXT NOT NULL CHECK(provider='yixiaoer'), platform TEXT NOT NULL CHECK(platform='douyin'),
 provider_account_id TEXT NOT NULL UNIQUE,
 business_display_name TEXT NOT NULL, provider_display_name TEXT NOT NULL, provider_remark TEXT NOT NULL,
 provider_status TEXT NOT NULL, provider_binding_status TEXT NOT NULL,
 provider_first_seen_at TEXT NOT NULL, provider_last_seen_at TEXT NOT NULL,
 mapping_source TEXT NOT NULL, missing_count INTEGER NOT NULL DEFAULT 0,
 missing_since TEXT, raw_account_json TEXT NOT NULL,
 initial_startup_profile_status TEXT NOT NULL DEFAULT 'NOT_CONFIGURED'
);
CREATE TABLE IF NOT EXISTS account_sync_runs (
 sync_run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, state TEXT NOT NULL,
 provider_accounts_seen INTEGER NOT NULL DEFAULT 0, created INTEGER NOT NULL DEFAULT 0,
 updated INTEGER NOT NULL DEFAULT 0, unchanged INTEGER NOT NULL DEFAULT 0,
 offline INTEGER NOT NULL DEFAULT 0, missing INTEGER NOT NULL DEFAULT 0, errors INTEGER NOT NULL DEFAULT 0,
 error_code TEXT
);
CREATE TABLE IF NOT EXISTS account_sync_changes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, sync_run_id TEXT NOT NULL REFERENCES account_sync_runs(sync_run_id),
 business_account_id TEXT NOT NULL, provider_account_id TEXT NOT NULL, event TEXT NOT NULL,
 previous_json TEXT, current_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS account_sync_state (
 id INTEGER PRIMARY KEY CHECK(id=1), last_success_at TEXT, revision INTEGER NOT NULL DEFAULT 0,
 request_generation INTEGER NOT NULL DEFAULT 0, completed_generation INTEGER NOT NULL DEFAULT 0,
 last_error TEXT, last_attempt_at TEXT
);
INSERT OR IGNORE INTO account_sync_state(id) VALUES(1);
