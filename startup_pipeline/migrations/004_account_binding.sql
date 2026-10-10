CREATE TABLE startup_generation_bindings (
 generation_id TEXT PRIMARY KEY REFERENCES startup_generation_runs(generation_id),
 employee_id TEXT NOT NULL REFERENCES employees(employee_id),
 business_type TEXT NOT NULL CHECK(business_type IN ('STARTUP','COMMERCE')),
 target_account_id TEXT NOT NULL REFERENCES xiaovcat_accounts(account_id),
 target_account_name_snapshot TEXT NOT NULL,
 batch_id TEXT NOT NULL UNIQUE, local_date TEXT NOT NULL
);
CREATE TABLE startup_name_reservations (
 generation_id TEXT NOT NULL REFERENCES startup_generation_bindings(generation_id),
 video_index INTEGER NOT NULL, target_account_id TEXT NOT NULL,
 business_type TEXT NOT NULL, local_date TEXT NOT NULL, daily_sequence INTEGER NOT NULL,
 draft_name TEXT NOT NULL,
 PRIMARY KEY(generation_id,video_index),
 UNIQUE(target_account_id,business_type,local_date,daily_sequence),
 UNIQUE(draft_name COLLATE NOCASE)
);
CREATE TABLE startup_content_bindings (
 content_id TEXT PRIMARY KEY REFERENCES startup_contents(content_id),
 generation_id TEXT NOT NULL REFERENCES startup_generation_bindings(generation_id),
 target_account_id TEXT NOT NULL REFERENCES xiaovcat_accounts(account_id),
 target_account_name_snapshot TEXT NOT NULL, draft_name TEXT NOT NULL,
 source_content_id TEXT REFERENCES startup_contents(content_id)
);
CREATE TRIGGER startup_binding_no_update BEFORE UPDATE ON startup_content_bindings
 BEGIN SELECT RAISE(ABORT,'ACCOUNT_BINDING_IMMUTABLE'); END;
CREATE TRIGGER startup_binding_no_delete BEFORE DELETE ON startup_content_bindings
 BEGIN SELECT RAISE(ABORT,'ACCOUNT_BINDING_IMMUTABLE'); END;
CREATE TRIGGER startup_context_no_update BEFORE UPDATE ON startup_generation_bindings
 BEGIN SELECT RAISE(ABORT,'ACCOUNT_BINDING_IMMUTABLE'); END;
CREATE TRIGGER startup_context_no_delete BEFORE DELETE ON startup_generation_bindings
 BEGIN SELECT RAISE(ABORT,'ACCOUNT_BINDING_IMMUTABLE'); END;
CREATE TRIGGER startup_binding_validate BEFORE INSERT ON startup_content_bindings
 WHEN NOT EXISTS(SELECT 1 FROM startup_generation_bindings g WHERE g.generation_id=NEW.generation_id
 AND g.target_account_id=NEW.target_account_id AND g.target_account_name_snapshot=NEW.target_account_name_snapshot)
 BEGIN SELECT RAISE(ABORT,'ACCOUNT_BINDING_MISMATCH'); END;
CREATE TRIGGER startup_job_account_guard BEFORE INSERT ON startup_job_metadata
 WHEN NOT EXISTS(SELECT 1 FROM startup_content_bindings b WHERE b.content_id=NEW.content_id AND b.target_account_id=NEW.account_id)
 BEGIN SELECT RAISE(ABORT,'ACCOUNT_BINDING_MISMATCH'); END;
CREATE TRIGGER startup_job_account_update_guard BEFORE UPDATE ON startup_job_metadata
 WHEN NOT EXISTS(SELECT 1 FROM startup_content_bindings b WHERE b.content_id=NEW.content_id AND b.target_account_id=NEW.account_id)
 BEGIN SELECT RAISE(ABORT,'ACCOUNT_BINDING_MISMATCH'); END;
