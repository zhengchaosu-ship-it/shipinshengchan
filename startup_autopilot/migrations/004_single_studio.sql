-- 兼容原employees外键的不可登录审计锚点；不修改任何历史员工/绑定/Session/业务记录。
CREATE TABLE IF NOT EXISTS studio_operator_identity(
 actor_id TEXT PRIMARY KEY, actor_type TEXT NOT NULL CHECK(actor_type='LOCAL_OPERATOR'), created_at TEXT NOT NULL);
INSERT OR IGNORE INTO employees(employee_id,employee_name,login_name,role,xiaovcat_group_id,enabled,created_at,updated_at,password_hash)
 VALUES('STUDIO_CONSOLE','工作室操作台','__studio_console_not_loginable__','ADMIN',NULL,0,
 strftime('%Y-%m-%dT%H:%M:%S+00:00','now'),strftime('%Y-%m-%dT%H:%M:%S+00:00','now'),'LOCAL_OPERATOR_NOT_LOGINABLE');
INSERT OR IGNORE INTO studio_operator_identity VALUES('STUDIO_CONSOLE','LOCAL_OPERATOR',strftime('%Y-%m-%dT%H:%M:%S+00:00','now'));
