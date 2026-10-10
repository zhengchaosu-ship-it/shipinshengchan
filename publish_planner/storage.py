"""增量数据库迁移、登录鉴权、组权限与幂等测试任务。"""
from contextlib import contextmanager, closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import hmac
import json
import secrets
import sqlite3
import uuid

from xiaovcat_adapter.models import PublishJob, PublishStatus, utc_now_iso
from xiaovcat_adapter.storage import JOB_COLUMNS, SCHEMA_SQL
from .models import digest
from .planner import preview
from .validator import validate

ROOT = Path(__file__).resolve().parents[1]
MIN_PASSWORD_LENGTH = 6  # 用户明确批准的本地密码策略；哈希强度和登录限速不变。


def publish_account_status(account, *, now=None):
    """仅描述发布快照；不影响生产资格，也不将历史在线状态当作当前在线。"""
    try:
        synced = datetime.fromisoformat(account['last_synced_at'])
        if synced.tzinfo is None:
            raise ValueError('MISSING_TIMEZONE')
        if synced < (now or datetime.now(timezone.utc)) - timedelta(minutes=30):
            return 'PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED'
    except (KeyError, TypeError, ValueError):
        return 'PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED'
    if account.get('online_status') != 'ONLINE' or not account.get('is_available'):
        return 'PUBLISH_ACCOUNT_OFFLINE'
    return 'PUBLISH_ACCOUNT_AVAILABLE'


def default_db():
    config = json.loads((ROOT / "xiaovcat_adapter/config.json").read_text(encoding="utf-8"))
    return ROOT / config["operations_db"]


def password_hash(password, salt=None):
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"本地密码至少{MIN_PASSWORD_LENGTH}个字符")
    salt = salt or secrets.token_hex(16)
    value = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 310000).hex()
    return salt + ":" + value


