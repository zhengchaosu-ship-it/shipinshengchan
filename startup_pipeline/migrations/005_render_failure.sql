-- SQLite不能ALTER CHECK；按官方重建流程保留全部旧字段、唯一约束和外键。
CREATE TABLE startup_contents_render_migration (
    content_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES startup_batches(batch_id),
    video_index INTEGER NOT NULL, composition_signature TEXT NOT NULL,
    video_path TEXT UNIQUE COLLATE NOCASE, created_at TEXT NOT NULL, business_type TEXT NOT NULL CHECK(business_type='STARTUP'),
    production_status TEXT NOT NULL CHECK(production_status IN ('GENERATING','READY','FAILED','RENDER_FAILED')),
    publish_status TEXT NOT NULL CHECK(publish_status IN ('NOT_SCHEDULED','SCHEDULED','SUBMITTED','PUBLISHED','FAILED','NEEDS_MANUAL')),
    duration_seconds REAL, size_bytes INTEGER, mtime_ns INTEGER, media_json TEXT,
    materials_json TEXT NOT NULL, error TEXT,
    failure_code TEXT, failure_message TEXT, failed_at TEXT, render_job_id TEXT,
    UNIQUE(batch_id,video_index)
);
INSERT INTO startup_contents_render_migration(content_id,batch_id,video_index,composition_signature,video_path,created_at,business_type,production_status,publish_status,duration_seconds,size_bytes,mtime_ns,media_json,materials_json,error)
 SELECT content_id,batch_id,video_index,composition_signature,video_path,created_at,business_type,production_status,publish_status,duration_seconds,size_bytes,mtime_ns,media_json,materials_json,error FROM startup_contents;
DROP TABLE startup_contents;
ALTER TABLE startup_contents_render_migration RENAME TO startup_contents;
CREATE TABLE startup_render_failures (
 render_job_id TEXT PRIMARY KEY, content_id TEXT NOT NULL UNIQUE REFERENCES startup_contents(content_id),
 receipt_sha256 TEXT NOT NULL, failure_code TEXT NOT NULL, failure_message TEXT NOT NULL, failed_at TEXT NOT NULL
);
