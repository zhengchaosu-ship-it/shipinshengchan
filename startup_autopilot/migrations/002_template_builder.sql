-- 只用于独立shadow_8502.db，不迁移operations.db。
CREATE TABLE IF NOT EXISTS composition_template_states(
    account_id TEXT PRIMARY KEY, status TEXT NOT NULL, active_version INTEGER,
    legacy_template_hash TEXT, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS composition_template_versions(
    account_id TEXT NOT NULL, version INTEGER NOT NULL, config_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL, created_at TEXT NOT NULL, confirmed_by TEXT NOT NULL,
    preview_token TEXT NOT NULL UNIQUE, PRIMARY KEY(account_id,version));
CREATE TABLE IF NOT EXISTS composition_preview_receipts(
    token TEXT PRIMARY KEY, account_id TEXT NOT NULL, actor_id TEXT NOT NULL,
    base_version INTEGER NOT NULL, config_hash TEXT NOT NULL, catalog_hash TEXT NOT NULL,
    draft_json TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS composition_material_pools(
    account_id TEXT NOT NULL, pool_id TEXT NOT NULL, label TEXT NOT NULL, root TEXT NOT NULL,
    PRIMARY KEY(account_id,pool_id));
CREATE TABLE IF NOT EXISTS composition_catalog_cache(
    account_id TEXT NOT NULL,pool_id TEXT NOT NULL,file_key TEXT NOT NULL,
    path TEXT NOT NULL,size_bytes INTEGER NOT NULL,mtime_ns INTEGER NOT NULL,
    media_sha256 TEXT NOT NULL, PRIMARY KEY(account_id,pool_id,file_key));
CREATE TABLE IF NOT EXISTS composition_public_samples(
    account_id TEXT NOT NULL,work_id TEXT NOT NULL,actual_published_at TEXT NOT NULL,
    evidence_json TEXT NOT NULL, PRIMARY KEY(account_id,work_id));
CREATE TABLE IF NOT EXISTS composition_slot_affinities(
    account_id TEXT NOT NULL,slot_position TEXT NOT NULL,material_id TEXT NOT NULL,
    normalized_score REAL, sample_count INTEGER NOT NULL DEFAULT 0,
    override TEXT, evidence_json TEXT NOT NULL,
    PRIMARY KEY(account_id,slot_position,material_id));
CREATE TRIGGER IF NOT EXISTS composition_versions_no_update BEFORE UPDATE ON composition_template_versions BEGIN SELECT RAISE(ABORT,'APPEND_ONLY_TEMPLATE_VERSION'); END;
CREATE TRIGGER IF NOT EXISTS composition_versions_no_delete BEFORE DELETE ON composition_template_versions BEGIN SELECT RAISE(ABORT,'APPEND_ONLY_TEMPLATE_VERSION'); END;
CREATE TRIGGER IF NOT EXISTS composition_receipts_no_update BEFORE UPDATE ON composition_preview_receipts BEGIN SELECT RAISE(ABORT,'APPEND_ONLY_PREVIEW'); END;
CREATE TRIGGER IF NOT EXISTS composition_receipts_no_delete BEFORE DELETE ON composition_preview_receipts BEGIN SELECT RAISE(ABORT,'APPEND_ONLY_PREVIEW'); END;
