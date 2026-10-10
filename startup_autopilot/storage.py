"""只允许隔离fixture的迁移与Shadow存储；没有默认生产路径。"""
from dataclasses import asdict
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile

from .models import aware, digest, policy


class FoundationStore:
    def __init__(self, path):
        self.path=Path(path).resolve()
        permitted=[Path(tempfile.gettempdir()).resolve(),Path(__file__).parent.joinpath('runtime','isolated').resolve()]
        if not self.path.name.endswith('.fixture.db') or not any(self.path.is_relative_to(root) for root in permitted):
            raise PermissionError('FOUNDATION_DATABASE_MUST_BE_ISOLATED_FIXTURE')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10)
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def migrate(self, *, isolated=False):
        if not isolated:
            raise PermissionError('EXPLICIT_ISOLATED_MIGRATION_REQUIRED')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        sql=Path(__file__).with_name('migrations').joinpath('001_foundation.sql').read_text('utf-8')
        checksum=hashlib.sha256(sql.encode()).hexdigest()
        with self.connect() as db:
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'sap_migrations' in tables:
                previous=db.execute("SELECT checksum FROM sap_migrations WHERE version='001'").fetchone()
                if previous:
                    if previous[0]!=checksum:
                        raise ValueError('MIGRATION_CHECKSUM_CHANGED')
                    return False
            # 与实际旧表一样使用业务账号和员工PK。fixture须显式准备旧基础表，不自动造账号。
            if not {'employees','xiaovcat_accounts'}<=tables:
                raise ValueError('EXISTING_ACCOUNT_AND_EMPLOYEE_SCHEMA_REQUIRED')
            backup=sqlite3.connect(str(self.path)+'.bak')
            try:
                db.backup(backup)
            finally:
                backup.close()
            try:
                db.executescript('BEGIN IMMEDIATE;\n'+sql)
                db.execute('INSERT INTO sap_migrations VALUES(?,?,?)',('001',checksum,datetime.now(timezone.utc).isoformat()))
                db.commit()
            except Exception:
                db.rollback(); raise
        return True

    def save_profile(self, actor, profile, template, now):
        actor.require(profile.account_id)
        profile.validate(); template.validate()
        if template.account_id!=profile.account_id or template.version!=profile.template_version:
            raise PermissionError('ACCOUNT_TEMPLATE_MISMATCH')
        if profile.template_hash!=digest(asdict(template)) or profile.policy_hash!=digest(policy()):
            raise PermissionError('RECONFIRM_CHANGED_TEMPLATE_OR_POLICY')
        at=aware(now).isoformat()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior=db.execute('SELECT config_hash FROM sap_template_versions WHERE account_id=? AND template_version=?',(profile.account_id,template.version)).fetchone()
            template_hash=digest(asdict(template))
            if prior and prior[0]!=template_hash:
                raise ValueError('IMMUTABLE_TEMPLATE_VERSION_CHANGED')
            db.execute('INSERT OR IGNORE INTO sap_template_versions VALUES(?,?,?,?,?,?)',(profile.account_id,template.version,json.dumps(asdict(template),ensure_ascii=False),template_hash,actor.employee_id,at))
            old=db.execute('SELECT status,owner_employee_id FROM sap_profiles WHERE account_id=?',(profile.account_id,)).fetchone()
            # fixture保存也执行最小权限；多人业务账号授权应由未来8502适配器构建Actor。
            if old and old[1]!=actor.employee_id and actor.role!='ADMIN':
                raise PermissionError('PROFILE_OWNER_OR_ADMIN_REQUIRED')
            values=(profile.account_id,old[1] if old else actor.employee_id,int(profile.enabled),profile.status,profile.execution_mode,
                    profile.daily_publish_limit,json.dumps(profile.publish_times),profile.target_follower_count,profile.learning_threshold,
                    profile.exploit_ratio,profile.explore_ratio,profile.template_version,profile.policy_version,profile.confirmed_by,
                    profile.confirmed_at,profile.confirmed_config_hash,json.dumps(asdict(profile),ensure_ascii=False),at)
            db.execute('''INSERT INTO sap_profiles VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                          ON CONFLICT(account_id) DO UPDATE SET enabled=excluded.enabled,status=excluded.status,
                          daily_publish_limit=excluded.daily_publish_limit,publish_times_json=excluded.publish_times_json,
                          target_follower_count=excluded.target_follower_count,learning_threshold=excluded.learning_threshold,
                          exploit_ratio=excluded.exploit_ratio,explore_ratio=excluded.explore_ratio,
                          template_version=excluded.template_version,policy_version=excluded.policy_version,
                          autopilot_confirmed_by=excluded.autopilot_confirmed_by,autopilot_confirmed_at=excluded.autopilot_confirmed_at,
                          confirmed_config_hash=excluded.confirmed_config_hash,profile_json=excluded.profile_json,updated_at=excluded.updated_at''',values)
            db.execute('''INSERT INTO sap_profile_events(account_id,actor_id,action,from_status,to_status,config_hash,evidence_json,created_at)
                          VALUES(?,?,?,?,?,?,?,?)''',(profile.account_id,actor.employee_id,'SAVE_SHADOW_PROFILE',old[0] if old else None,profile.status,profile.config_hash(),json.dumps(asdict(profile),ensure_ascii=False),at))

    def save_shadow(self, actor, profile, decision, now, scoring_version):
        actor.require(profile.account_id)
        profile.validate()
        if decision['execution_mode']!='SHADOW_MODE' or decision['account_id']!=profile.account_id or any(decision[key] for key in ('render_jobs_created','publish_jobs_created','submit_count')):
            raise PermissionError('SHADOW_ONLY_DECISION_REQUIRED')
        raw=json.dumps(decision,ensure_ascii=False,sort_keys=True)
        key=digest([profile.config_hash(),decision])
        snapshot=decision.get('input_snapshot_hash',digest(decision))
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior=db.execute('SELECT decision_key FROM sap_shadow_runs WHERE account_id=? AND target_day=? AND profile_hash=? AND input_snapshot_hash=?',
                             (profile.account_id,decision['target_day'],profile.config_hash(),snapshot)).fetchone()
            if prior:
                return prior[0],False
            db.execute('INSERT INTO sap_shadow_runs VALUES(?,?,?,?,?,?,?,?,?)',(key,profile.account_id,decision['target_day'],profile.config_hash(),snapshot,
                       decision['policy_version'],scoring_version,raw,aware(now).isoformat()))
        return key,True
