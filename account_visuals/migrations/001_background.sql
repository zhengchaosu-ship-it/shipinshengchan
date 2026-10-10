CREATE TABLE IF NOT EXISTS background_material_catalog (
    background_asset_id TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    filename TEXT NOT NULL,
    hash TEXT NOT NULL UNIQUE,
    width INTEGER NOT NULL CHECK(width > 0),
    height INTEGER NOT NULL CHECK(height > 0),
    duration REAL NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('IMAGE','VIDEO')),
    thumbnail_path TEXT,
    available INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS background_material_aliases (
    path TEXT PRIMARY KEY,
    background_asset_id TEXT NOT NULL REFERENCES background_material_catalog(background_asset_id)
);
CREATE TABLE IF NOT EXISTS account_background_bindings (
    business_account_id TEXT PRIMARY KEY REFERENCES xiaovcat_accounts(account_id),
    background_asset_id TEXT NOT NULL REFERENCES background_material_catalog(background_asset_id),
    background_path TEXT NOT NULL,
    background_type TEXT NOT NULL CHECK(background_type IN ('IMAGE','VIDEO')),
    fit_mode TEXT NOT NULL DEFAULT 'COVER' CHECK(fit_mode IN ('COVER','CONTAIN','STRETCH')),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS account_background_settings (
    business_account_id TEXT PRIMARY KEY REFERENCES xiaovcat_accounts(account_id),
    required INTEGER NOT NULL DEFAULT 0 CHECK(required IN (0,1)),
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS account_background_audit (
    change_id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_account_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS background_catalog_state (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    root TEXT NOT NULL,
    scanned_at TEXT NOT NULL,
    result_json TEXT NOT NULL
);
