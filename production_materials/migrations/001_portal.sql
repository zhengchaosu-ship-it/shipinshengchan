CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pools(
    pool_id TEXT PRIMARY KEY, business_type TEXT NOT NULL CHECK(business_type IN ('STARTUP','COMMERCE','VISUAL')),
    module_type TEXT NOT NULL UNIQUE, label TEXT NOT NULL, root TEXT, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS products(product_id TEXT PRIMARY KEY, display_name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS batches(ingest_batch_id TEXT PRIMARY KEY, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS uploads(
    upload_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, ingest_batch_id TEXT NOT NULL REFERENCES batches,
    pool_id TEXT NOT NULL REFERENCES pools, product_scope TEXT NOT NULL, product_id TEXT REFERENCES products,
    original_filename TEXT NOT NULL, expected_size INTEGER NOT NULL CHECK(expected_size>0), received INTEGER NOT NULL DEFAULT 0,
    fingerprint TEXT NOT NULL, state TEXT NOT NULL, staged_path TEXT NOT NULL, target_root TEXT NOT NULL,
    destination TEXT, content_hash TEXT, metadata_json TEXT, material_id TEXT, duplicate_of TEXT,
    long_confirmed INTEGER NOT NULL DEFAULT 0, error_code TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS uploads_state ON uploads(state,updated_at);
CREATE TABLE IF NOT EXISTS materials(
    material_id TEXT PRIMARY KEY, business_type TEXT NOT NULL, module_type TEXT NOT NULL, pool_id TEXT NOT NULL REFERENCES pools,
    product_scope TEXT NOT NULL CHECK(product_scope IN ('GLOBAL','PRODUCT_SPECIFIC')), product_id TEXT REFERENCES products,
    original_filename TEXT NOT NULL, stored_filename TEXT NOT NULL, path TEXT NOT NULL UNIQUE,
    content_hash TEXT NOT NULL UNIQUE, size_bytes INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
    duration REAL NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL, fps REAL,
    codec TEXT, audio_codec TEXT, media_type TEXT NOT NULL, thumbnail_path TEXT,
    status TEXT NOT NULL, ingest_batch_id TEXT REFERENCES batches, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS materials_scope ON materials(business_type,module_type,product_scope,product_id,status);
CREATE TABLE IF NOT EXISTS legacy_inventory(
    path TEXT PRIMARY KEY, pool_id TEXT NOT NULL REFERENCES pools, size_bytes INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
    content_hash TEXT, available INTEGER NOT NULL DEFAULT 1);
CREATE INDEX IF NOT EXISTS legacy_size ON legacy_inventory(size_bytes,available);
CREATE TABLE IF NOT EXISTS events(event_id INTEGER PRIMARY KEY, upload_id TEXT, event TEXT NOT NULL, detail_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS catalog_state(singleton INTEGER PRIMARY KEY CHECK(singleton=1),revision INTEGER NOT NULL,updated_at TEXT NOT NULL);
INSERT OR IGNORE INTO catalog_state VALUES(1,0,'');
