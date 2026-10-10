CREATE TABLE employee_group_bindings (
    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    group_id TEXT NOT NULL REFERENCES xiaovcat_groups(group_id),
    group_role TEXT NOT NULL CHECK(group_role IN ('STARTUP','COMMERCE')),
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    PRIMARY KEY(employee_id,group_id,group_role)
);
CREATE INDEX idx_employee_bindings_role ON employee_group_bindings(employee_id,group_role,enabled);
ALTER TABLE publish_plans ADD COLUMN business_type TEXT NOT NULL DEFAULT 'STARTUP'
    CHECK(business_type IN ('STARTUP','COMMERCE'));
