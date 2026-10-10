-- 仅新增表。当前FoundationStore只允许隔离fixture库；禁止应用到operations.db。
CREATE TABLE sap_migrations(version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL);
CREATE TABLE sap_template_versions(
    account_id TEXT NOT NULL REFERENCES xiaovcat_accounts(account_id), template_version TEXT NOT NULL,
    ordered_slots_json TEXT NOT NULL, config_hash TEXT NOT NULL, created_by TEXT NOT NULL REFERENCES employees(employee_id),
    created_at TEXT NOT NULL, PRIMARY KEY(account_id,template_version)
);
CREATE TABLE sap_profiles(
    account_id TEXT PRIMARY KEY REFERENCES xiaovcat_accounts(account_id), owner_employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN(0,1)),
    status TEXT NOT NULL DEFAULT 'SETUP' CHECK(status IN('SETUP','COLD_START','LEARNING','AUTOPILOT','PAUSED','FINISHED','ATTENTION_REQUIRED')),
    execution_mode TEXT NOT NULL DEFAULT 'SHADOW_MODE' CHECK(execution_mode='SHADOW_MODE'),
    daily_publish_limit INTEGER NOT NULL DEFAULT 5 CHECK(daily_publish_limit BETWEEN 1 AND 5), publish_times_json TEXT NOT NULL,
    target_follower_count INTEGER NOT NULL CHECK(target_follower_count>0), learning_threshold INTEGER NOT NULL DEFAULT 20 CHECK(learning_threshold>=20),
    exploit_ratio REAL NOT NULL DEFAULT .7 CHECK(exploit_ratio BETWEEN 0 AND 1), explore_ratio REAL NOT NULL DEFAULT .1 CHECK(explore_ratio BETWEEN 0 AND 1 AND exploit_ratio+explore_ratio<=1),
    template_version TEXT NOT NULL, policy_version TEXT NOT NULL,
    autopilot_confirmed_by TEXT REFERENCES employees(employee_id), autopilot_confirmed_at TEXT, confirmed_config_hash TEXT,
    profile_json TEXT NOT NULL, updated_at TEXT NOT NULL,
    CHECK(enabled=0 OR (status IN('COLD_START','LEARNING','AUTOPILOT') AND autopilot_confirmed_by IS NOT NULL AND confirmed_config_hash IS NOT NULL AND autopilot_confirmed_at IS NOT NULL)),
    FOREIGN KEY(account_id,template_version) REFERENCES sap_template_versions(account_id,template_version)
);
CREATE TABLE sap_profile_events(
    event_id INTEGER PRIMARY KEY, account_id TEXT NOT NULL REFERENCES sap_profiles(account_id), actor_id TEXT NOT NULL REFERENCES employees(employee_id),
    action TEXT NOT NULL, from_status TEXT, to_status TEXT NOT NULL, config_hash TEXT NOT NULL,
    scheduled_work_choice TEXT, evidence_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE sap_material_registry(
    material_id TEXT PRIMARY KEY, media_sha256 TEXT NOT NULL UNIQUE, module_type TEXT NOT NULL,
    duration_seconds REAL NOT NULL CHECK(duration_seconds>0), aliases_json TEXT NOT NULL, registered_at TEXT NOT NULL
);
CREATE TABLE sap_material_overrides(
    override_id INTEGER PRIMARY KEY, account_id TEXT NOT NULL REFERENCES sap_profiles(account_id), material_id TEXT NOT NULL REFERENCES sap_material_registry(material_id),
    mode TEXT NOT NULL CHECK(mode IN('LOCK','PREFERRED','BLOCK','CLEAR')), actor_id TEXT NOT NULL REFERENCES employees(employee_id), created_at TEXT NOT NULL
);
CREATE TABLE sap_shadow_runs(
    decision_key TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES sap_profiles(account_id), target_day TEXT NOT NULL,
    profile_hash TEXT NOT NULL, input_snapshot_hash TEXT NOT NULL, policy_version TEXT NOT NULL, scoring_version TEXT NOT NULL,
    decision_json TEXT NOT NULL, created_at TEXT NOT NULL,
    UNIQUE(account_id,target_day,profile_hash,input_snapshot_hash)
);
CREATE TABLE sap_publication_reservations(
    reservation_id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES sap_profiles(account_id), local_day TEXT NOT NULL,
    scheduled_at TEXT NOT NULL, content_id TEXT NOT NULL UNIQUE, composition_signature TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN('RESERVED','RENDERING','READY','SUBMITTED','SCHEDULED_QUEUED','PUBLISHED','FAILED_HOLD','RELEASED_NO_PLATFORM_WORK')),
    evidence_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX sap_active_account_slot ON sap_publication_reservations(account_id,scheduled_at) WHERE state!='RELEASED_NO_PLATFORM_WORK';
CREATE TABLE sap_public_works(
    account_id TEXT NOT NULL REFERENCES sap_profiles(account_id), work_id TEXT NOT NULL, content_id TEXT NOT NULL,
    public_at TEXT NOT NULL, time_precision TEXT NOT NULL, public_evidence_ref TEXT NOT NULL, PRIMARY KEY(account_id,work_id)
);
CREATE TABLE sap_metric_requests(
    account_id TEXT NOT NULL, work_id TEXT NOT NULL, window_hours INTEGER NOT NULL CHECK(window_hours IN(2,24,72)),
    due_at TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN('WAITING','COLLECTED','NOT_SUPPORTED','ATTENTION_REQUIRED')),
    PRIMARY KEY(account_id,work_id,window_hours), FOREIGN KEY(account_id,work_id) REFERENCES sap_public_works(account_id,work_id)
);
CREATE TABLE sap_work_materials(
    account_id TEXT NOT NULL, work_id TEXT NOT NULL, slot_index INTEGER NOT NULL CHECK(slot_index>0),
    material_id TEXT NOT NULL REFERENCES sap_material_registry(material_id), module_type TEXT NOT NULL,
    attribution_evidence_ref TEXT NOT NULL, PRIMARY KEY(account_id,work_id,slot_index),
    FOREIGN KEY(account_id,work_id) REFERENCES sap_public_works(account_id,work_id)
);
CREATE TABLE sap_metric_snapshots(
    snapshot_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL, work_id TEXT NOT NULL,
    window_hours INTEGER NOT NULL CHECK(window_hours IN(2,24,72)), observed_at TEXT NOT NULL,
    views INTEGER, likes INTEGER, comments INTEGER, shares INTEGER, favorites INTEGER, followers_delta INTEGER,
    completion_rate REAL, watch_seconds REAL, capabilities_json TEXT NOT NULL,
    source TEXT NOT NULL, evidence_ref TEXT NOT NULL, evidence_hash TEXT NOT NULL, time_precision TEXT NOT NULL,
    snapshot_json TEXT NOT NULL, FOREIGN KEY(account_id,work_id) REFERENCES sap_public_works(account_id,work_id)
);
CREATE TABLE sap_affinity_versions(
    version_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES sap_profiles(account_id), material_id TEXT NOT NULL,
    module_type TEXT NOT NULL, sample_count INTEGER NOT NULL, score_2h REAL, score_24h REAL, score_72h REAL,
    view_score REAL, completion_score REAL, like_score REAL, comment_score REAL, share_score REAL, favorite_score REAL, follow_score REAL,
    affinity_score REAL NOT NULL, last_used_at TEXT, usage_7d INTEGER NOT NULL, usage_30d INTEGER NOT NULL,
    updated_at TEXT NOT NULL, scoring_version TEXT NOT NULL, policy_version TEXT NOT NULL, evidence_json TEXT NOT NULL
);
CREATE TABLE sap_submission_budget_events(
    attempt_key TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES sap_profiles(account_id), attempted_at TEXT NOT NULL,
    beijing_day TEXT NOT NULL, source TEXT NOT NULL CHECK(source IN('PRODUCTION','POC','MANUAL')),
    quota_rejected INTEGER NOT NULL CHECK(quota_rejected IN(0,1)), evidence_ref TEXT NOT NULL
);
CREATE TABLE sap_account_metric_snapshots(
    snapshot_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES sap_profiles(account_id), observed_at TEXT NOT NULL,
    followers_total INTEGER, capability TEXT NOT NULL CHECK(capability IN('AVAILABLE','NOT_SUPPORTED','NOT_RETURNED','INVALID')),
    source TEXT NOT NULL, evidence_ref TEXT NOT NULL, evidence_hash TEXT NOT NULL, freshness TEXT NOT NULL
);
CREATE INDEX sap_reservations_account_day ON sap_publication_reservations(account_id,local_day,state);
CREATE INDEX sap_metrics_work_window ON sap_metric_snapshots(account_id,work_id,window_hours,observed_at);
-- 版本证据只能追加，升级算法不能改写历史分数或原始指标。
CREATE TRIGGER sap_shadow_no_update BEFORE UPDATE ON sap_shadow_runs BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
CREATE TRIGGER sap_shadow_no_delete BEFORE DELETE ON sap_shadow_runs BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
CREATE TRIGGER sap_metrics_no_update BEFORE UPDATE ON sap_metric_snapshots BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
CREATE TRIGGER sap_metrics_no_delete BEFORE DELETE ON sap_metric_snapshots BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
CREATE TRIGGER sap_affinity_no_update BEFORE UPDATE ON sap_affinity_versions BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
CREATE TRIGGER sap_affinity_no_delete BEFORE DELETE ON sap_affinity_versions BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
CREATE TRIGGER sap_template_no_update BEFORE UPDATE ON sap_template_versions BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
CREATE TRIGGER sap_template_no_delete BEFORE DELETE ON sap_template_versions BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
CREATE TRIGGER sap_events_no_update BEFORE UPDATE ON sap_profile_events BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
CREATE TRIGGER sap_events_no_delete BEFORE DELETE ON sap_profile_events BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
CREATE TRIGGER sap_budget_no_update BEFORE UPDATE ON sap_submission_budget_events BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
CREATE TRIGGER sap_budget_no_delete BEFORE DELETE ON sap_submission_budget_events BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
CREATE TRIGGER sap_account_metrics_no_update BEFORE UPDATE ON sap_account_metric_snapshots BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
CREATE TRIGGER sap_account_metrics_no_delete BEFORE DELETE ON sap_account_metric_snapshots BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
