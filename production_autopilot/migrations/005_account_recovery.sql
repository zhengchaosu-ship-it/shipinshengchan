-- 独立恢复证据，不使用历史PublishJob或普通账号同步作为验证恢复证明。
CREATE TABLE IF NOT EXISTS account_recovery_checks(
 check_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, provider_account_id TEXT NOT NULL,
 requested_by TEXT NOT NULL, requested_at REAL NOT NULL, checked_at REAL,
 state TEXT NOT NULL, reason_code TEXT, human_message TEXT,
 provider_raw_status TEXT, probe_evidence TEXT, resume_requested INTEGER NOT NULL,
 resumed INTEGER NOT NULL DEFAULT 0);
CREATE UNIQUE INDEX IF NOT EXISTS account_recovery_one_check
 ON account_recovery_checks(account_id) WHERE state='CHECKING';
