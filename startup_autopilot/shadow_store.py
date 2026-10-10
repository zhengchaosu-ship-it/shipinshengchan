"""8502独立观察数据；不迁移operations.db，不提供正式生产派发。"""
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from .models import Actor, Profile, Slot, Template, digest, policy

DEFAULT_PATH=Path(__file__).parent/'runtime'/'shadow_8502.db'
EXCLUDED_BUSINESS='1621131832863931'
EXCLUDED_PROVIDER='6ac389eb46f95bf847d47da1'


class ShadowStore:
    def __init__(self,path=None):
        self.path=Path(path or DEFAULT_PATH).resolve()
        if self.path.name=='operations.db':
            raise PermissionError('SEPARATE_SHADOW_DATABASE_REQUIRED')

    @contextmanager
    def connect(self, *, readonly=False):
        if readonly:
            db=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True)
            db.execute('PRAGMA query_only=ON')
        else:
            db=sqlite3.connect(self.path)
        db.row_factory=sqlite3.Row
        try:
            with db: yield db
        finally: db.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS shadow_profiles(
                    business_account_id TEXT PRIMARY KEY, provider_account_id TEXT NOT NULL UNIQUE,
                    owner_employee_id TEXT NOT NULL, nickname TEXT NOT NULL, bound_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL, template_json TEXT NOT NULL, catalog_json TEXT NOT NULL,
                    source_evidence_json TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS shadow_decisions(
                    decision_hash TEXT PRIMARY KEY, business_account_id TEXT NOT NULL,
                    profile_hash TEXT NOT NULL, observed_at TEXT NOT NULL, payload_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS shadow_audit(
                    id INTEGER PRIMARY KEY, business_account_id TEXT NOT NULL, actor_id TEXT NOT NULL,
                    action TEXT NOT NULL, recorded_at TEXT NOT NULL, evidence_json TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS shadow_decisions_no_update BEFORE UPDATE ON shadow_decisions BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
                CREATE TRIGGER IF NOT EXISTS shadow_decisions_no_delete BEFORE DELETE ON shadow_decisions BEGIN SELECT RAISE(ABORT,'APPEND_ONLY'); END;
            ''')

    def create(self, actor, profile, template, catalog, identity):
        actor.require(profile.account_id)
        profile.validate(); template.validate()
        if profile.enabled or profile.status!='COLD_START' or profile.execution_mode!='SHADOW':
            raise PermissionError('OBSERVATION_PROFILE_ONLY')
        if profile.account_id==EXCLUDED_BUSINESS or identity['provider_account_id']==EXCLUDED_PROVIDER:
            raise PermissionError('BINGYAO_EXCLUDED_FROM_AUTOPILOT')
        if identity['business_account_id']!=profile.account_id or template.account_id!=profile.account_id:
            raise PermissionError('ACCOUNT_IDENTITY_MISMATCH')
        if profile.template_hash!=digest(asdict(template)):
            raise PermissionError('TEMPLATE_HASH_MISMATCH')
        if profile.policy_hash!=digest(policy()):
            raise PermissionError('POLICY_HASH_MISMATCH')
        at=datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT * FROM shadow_profiles WHERE business_account_id=?',(profile.account_id,)).fetchone()
            if old:
                if old['provider_account_id']!=identity['provider_account_id'] or old['owner_employee_id']!=actor.employee_id:
                    raise PermissionError('SHADOW_ACCOUNT_REBIND_FORBIDDEN')
                return False
            db.execute('INSERT INTO shadow_profiles VALUES(?,?,?,?,?,?,?,?,?,?)',(
                profile.account_id,identity['provider_account_id'],actor.employee_id,identity['nickname'],identity['bound_at'],
                json.dumps(asdict(profile),ensure_ascii=False),json.dumps(asdict(template),ensure_ascii=False),
                json.dumps(catalog,ensure_ascii=False),json.dumps(identity,ensure_ascii=False),at))
            db.execute('INSERT INTO shadow_audit(business_account_id,actor_id,action,recorded_at,evidence_json) VALUES(?,?,?,?,?)',
                       (profile.account_id,actor.employee_id,'CREATE_DISABLED_NEW_ACCOUNT_SHADOW',at,json.dumps(identity,ensure_ascii=False)))
        return True

    def load(self, actor, account_id):
        actor.require(account_id)
        if account_id==EXCLUDED_BUSINESS:
            raise PermissionError('BINGYAO_EXCLUDED_FROM_AUTOPILOT')
        with self.connect(readonly=True) as db:
            row=db.execute('SELECT * FROM shadow_profiles WHERE business_account_id=?',(account_id,)).fetchone()
            if not row or (row['owner_employee_id']!=actor.employee_id and actor.role!='ADMIN'):
                raise PermissionError('SHADOW_PROFILE_PERMISSION_REQUIRED')
        raw=json.loads(row['payload_json']);raw['publish_times']=tuple(raw['publish_times'])
        profile=Profile(**raw);profile.validate()
        if profile.execution_mode not in {'SHADOW','PRODUCTION'}:
            raise PermissionError('LIVE_MODE_UNAVAILABLE')
        template_raw=json.loads(row['template_json'])
        template=Template(template_raw['account_id'],template_raw['version'],tuple(
            Slot(**{**slot,'material_ids':tuple(slot['material_ids'])}) for slot in template_raw['slots']))
        return dict(row),profile,template,json.loads(row['catalog_json'])

    def visible(self, actor):
        if not self.path.exists(): return []
        with self.connect(readonly=True) as db:
            return [dict(r) for r in db.execute('SELECT business_account_id,nickname,owner_employee_id FROM shadow_profiles ORDER BY bound_at DESC')
                    if r['business_account_id'] in actor.permitted_accounts and (r['owner_employee_id']==actor.employee_id or actor.role=='ADMIN')
                    and r['business_account_id']!=EXCLUDED_BUSINESS]

    def save_decision(self,actor,account_id,decision):
        _,profile,_,_=self.load(actor,account_id)
        with self.connect(readonly=True) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='composition_template_states'").fetchone():
                raise PermissionError('USE_USER_CONFIRMED_COMPOSITION_PLANNER')
        if decision['business_account_id']!=account_id or decision['profile_enabled'] or any(decision[k] for k in ('render_jobs_created','publish_jobs_created','provider_tasks_created','publish_count')):
            raise PermissionError('SHADOW_SIDE_EFFECT_DETECTED')
        key=digest(decision)
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO shadow_decisions VALUES(?,?,?,?,?)',(key,account_id,profile.config_hash(),datetime.now(timezone.utc).isoformat(),json.dumps(decision,ensure_ascii=False)))
        return key

    def latest(self,actor,account_id):
        _,profile,_,_=self.load(actor,account_id)
        with self.connect(readonly=True) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='composition_template_states'").fetchone():
                return None  # 原默认模板的历史建议保留，但不再作为正式计划展示。
            row=db.execute('SELECT payload_json FROM shadow_decisions WHERE business_account_id=? AND profile_hash=? ORDER BY observed_at DESC LIMIT 1',(account_id,profile.config_hash())).fetchone()
        return json.loads(row[0]) if row else None

    def update_target(self,actor,account_id,target):
        row,profile,_,_=self.load(actor,account_id)
        raw=asdict(profile);raw['target_follower_count']=target
        updated=Profile(**raw);updated.validate()
        at=datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute('UPDATE shadow_profiles SET payload_json=?,updated_at=? WHERE business_account_id=? AND provider_account_id=?',
                       (json.dumps(raw,ensure_ascii=False),at,account_id,row['provider_account_id']))
            db.execute('INSERT INTO shadow_audit(business_account_id,actor_id,action,recorded_at,evidence_json) VALUES(?,?,?,?,?)',
                       (account_id,actor.employee_id,'SAVE_SHADOW_TARGET_NO_ENABLE',at,json.dumps({'target':target})))

    def update_observation_settings(self,actor,account_id,*,note,daily_limit,publish_times,target,learning_threshold):
        """只有用户保存时写独立观察设置，不启用真实托管、不改正式Account映射。"""
        self.load(actor,account_id)
        if not isinstance(note,str) or len(note)>500:raise ValueError('账号备注最多500字')
        at=datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM shadow_profiles WHERE business_account_id=?',(account_id,)).fetchone()
            if not row or (row['owner_employee_id']!=actor.employee_id and actor.role!='ADMIN'):
                raise PermissionError('SHADOW_PROFILE_PERMISSION_REQUIRED')
            raw=json.loads(row['payload_json'])
            raw.update(daily_publish_limit=daily_limit,publish_times=tuple(publish_times),target_follower_count=target,
                       learning_threshold=learning_threshold,enabled=False,execution_mode='SHADOW')
            Profile(**raw).validate()
            evidence=json.loads(row['source_evidence_json']);evidence['startup_account_note']=note.strip()
            db.execute('UPDATE shadow_profiles SET payload_json=?,source_evidence_json=?,updated_at=? WHERE business_account_id=?',
                       (json.dumps(raw,ensure_ascii=False),json.dumps(evidence,ensure_ascii=False),at,account_id))
            db.execute('INSERT INTO shadow_audit(business_account_id,actor_id,action,recorded_at,evidence_json) VALUES(?,?,?,?,?)',
                       (account_id,actor.employee_id,'SAVE_SHADOW_ACCOUNT_SETTINGS_NO_ENABLE',at,
                        json.dumps({'daily_limit':daily_limit,'publish_times':publish_times,'target':target,'learning_threshold':learning_threshold})))