class PlannerStore:
    def __init__(self, path=None):
        self.path = Path(path or default_db()).resolve()

    @contextmanager
    def connect(self, *, write=False):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def migrate(self):
        first = self._migrate_v1()
        with self.connect() as db:
            if db.execute("SELECT 1 FROM planner_migrations WHERE version=2").fetchone():
                return {"version": 2, "already_applied": True, "initial": first}
            backup = self.path.with_name(self.path.name + ".multi-group-" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".bak")
            with closing(sqlite3.connect(backup)) as saved:
                db.backup(saved)
            protected = {name: [tuple(r) for r in db.execute(f'SELECT * FROM "{name}"')]
                         for name in ["publish_jobs", "published_content", "performance_snapshots", "state_events", "employees", "publish_plan_items"]}
            sql = (Path(__file__).parent / "migrations/002_employee_multi_groups.sql").read_text(encoding="utf-8")
            try:
                db.executescript("BEGIN IMMEDIATE;" + sql)
                # 旧单组字段保留兼容，但业务类型未知，不自动推断或授予绑定。
                for row in db.execute("SELECT plan_id,payload_json FROM publish_plans").fetchall():
                    payload = json.loads(row["payload_json"])
                    payload.setdefault("business_type", "STARTUP")
                    db.execute("UPDATE publish_plans SET payload_json=? WHERE plan_id=?",
                               (json.dumps(payload, default=str, ensure_ascii=False, sort_keys=True), row["plan_id"]))
                db.execute("INSERT INTO planner_migrations VALUES(2,?)", (utc_now_iso(),))
                for name, rows in protected.items():
                    if rows != [tuple(r) for r in db.execute(f'SELECT * FROM "{name}"')]:
                        raise RuntimeError("MULTI_GROUP_MIGRATION_CHANGED_PROTECTED_ROWS:" + name)
                db.commit()
            except Exception:
                db.rollback()
                raise
            return {"version": 2, "backup": str(backup), "initial": first,
                    "protected_rows_unchanged": True, "bindings_auto_assigned": 0,
                    "legacy_single_group_not_used_for_permissions": True}

    def _migrate_v1(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='planner_migrations'").fetchone()
            if exists and db.execute("SELECT 1 FROM planner_migrations WHERE version=1").fetchone():
                return {"version": 1, "already_applied": True}
            legacy = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            # SQLite backup API：一致性快照，不直接复制正在使用的DB。
            backup = self.path.with_name(self.path.name + ".group-planner-" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".bak")
            with closing(sqlite3.connect(backup)) as saved:
                db.backup(saved)
            before = {name: [tuple(r) for r in db.execute(f'SELECT * FROM "{name}" ORDER BY rowid')]
                      for name in legacy}
            sql = (Path(__file__).parent / "migrations/001_group_planner.sql").read_text(encoding="utf-8")
            try:
                db.executescript("BEGIN IMMEDIATE;" + SCHEMA_SQL + sql +
                                 "CREATE TABLE planner_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);")
                db.execute("INSERT INTO planner_migrations VALUES(1,?)", (utc_now_iso(),))
                for name, rows in before.items():
                    if rows != [tuple(r) for r in db.execute(f'SELECT * FROM "{name}" ORDER BY rowid')]:
                        raise RuntimeError("LEGACY_ROWS_CHANGED: " + name)
                if db.execute("PRAGMA foreign_key_check").fetchall():
                    raise RuntimeError("MIGRATION_FOREIGN_KEY_ERROR")
                db.commit()
            except Exception:
                db.rollback()
                raise
            return {"version": 1, "backup": str(backup), "legacy_counts": {n: len(r) for n, r in before.items()},
                    "legacy_rows_unchanged": True, "integrity": db.execute("PRAGMA integrity_check").fetchone()[0]}

    def bootstrap_admin(self, login_name, password):
        encoded = password_hash(password)
        with self.connect(write=True) as db:
            if db.execute("SELECT 1 FROM employees").fetchone():
                raise PermissionError("INITIAL_ADMIN_ALREADY_EXISTS")
            employee_id = str(uuid.uuid4())
            now = utc_now_iso()
            db.execute("INSERT INTO employees VALUES(?,?,?,?,?,?,?,?,?)",
                       (employee_id, "本地管理员", login_name.strip(), "ADMIN", None, 1, now, now, encoded))
        return employee_id

    def login(self, login_name, password):
        now = datetime.now(timezone.utc)
        with self.connect(write=True) as db:
            limit = db.execute("SELECT * FROM planner_login_attempts WHERE login_name=?", (login_name,)).fetchone()
            if limit and limit["failures"] >= 5 and limit["retry_after"] > now.isoformat():
                raise PermissionError("LOGIN_THROTTLED")
            employee = db.execute("SELECT * FROM employees WHERE login_name=? AND enabled=1", (login_name,)).fetchone()
            good = False
            if employee:
                salt, expected = employee["password_hash"].split(":")
                good = len(password) >= MIN_PASSWORD_LENGTH and hmac.compare_digest(password_hash(password, salt).split(":")[1], expected)
            if not good:
                failures = (limit["failures"] if limit and limit["retry_after"] > now.isoformat() else 0) + 1
                db.execute("INSERT OR REPLACE INTO planner_login_attempts VALUES(?,?,?)",
                           (login_name, failures, (now + timedelta(minutes=15)).isoformat()))
            else:
                db.execute("DELETE FROM planner_login_attempts WHERE login_name=?", (login_name,))
                token = secrets.token_urlsafe(32)
                db.execute("INSERT INTO planner_sessions VALUES(?,?,?)",
                           (digest(token), employee["employee_id"], (now + timedelta(hours=8)).isoformat()))
        if not good:
            raise PermissionError("INVALID_LOGIN")
        return token

    def _principal(self, db, token, *, admin=False):
        row = db.execute("SELECT e.* FROM employees e JOIN planner_sessions s USING(employee_id) "
                         "WHERE s.session_hash=? AND s.expires_at>? AND e.enabled=1",
                         (digest(token), utc_now_iso())).fetchone()
        if not row or admin and row["role"] != "ADMIN":
            raise PermissionError("AUTHORIZATION_REQUIRED")
        return row

    def principal(self, token):
        with self.connect() as db:
            row = dict(self._principal(db, token))
            row.pop("password_hash")
            return row

    def generation_owner_available(self, db, owner):
        return bool(db.execute('SELECT 1 FROM employees WHERE employee_id=? AND enabled=1', (owner,)).fetchone())

    def logout(self, token):
        with self.connect(write=True) as db:
            db.execute("DELETE FROM planner_sessions WHERE session_hash=?", (digest(token),))

    def admin_rows(self, token, table):
        if table not in {"employees", "xiaovcat_groups", "group_sync_runs", "employee_group_bindings"}:
            raise ValueError("INVALID_TABLE")
        with self.connect() as db:
            self._principal(db, token, admin=True)
            return [{k: v for k, v in dict(r).items() if k != "password_hash"}
                    for r in db.execute(f"SELECT * FROM {table}")]

    def save_employee(self, token, *, employee_name, login_name, group_id=None,
                      enabled=True, role="EMPLOYEE", password=None, employee_id=None, group_bindings=None):
        if role not in {"ADMIN", "EMPLOYEE"} or not employee_name.strip() or not login_name.strip():
            raise ValueError("INVALID_EMPLOYEE")
        with self.connect(write=True) as db:
            actor = self._principal(db, token, admin=True)
            # 旧API显式group_id输入仅作STARTUP兼容；权限从不查询employees单组列。
            bindings = group_bindings if group_bindings is not None else ([{"group_id": group_id, "group_role": "STARTUP"}] if group_id else None)
            if bindings is not None:
                seen = set()
                for binding in bindings:
                    key = (binding["group_id"], binding["group_role"])
                    if key in seen or binding["group_role"] not in {"STARTUP", "COMMERCE"}:
                        raise ValueError("INVALID_GROUP_BINDINGS")
                    seen.add(key)
                    if not db.execute("SELECT 1 FROM xiaovcat_groups WHERE group_id=? AND is_active=1 AND identity_status IN ('SOURCE_ID','LOCAL_CONFIRMED')", (binding["group_id"],)).fetchone():
                        raise PermissionError("GROUP_IDENTITY_UNVERIFIED")
            old = db.execute("SELECT * FROM employees WHERE employee_id=?", (employee_id,)).fetchone()
            if old and old["role"] == "ADMIN" and (not enabled or role != "ADMIN"):
                if db.execute("SELECT count(*) FROM employees WHERE role='ADMIN' AND enabled=1").fetchone()[0] <= 1:
                    raise PermissionError("LAST_ADMIN_REQUIRED")
            if old:
                encoded = password_hash(password) if password else old["password_hash"]
                db.execute("UPDATE employees SET employee_name=?,login_name=?,role=?,xiaovcat_group_id=?,enabled=?,updated_at=?,password_hash=? WHERE employee_id=?",
                           (employee_name.strip(), login_name.strip(), role, group_id, int(enabled), utc_now_iso(), encoded, employee_id))
                # 修改权限/密码后旧登录凭据作废。
                db.execute("DELETE FROM planner_sessions WHERE employee_id=?", (employee_id,))
            else:
                if employee_id:
                    raise ValueError("EMPLOYEE_NOT_FOUND")
                employee_id = str(uuid.uuid4())
                now = utc_now_iso()
                db.execute("INSERT INTO employees VALUES(?,?,?,?,?,?,?,?,?)",
                           (employee_id, employee_name.strip(), login_name.strip(), role, group_id, int(enabled), now, now, password_hash(password or "")))
            if bindings is not None:
                db.execute("UPDATE employee_group_bindings SET enabled=0 WHERE employee_id=?", (employee_id,))
                for binding in bindings:
                    db.execute("INSERT INTO employee_group_bindings VALUES(?,?,?,?,?) "
                               "ON CONFLICT(employee_id,group_id,group_role) DO UPDATE SET enabled=excluded.enabled",
                               (employee_id, binding["group_id"], binding["group_role"], int(binding.get("enabled", True)), utc_now_iso()))
            return employee_id

    def _accounts(self, db, employee, *, available=True, business_type=None, strict_business=False):
        from yixiaoer_adapter.storage import enabled, enrich_accounts
        provider_enabled = enabled(db)
        if business_type is not None and business_type not in {"STARTUP", "COMMERCE"}:
            raise ValueError("INVALID_BUSINESS_TYPE")
        where = "a.is_active=1"
        args = []
        if available and not provider_enabled:
            where += " AND a.is_available=1 AND a.online_status='ONLINE'"
            where += " AND a.last_synced_at>=?"
            args.append((datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat(timespec="seconds"))
        if employee["role"] != "ADMIN" or strict_business:
            where += " AND g.is_active=1 AND g.identity_status IN ('SOURCE_ID','LOCAL_CONFIRMED') AND EXISTS (SELECT 1 FROM employee_group_bindings b JOIN employees owner ON owner.employee_id=b.employee_id WHERE b.group_id=a.group_id AND b.enabled=1 AND owner.enabled=1"
            if employee["role"] != "ADMIN":
                where += " AND b.employee_id=?"
                args.append(employee["employee_id"])
            if business_type:
                where += " AND b.group_role=?"
                args.append(business_type)
            where += ")"
        rows = enrich_accounts(db, [dict(r) for r in db.execute("SELECT a.*,g.group_name FROM xiaovcat_accounts a LEFT JOIN xiaovcat_groups g ON g.group_id=a.group_id WHERE " + where + " ORDER BY a.platform,a.account_id", args)])
        return [r for r in rows if not available or not provider_enabled or publish_account_status(r)=='PUBLISH_ACCOUNT_AVAILABLE']

    def get_publishable_accounts(self, employee_id, *, session_token, business_type=None):
        with self.connect() as db:
            actor = self._principal(db, session_token)
            if actor["employee_id"] != employee_id:
                raise PermissionError("EMPLOYEE_ID_SPOOFING")
            return self._accounts(db, actor, business_type=business_type, strict_business=business_type is not None)

    def _generation_accounts(self, db, actor, business_type):
        if business_type not in {'STARTUP', 'COMMERCE'}:
            raise ValueError('INVALID_BUSINESS_TYPE')
        # is_active是账号禁用/移除标志；is_available是发布状态，不能混用。
        candidates = self._accounts(db, actor, available=False, business_type=business_type, strict_business=True)
        verified = []
        for account in candidates:
            if not account.get('identity_evidence') or not account.get('account_id'):
                continue
            try:
                if datetime.fromisoformat(account['last_synced_at']).tzinfo is None:
                    continue
            except (TypeError, ValueError):
                continue
            verified.append(dict(account, generation_eligible=True,
                                 publish_availability=publish_account_status(account)))
        return verified

    def get_generation_accounts(self, employee_id, *, session_token, business_type):
        with self.connect() as db:
            actor = self._principal(db, session_token)
            if actor['employee_id'] != employee_id:
                raise PermissionError('EMPLOYEE_ID_SPOOFING')
            return self._generation_accounts(db, actor, business_type)

    def _require_publish_accounts(self, db, actor, account_ids, business_type):
        visible = {a['account_id']: a for a in self._accounts(db, actor, available=False,
            business_type=business_type, strict_business=True)}
        if not set(account_ids).issubset(visible):
            raise PermissionError('ACCOUNT_PERMISSION_DENIED')
        if any(publish_account_status(visible[k]) == 'PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED' for k in account_ids):
            raise PermissionError('PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED')
        available = {a['account_id']: a for a in self._accounts(db, actor,
            business_type=business_type, strict_business=True)}
        if not set(account_ids).issubset(available):
            raise PermissionError('ACCOUNT_PERMISSION_DENIED')
        return available

    def visible_accounts(self, token, business_type=None):
        with self.connect() as db:
            return self._accounts(db, self._principal(db, token), available=False, business_type=business_type,
                                  strict_business=business_type is not None)

    def plan_accounts(self, token, business_type):
        with self.connect() as db:
            return self._accounts(db, self._principal(db, token), business_type=business_type, strict_business=True)

    def sync_snapshot(self, snapshot, *, session_token):
        if not snapshot.get("complete") or not snapshot.get("accounts"):
            raise ValueError("INCOMPLETE_SYNC_NO_MUTATION")
        ids = [a["account_id"] for a in snapshot["accounts"]]
        if any(not i for i in ids) or len(ids) != len(set(ids)):
            raise ValueError("AMBIGUOUS_ACCOUNT_IDS")
        now = utc_now_iso()
        with self.connect(write=True) as db:
            self._principal(db, session_token, admin=True)
            # 不自动停用缺失记录：可见UI可能是过滤/分页的子集。
            group_ids = set()
            for group in snapshot.get("groups", []):
                if not group.get("group_id") or group.get("identity_status") != "SOURCE_ID":
                    continue  # 未拿到源ID的观察不伪造稳定分组，不授予权限。
                group_ids.add(group["group_id"])
                db.execute("INSERT INTO xiaovcat_groups VALUES(?,?,1,?,'SOURCE_ID',?,NULL) "
                           "ON CONFLICT(group_id) DO UPDATE SET group_name=excluded.group_name,is_active=1,last_synced_at=excluded.last_synced_at",
                           (group["group_id"], group["group_name"], now, group["group_id"]))
            for account in snapshot["accounts"]:
                group_id = account.get("group_id")
                if group_id and group_id not in group_ids:
                    raise ValueError("UNKNOWN_GROUP_ID")
                values = (account["account_id"], group_id, account["display_name"], account["platform"],
                          account.get("avatar"), account.get("bio"), account["online_status"],
                          int(account["is_available"]), 1, now, account.get("observed_group_name"), account["identity_evidence"])
                db.execute("INSERT INTO xiaovcat_accounts VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET "
                           "group_id=excluded.group_id,display_name=excluded.display_name,platform=excluded.platform,avatar=excluded.avatar,bio=excluded.bio,online_status=excluded.online_status,is_available=excluded.is_available,is_active=1,last_synced_at=excluded.last_synced_at,observed_group_name=excluded.observed_group_name,identity_evidence=excluded.identity_evidence", values)
            if snapshot.get("snapshot_scope") == "UNFILTERED_NO_PAGINATION_VISIBLE_UI":
                # 完整当前清单明确核验后，缺失账号只停用，保留历史任务/稳定ID，不删除。
                db.execute("UPDATE xiaovcat_accounts SET is_active=0,is_available=0 WHERE account_id NOT IN (" +
                           ",".join("?" for _ in ids) + ")", ids)
            run_id = snapshot["run_id"]
            db.execute("INSERT INTO group_sync_runs VALUES(?,?,?)", (run_id, now, json.dumps(snapshot, ensure_ascii=False)))
        return {"run_id": run_id, "saved_accounts": len(ids), "saved_stable_groups": len(group_ids),
                "observed_groups": snapshot.get("groups", [])}

    def authorized_preview(self, token, plan):
        with self.connect() as db:
            employee = self._principal(db, token)
            self._require_publish_accounts(db, employee, plan.account_ids, plan.business_type)
            return self._schedule_preview(db, plan)

    def _schedule_preview(self, db, plan):
        occupied = []
        if plan.business_type == 'STARTUP':
            occupied = [(r[0], r[1]) for r in db.execute(
                "SELECT i.account_id,i.scheduled_at FROM publish_plan_items i JOIN publish_jobs j USING(job_id) "
                "JOIN publish_plans p USING(plan_id) WHERE i.plan_id<>? AND p.status!='CANCELLED' "
                "AND j.status NOT IN ('CANCELLED','FAILED')", (plan.plan_id,))]
        return preview(plan, occupied_slots=occupied)

    def create_plan(self, token, plan):
        validate(plan, check_files=True)
        slots = preview(plan)
        with self.connect(write=True) as db:
            employee = self._principal(db, token)
            from startup_pipeline.account_binding import guard_manual_paths
            guard_manual_paths(db, plan.video_paths)
            existing = db.execute("SELECT * FROM publish_plans WHERE plan_id=?", (plan.plan_id,)).fetchone()
            if existing:
                if existing["employee_id"] != employee["employee_id"] or existing["payload_json"] != plan.payload():
                    raise ValueError("PLAN_ID_CONFLICT_CREATE_NEW_PLAN")
                return {"plan_id": plan.plan_id, "created": 0, "existing": len(slots), "test_only": True}
            accounts = self._require_publish_accounts(db, employee, plan.account_ids, plan.business_type)
            slots = self._schedule_preview(db, plan)
            # 不调用 Queue / Worker。状态NEEDS_MANUAL不属于可消费队列。
            db.execute("INSERT INTO publish_plans(plan_id,employee_id,payload_json,status,created_at,business_type) VALUES(?,?,?,'TEST_ONLY',?,?)",
                       (plan.plan_id, employee["employee_id"], plan.payload(), utc_now_iso(), plan.business_type))
            for slot in slots:
                account = accounts[slot.account_id]
                job = PublishJob.create(content_id=slot.content_id, video_path=slot.video_path,
                                        title=plan.title, description=plan.description, platform=account["platform"],
                                        account_name=account["display_name"], publish_mode="SCHEDULED",
                                        scheduled_at=slot.scheduled_at, allow_empty_title=True)
                job.status = PublishStatus.NEEDS_MANUAL
                job.current_step = "PLANNER_TEST_ONLY_NOT_DISPATCHED"
                job.error_code = "PLANNER_TEST_ONLY"
                job.error_message = "仅本地计划预览记录；禁止派发至真实Worker"
                data = job.to_dict()
                db.execute(f"INSERT INTO publish_jobs ({','.join(JOB_COLUMNS)}) VALUES ({','.join('?' for _ in JOB_COLUMNS)})",
                           [json.dumps(data["segment_material_ids"]) if c == "segment_material_ids_json" else data.get(c) for c in JOB_COLUMNS])
                db.execute("INSERT INTO publish_plan_items VALUES(?,?,?,?,?,?,?,?,?,1)",
                           (slot.item_id, plan.plan_id, slot.content_id, slot.account_id, account["group_id"], slot.video_path,
                            slot.scheduled_at, slot.schedule_signature, job.job_id))
        return {"plan_id": plan.plan_id, "created": len(slots), "existing": 0, "test_only": True}

    def jobs(self, token):
        with self.connect() as db:
            actor = self._principal(db, token)
            query = "SELECT e.employee_name,p.business_type,COALESCE(g.group_name,a.observed_group_name || '（身份未确认）') AS group_name,a.account_id,a.display_name AS account_name,a.platform,i.video_path,i.scheduled_at,j.status,j.current_step,i.plan_id,i.job_id,i.test_only FROM publish_plan_items i JOIN publish_plans p USING(plan_id) JOIN employees e USING(employee_id) JOIN xiaovcat_accounts a USING(account_id) LEFT JOIN xiaovcat_groups g ON g.group_id=i.group_id JOIN publish_jobs j USING(job_id)"
            rows = [dict(r) for r in db.execute(query + ("" if actor["role"] == "ADMIN" else " WHERE p.employee_id=?") + " ORDER BY i.scheduled_at", () if actor["role"] == "ADMIN" else (actor["employee_id"],))]
            from yixiaoer_adapter.storage import enabled
            if enabled(db):
                providers={r['job_id']:dict(r) for r in db.execute('SELECT job_id,provider,provider_account_id,provider_task_set_id,provider_task_id,provider_video_id,provider_video_url,provider_status,provider_stage_status,submit_attempt_count FROM provider_publish_jobs')}
                rows=[dict(r,**{k:v for k,v in providers.get(r['job_id'],{}).items() if k!='job_id'}) for r in rows]
            return rows
