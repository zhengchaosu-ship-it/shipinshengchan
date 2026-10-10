-- 与server hardening v1旁表兼容；不改任何历史任务。
CREATE TABLE IF NOT EXISTS server_record_quarantine(
 source_table TEXT NOT NULL,entity_id TEXT NOT NULL,reason_code TEXT NOT NULL,
 payload_sha256 TEXT NOT NULL,first_seen_at REAL NOT NULL,last_seen_at REAL NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('QUARANTINED','RESOLVED')),
 PRIMARY KEY(source_table,entity_id,payload_sha256));
