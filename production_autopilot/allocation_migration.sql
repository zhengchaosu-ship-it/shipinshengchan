-- 仅去掉永久组合唯一约束。30天组合去重继续由已验证Planner控制。
-- 保留全部字段、原ID、账号/发布时间唯一约束、Content/Plan/Job唯一身份。
PRAGMA foreign_keys=OFF;
BEGIN IMMEDIATE;
CREATE TABLE autopilot_allocations_v2(
 allocation_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, local_day TEXT NOT NULL,
 scheduled_at TEXT NOT NULL, composition_signature TEXT NOT NULL, template_version INTEGER NOT NULL,
 proposal_json TEXT NOT NULL, authorization_hash TEXT NOT NULL, state TEXT NOT NULL,
 generation_context_json TEXT, content_id TEXT UNIQUE, render_job_id TEXT,
 plan_id TEXT UNIQUE, job_id TEXT UNIQUE, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(account_id,scheduled_at));
INSERT INTO autopilot_allocations_v2 SELECT * FROM autopilot_allocations;
DROP TABLE autopilot_allocations;
ALTER TABLE autopilot_allocations_v2 RENAME TO autopilot_allocations;
CREATE INDEX IF NOT EXISTS allocation_account_state ON autopilot_allocations(account_id,state,scheduled_at);
COMMIT;
PRAGMA foreign_keys=ON;
