CREATE TABLE startup_exports (
    content_id TEXT PRIMARY KEY REFERENCES startup_contents(content_id),
    batch_id TEXT NOT NULL REFERENCES startup_batches(batch_id),
    video_index INTEGER NOT NULL,
    composition_signature TEXT NOT NULL,
    draft_name TEXT NOT NULL, draft_path TEXT NOT NULL,
    expected_mp4_path TEXT NOT NULL UNIQUE COLLATE NOCASE,
    actual_mp4_path TEXT UNIQUE COLLATE NOCASE,
    export_status TEXT NOT NULL CHECK(export_status IN ('DRAFT_READY','WAITING_EXPORT','EXPORTING','EXPORTED','VALIDATED','EXPORT_FAILED')),
    export_source TEXT NOT NULL CHECK(export_source IN ('MANUAL_JIANYING','AUTOMATED_JIANYING')),
    created_at TEXT NOT NULL, export_started_at TEXT, export_completed_at TEXT,
    file_size INTEGER, mtime_ns INTEGER,
    video_codec TEXT, audio_codec TEXT, width INTEGER, height INTEGER, fps REAL, duration REAL,
    error TEXT, UNIQUE(batch_id,video_index)
);
CREATE TABLE startup_export_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id TEXT NOT NULL REFERENCES startup_exports(content_id),
    status TEXT NOT NULL, event_at TEXT NOT NULL, detail TEXT
);
CREATE TABLE startup_export_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
