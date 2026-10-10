"""正式Job派发仓库：不创建Plan/Job，不使用历史验收scope，不包含GUI操作。"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import secrets
import sqlite3

from publish_planner.storage import PlannerStore, ROOT
from xiaovcat_adapter.models import utc_now_iso
from .account_binding import guard_publish_job
from .single_acceptance import file_digest

CONFIRMATION = 'CONFIRMED_PRODUCTION_JOB_SINGLE_SUBMIT'
RESERVE_STEP = 'V04_FINAL_SUBMIT_RESERVED'


def migrate(store):
    with store.connect() as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='startup_production_dispatch'").fetchone():
            return {'already_applied': True}
        backup = store.path.with_name(store.path.name+'.production-dispatch-'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.bak')
        with closing(sqlite3.connect(backup)) as saved:
            db.backup(saved)
    with store.connect(write=True) as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='startup_production_dispatch'").fetchone():
            return {'already_applied': True}
        for statement in (Path(__file__).parent/'migrations/008_production_dispatch.sql').read_text('utf-8').split(';'):
            if statement.strip():
                db.execute(statement)
        db.execute('INSERT INTO startup_pipeline_migrations VALUES(8,?)', (utc_now_iso(),))
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('DISPATCH_MIGRATION_INTEGRITY_ERROR')
    return {'version': 8, 'backup': str(backup)}


def enqueue_confirmed(db, plan_id):
    """Confirm事务内调用；只进入独立正式队列，旧通用队列仍不会领取。"""
    plan = db.execute('SELECT * FROM publish_plans WHERE plan_id=?', (plan_id,)).fetchone()
    if not plan or plan['status'] != 'CONFIRMED' or plan['business_type'] != 'STARTUP':
        raise PermissionError('CONFIRMED_STARTUP_PLAN_REQUIRED')
    items = db.execute('SELECT * FROM publish_plan_items WHERE plan_id=? ORDER BY scheduled_at', (plan_id,)).fetchall()
    for item in items:
        guard_publish_job(db, item['job_id'])
        if item['test_only']:
            raise PermissionError('SIMULATION_NOT_DISPATCHABLE')
        queued = db.execute('SELECT plan_id FROM startup_production_dispatch WHERE job_id=?', (item['job_id'],)).fetchone()
        if queued:
            if queued['plan_id'] != plan_id:raise PermissionError('DISPATCH_PLAN_MISMATCH')
            continue
        job = db.execute('SELECT status,current_step FROM publish_jobs WHERE job_id=?', (item['job_id'],)).fetchone()
        if (not job or job['status'] != 'NEEDS_MANUAL' or job['current_step'] != 'STARTUP_CONFIRMED_NOT_DISPATCHED'
            or db.execute('SELECT 1 FROM state_events WHERE job_id=? AND step=?', (item['job_id'], RESERVE_STEP)).fetchone()):
            raise PermissionError('JOB_ALREADY_ACTIVE_NO_REDISPATCH')
        db.execute("INSERT OR IGNORE INTO startup_production_dispatch(job_id,plan_id,state,created_at) VALUES(?,?,'QUEUED',?)",
                   (item['job_id'], plan_id, utc_now_iso()))
    return [r['job_id'] for r in items]


class ProductionDispatcher:
    def __init__(self, store=None, *, probe=None):
        self.store = store or PlannerStore()
        if probe is None:
            from .service import probe_video
            probe = probe_video
        self.probe = probe

    def _plan_actor(self, db, token, plan_id):
        actor = self.store._principal(db, token)
        plan = db.execute('SELECT * FROM publish_plans WHERE plan_id=?', (plan_id,)).fetchone()
        if not plan or plan['employee_id'] != actor['employee_id']:
            raise PermissionError('PLAN_PERMISSION_DENIED')
        if plan['status'] != 'CONFIRMED' or plan['business_type'] != 'STARTUP':
            raise PermissionError('CONFIRMED_STARTUP_PLAN_REQUIRED')
        return actor

    def update_publish_config(self, token, plan_id, job_ids, *, title, description, topics):
        """正式仓库唯一配置写入；同一事务审计old→new，不修改排期或共享模板。"""
        migrate(self.store)
        normalized = ['#'+t.lstrip('#') for t in topics]
        if len(normalized) != len(set(normalized)) or any(t == '#' for t in normalized):
            raise ValueError('INVALID_TOPICS')
        with self.store.connect(write=True) as db:
            actor = self._plan_actor(db, token, plan_id)
            for job_id in job_ids:
                item = db.execute('SELECT * FROM publish_plan_items WHERE job_id=? AND plan_id=?', (job_id, plan_id)).fetchone()
                job = db.execute('SELECT * FROM publish_jobs WHERE job_id=?', (job_id,)).fetchone()
                meta = db.execute('SELECT * FROM startup_job_metadata WHERE job_id=?', (job_id,)).fetchone()
                queued = db.execute('SELECT state FROM startup_production_dispatch WHERE job_id=?', (job_id,)).fetchone()
                if (not item or not job or not meta or item['test_only'] or job['status'] != 'NEEDS_MANUAL'
                    or job['current_step'] != 'STARTUP_CONFIRMED_NOT_DISPATCHED'
                    or queued and queued['state'] != 'QUEUED'
                    or db.execute('SELECT 1 FROM state_events WHERE job_id=? AND step=?', (job_id, RESERVE_STEP)).fetchone()):
                    raise PermissionError('JOB_CONFIG_LOCKED_OR_NOT_IN_PLAN')
                guard_publish_job(db, job_id)
                old = {'title': job['title'], 'description': job['description'], 'topics': json.loads(meta['topics_json'])}
                new = {'title': title, 'description': description, 'topics': normalized}
                if old == new:
                    continue
                db.execute('UPDATE publish_jobs SET title=?,description=?,updated_at=? WHERE job_id=?',
                           (title, description, utc_now_iso(), job_id))
                db.execute('UPDATE startup_job_metadata SET topics_json=? WHERE job_id=?', (json.dumps(normalized, ensure_ascii=False), job_id))
                db.execute('INSERT INTO startup_publish_config_audit(job_id,employee_id,old_json,new_json,changed_at) VALUES(?,?,?,?,?)',
                           (job_id, actor['employee_id'], json.dumps(old, ensure_ascii=False), json.dumps(new, ensure_ascii=False), utc_now_iso()))

    def _context(self, db, job_id, *, claimed=False):
        job = db.execute('SELECT * FROM publish_jobs WHERE job_id=?', (job_id,)).fetchone()
        if job and job['status'] == 'CANCELLED':
            raise PermissionError('JOB_CANCELLED')
        meta = db.execute('SELECT * FROM startup_job_metadata WHERE job_id=?', (job_id,)).fetchone()
        if not job or not meta:
            raise PermissionError('FORMAL_JOB_METADATA_REQUIRED')
        plan = db.execute('SELECT * FROM publish_plans WHERE plan_id=?', (meta['source_plan_id'],)).fetchone()
        item = db.execute('SELECT * FROM publish_plan_items WHERE job_id=?', (job_id,)).fetchone()
        content = db.execute('SELECT * FROM startup_contents WHERE content_id=?', (job['content_id'],)).fetchone()
        actor = db.execute('SELECT * FROM employees WHERE employee_id=? AND enabled=1', (meta['employee_id'],)).fetchone()
        if (not plan or plan['status'] != 'CONFIRMED' or not item or item['test_only'] or not actor
            or meta['business_type'] != 'STARTUP' or plan['employee_id'] != actor['employee_id']
            or item['plan_id'] != plan['plan_id'] or item['item_id'] != meta['source_plan_item_id']
            or item['schedule_signature'] != meta['schedule_signature']
            or not content or content['production_status'] != 'READY' or content['publish_status'] != 'SCHEDULED'
            or job['video_path'] != item['video_path'] or job['video_path'] != content['video_path']
            or job['scheduled_at'] != item['scheduled_at'] or job['publish_mode'] != 'SCHEDULED'
            or meta['account_id'] != item['account_id'] or meta['content_id'] != job['content_id']
            or job['external_work_id'] or job['external_work_url']):
            raise PermissionError('FORMAL_JOB_CONTEXT_MISMATCH')
        expected = ('DRY_RUN_READY', 'NEEDS_MANUAL') if claimed else ('NEEDS_MANUAL',)
        if job['status'] not in expected or (not claimed and job['current_step'] != 'STARTUP_CONFIRMED_NOT_DISPATCHED'):
            raise PermissionError('JOB_ALREADY_ACTIVE_NO_REDISPATCH')
        guard_publish_job(db, job_id)
        if (db.execute('SELECT 1 FROM published_content WHERE content_id=?', (job['content_id'],)).fetchone()
            or db.execute("SELECT 1 FROM state_events WHERE job_id=? AND step IN (?, 'SUBMIT_INTENT')", (job_id, RESERVE_STEP)).fetchone()
            or db.execute("SELECT 1 FROM publish_jobs WHERE content_id=? AND job_id<>? AND status!='CANCELLED'", (job['content_id'], job_id)).fetchone()):
            raise PermissionError('ALREADY_SUBMITTED_OR_RESERVED_NO_RETRY')
        account = self.store._require_publish_accounts(db, actor, [meta['account_id']], 'STARTUP')[meta['account_id']]
        if (account['group_id'] != item['group_id'] or job['account_name'] != account['display_name']
            or job['platform'] != account['platform'] or not account.get('identity_evidence')):
            raise PermissionError('ACCOUNT_BINDING_MISMATCH')
        remaining = datetime.fromisoformat(job['scheduled_at']) - datetime.now(timezone.utc)
        if not timedelta(hours=2) < remaining <= timedelta(days=14):
            raise PermissionError('SCHEDULE_NO_LONGER_SAFE_NO_RECALCULATION')
        media = self.probe(job['video_path'])
        if (media['size_bytes'], media['mtime_ns']) != (content['size_bytes'], content['mtime_ns']):
            raise PermissionError('REGISTERED_VIDEO_CHANGED')
        return dict(job_id=job_id, content_id=job['content_id'], account_id=meta['account_id'],
                    employee_id=meta['employee_id'], plan_id=plan['plan_id'], business_type='STARTUP',
                    video_path=job['video_path'], account_name=account['display_name'], platform=account['platform'],
                    title=job['title'], description=job['description'], topics=json.loads(meta['topics_json']),
                    publish_mode='SCHEDULED', scheduled_at=job['scheduled_at'],
                    execution_mode='PRODUCTION', schedule_delay_minutes=130, schedule_rule='FIXED_CONFIRMED_PLAN_TIME',
                    max_jobs=1, max_final_submit_invocations=1, consume_other_jobs=False,
                    media_policy='VERIFIED_READY_ONLY', profile_mode='STARTUP_READY_BOUND',
                    video_sha256=file_digest(job['video_path']), confirmation=CONFIRMATION)

    def dry_dispatch(self, token, plan_id):
        if json.loads((ROOT/'xiaovcat_adapter/config.json').read_text('utf-8'))['real_publish_enabled'] is not False:
            raise PermissionError('GLOBAL_PUBLISH_SWITCH_MUST_STAY_OFF')
        migrate(self.store)
        with self.store.connect(write=True) as db:
            self._plan_actor(db, token, plan_id)
            ids = enqueue_confirmed(db, plan_id)
            policies = [self._context(db, job_id) for job_id in ids]
        return {'plan_id': plan_id, 'jobs': [dict(policy=p, dispatchable=True) for p in policies],
                'final_submit_invocations': 0, 'real_publish_enabled': False}

    def confirmed_schedule(self, token, plan_id):
        """只读显示已确认原排期，不以当前快照或执行状态重新计算Preview。"""
        from publish_planner.models import Slot
        with self.store.connect() as db:
            self._plan_actor(db, token, plan_id)
            rows = db.execute('SELECT * FROM publish_plan_items WHERE plan_id=? ORDER BY scheduled_at,item_id', (plan_id,)).fetchall()
            for row in rows:guard_publish_job(db,row['job_id'])
            return [Slot(r['item_id'],r['content_id'],r['account_id'],r['video_path'],r['scheduled_at'],r['schedule_signature']) for r in rows]

    def claim(self, token, plan_id, job_id, worker_id):
        with self.store.connect(write=True) as db:
            self._plan_actor(db, token, plan_id)
            return self._claim_in_transaction(db, plan_id, job_id, worker_id)

    def _claim_in_transaction(self, db, plan_id, job_id, worker_id):
        from yixiaoer_adapter.storage import enabled
        if enabled(db):
            raise PermissionError('XIAOVCAT_LEGACY_DISABLED')
        """共用原子领取；调用者必须先完成员工鉴权或限定的本机Worker授权。"""
        job = db.execute('SELECT status FROM publish_jobs WHERE job_id=?', (job_id,)).fetchone()
        if job and job['status'] == 'CANCELLED':
            raise PermissionError('JOB_CANCELLED')
        row = db.execute('SELECT * FROM startup_production_dispatch WHERE job_id=? AND plan_id=?', (job_id, plan_id)).fetchone()
        if not row or row['state'] != 'QUEUED':
            raise PermissionError('ALREADY_CLAIMED_NO_REDISPATCH')
        policy = self._context(db, job_id)
        if policy['plan_id'] != plan_id:
            raise PermissionError('DISPATCH_PLAN_MISMATCH')
        nonce = secrets.token_hex(24)
        changed = db.execute("UPDATE startup_production_dispatch SET state='CLAIMED',worker_id=?,claim_token=?,context_json=?,claimed_at=? WHERE job_id=? AND state='QUEUED'",
                             (worker_id, nonce, json.dumps(policy, ensure_ascii=False, sort_keys=True), utc_now_iso(), job_id))
        if changed.rowcount != 1:
            raise PermissionError('ATOMIC_CLAIM_LOST')
        db.execute("UPDATE publish_jobs SET status='DRY_RUN_READY',current_step='PRODUCTION_CLAIMED',error_code=NULL,error_message=NULL,updated_at=? WHERE job_id=?",
                   (utc_now_iso(), job_id))
        db.execute('INSERT INTO state_events(job_id,step,attempt,outcome,started_at,duration_ms) VALUES(?,?,?,?,?,0)',
                   (job_id, 'PRODUCTION_ATOMIC_CLAIM', 1, worker_id, utc_now_iso()))
        return nonce

    def block(self, job_id, reason):
        with self.store.connect(write=True) as db:
            job = db.execute('SELECT status FROM publish_jobs WHERE job_id=?', (job_id,)).fetchone()
            if job and job['status'] == 'CANCELLED':
                raise PermissionError('JOB_CANCELLED')
            row = db.execute('SELECT state FROM startup_production_dispatch WHERE job_id=?', (job_id,)).fetchone()
            if not row or row['state'] == 'SCHEDULED_QUEUED':
                raise PermissionError('CANNOT_OVERWRITE_SUCCESS')
            attempted = bool(db.execute('SELECT 1 FROM state_events WHERE job_id=? AND step=?', (job_id, RESERVE_STEP)).fetchone())
            state = 'SUBMIT_RESULT_UNCERTAIN' if attempted else 'BLOCKED'
            db.execute('UPDATE startup_production_dispatch SET state=?,error_code=?,completed_at=? WHERE job_id=?', (state, reason, utc_now_iso(), job_id))
            db.execute("UPDATE publish_jobs SET status='NEEDS_MANUAL',current_step=?,error_code=?,error_message=?,updated_at=? WHERE job_id=?",
                       (state, state if attempted else reason, reason, utc_now_iso(), job_id))
        return state

    def cancel_unsubmitted_job(self, plan_id, job_id, content_id, *, task_record_evidence):
        """用户明确撤销后的安全收口；保留历史，缺少任务记录负证据不得取消。

        维护调用须先取得既有GUI执行互斥。数据库BEGIN IMMEDIATE再次校验，
        任何提交意图/成功/活跃领取都拒绝，不能用取消去掩盖未知提交。
        不新增schema，取消元信息存原审计JSON与Job error_message。
        """
        with self.store.connect(write=True) as db:
            job = db.execute('SELECT * FROM publish_jobs WHERE job_id=?', (job_id,)).fetchone()
            row = db.execute('SELECT * FROM startup_production_dispatch WHERE job_id=?', (job_id,)).fetchone()
            meta = db.execute('SELECT * FROM startup_job_metadata WHERE job_id=?', (job_id,)).fetchone()
            if (not job or not row or not meta or row['plan_id'] != plan_id
                or meta['source_plan_id'] != plan_id or job['content_id'] != content_id):
                raise PermissionError('CANCELLATION_SCOPE_MISMATCH')
            if job['status'] == 'CANCELLED':
                return dict(job_id=job_id, status='CANCELLED', idempotent=True)
            attempted = db.execute('SELECT 1 FROM state_events WHERE job_id=? AND '
                "(step IN (?, 'SUBMIT_INTENT', 'LOCAL_SUBMIT_RETURNED') OR outcome='SUBMIT_ATTEMPTED_DURABLE_BEFORE_UI')",
                (job_id, RESERVE_STEP)).fetchone()
            if (attempted or job['status'] in {'SUBMITTING','SCHEDULED_QUEUED','PUBLISHED'}
                or job['external_work_id'] or job['external_work_url']
                or db.execute('SELECT 1 FROM published_content WHERE content_id=?', (content_id,)).fetchone()):
                raise PermissionError('POST_SUBMIT_RECONCILIATION_REQUIRED_NO_CANCEL')
            if row['state'] not in {'QUEUED','BLOCKED'}:
                raise PermissionError('ACTIVE_OR_UNCERTAIN_JOB_NO_CANCEL')
            guard_publish_job(db, job_id)
            evidence = task_record_evidence or {}
            expected = dict(job_id=job_id, content_id=content_id, account_id=meta['account_id'],
                account_name=job['account_name'], platform=job['platform'],
                video_name=Path(job['video_path']).name, scheduled_at=job['scheduled_at'])
            if (evidence.get('verified') is not True or evidence.get('matching_tasks') != 0
                or evidence.get('source') not in {'SUPPORTED_COMPUTER_USE_TASK_RECORDS',
                                                 'USER_MANUAL_XIAOVCAT_CONFIRMATION'}
                or not evidence.get('checked_at') or any(evidence.get(k) != v for k,v in expected.items())):
                raise PermissionError('XIAOVCAT_NO_TASK_EVIDENCE_REQUIRED')
            now = utc_now_iso()
            reason = 'SCHEDULE_WINDOW_EXPIRED_USER_CANCELLED'
            audit = dict(**expected, cancel_reason=reason, cancelled_at=now, cancelled_by='USER',
                old_job_status=job['status'], old_step=job['current_step'],
                old_error_code=job['error_code'], old_error_message=job['error_message'],
                old_dispatch_state=row['state'], task_record_evidence=evidence)
            encoded = json.dumps(audit, ensure_ascii=False, sort_keys=True)
            db.execute("UPDATE publish_jobs SET status='CANCELLED',current_step='USER_CANCELLED',"
                       'error_code=?,error_message=?,updated_at=? WHERE job_id=?', (reason, encoded, now, job_id))
            # 既有dispatch CHECK没有CANCELLED：BLOCKED + JOB_CANCELLED是不可领取等价终态。
            # 不删除claim/context，也不更改历史scheduled_at。
            db.execute("UPDATE startup_production_dispatch SET state='BLOCKED',error_code='JOB_CANCELLED',"
                       'completed_at=? WHERE job_id=?', (now, job_id))
            other = db.execute("SELECT 1 FROM publish_jobs WHERE content_id=? AND job_id<>? "
                               "AND status NOT IN ('CANCELLED','FAILED') LIMIT 1", (content_id, job_id)).fetchone()
            if not other:
                db.execute("UPDATE startup_contents SET publish_status='NOT_SCHEDULED' WHERE content_id=? "
                           "AND production_status='READY' AND publish_status='SCHEDULED'", (content_id,))
            states = [r[0] for r in db.execute('SELECT j.status FROM publish_jobs j JOIN '
                'startup_job_metadata m USING(job_id) WHERE m.source_plan_id=?', (plan_id,))]
            plan_state = ('PARTIALLY_COMPLETED' if any(s in {'SCHEDULED_QUEUED','PUBLISHED'} for s in states)
                          else 'CANCELLED' if all(s=='CANCELLED' for s in states) else 'PARTIALLY_CANCELLED')
            db.execute('UPDATE publish_plans SET status=? WHERE plan_id=?', (plan_state, plan_id))
            db.execute('INSERT INTO state_events(job_id,step,attempt,outcome,started_at,duration_ms) VALUES(?,?,?,?,?,0)',
                       (job_id,'USER_CANCELLED',1,encoded,now))
            if db.execute('PRAGMA foreign_key_check').fetchall():
                raise RuntimeError('CANCELLATION_INTEGRITY_ERROR')
        return dict(job_id=job_id, status='CANCELLED', plan_status=plan_state,
                    submit_attempt_count=0, cancelled_at=now, cancelled_by='USER', cancel_reason=reason)

    def cancel_unsubmitted_plan(self, plan_id, expected_job_ids, *, reason):
        """用户撤销错误队列：全体未claim/未尝试才允许同一事务取消，保留索引与审计。"""
        if reason != 'INVALID_DUPLICATE_SCHEDULE_GENERATION':
            raise PermissionError('PLAN_CANCEL_REASON_REQUIRED')
        with self.store.connect(write=True) as db:
            plan = db.execute('SELECT * FROM publish_plans WHERE plan_id=?', (plan_id,)).fetchone()
            rows = db.execute('SELECT j.*,d.state AS dispatch_state,d.claimed_at,d.claim_token,d.worker_id '
                'FROM publish_jobs j JOIN startup_job_metadata m USING(job_id) '
                'LEFT JOIN startup_production_dispatch d USING(job_id) WHERE m.source_plan_id=?', (plan_id,)).fetchall()
            if not plan or not rows or {r['job_id'] for r in rows} != set(expected_job_ids):
                raise PermissionError('PLAN_CANCELLATION_SCOPE_MISMATCH')
            if plan['status'] == 'CANCELLED' and all(r['status']=='CANCELLED' for r in rows):
                return dict(plan_id=plan_id, status='CANCELLED', cancelled_jobs=len(rows), idempotent=True)
            if plan['status'] != 'CONFIRMED':
                raise PermissionError('CONFIRMED_STARTUP_PLAN_REQUIRED')
            for row in rows:
                attempted = db.execute("SELECT 1 FROM state_events WHERE job_id=? AND "
                    "(step IN (?, 'SUBMIT_INTENT', 'LOCAL_SUBMIT_RETURNED', 'PRODUCTION_ATOMIC_CLAIM', 'LOCAL_PUBLISH_STAGE') "
                    "OR outcome='SUBMIT_ATTEMPTED_DURABLE_BEFORE_UI')", (row['job_id'], RESERVE_STEP)).fetchone()
                if (attempted or row['status'] != 'NEEDS_MANUAL'
                    or row['current_step'] != 'STARTUP_CONFIRMED_NOT_DISPATCHED'
                    or row['dispatch_state'] != 'QUEUED' or row['claimed_at'] or row['claim_token'] or row['worker_id']
                    or row['external_work_id'] or row['external_work_url']
                    or db.execute('SELECT 1 FROM published_content WHERE content_id=?', (row['content_id'],)).fetchone()):
                    raise PermissionError('ACTIVE_OR_ATTEMPTED_PLAN_NO_CANCEL')
                guard_publish_job(db, row['job_id'])
            now = utc_now_iso()
            for row in rows:
                audit = json.dumps(dict(plan_id=plan_id, job_id=row['job_id'], content_id=row['content_id'],
                    cancel_reason=reason, cancelled_by='USER', cancelled_at=now,
                    previous_status=row['status'], previous_step=row['current_step'],
                    scheduled_at=row['scheduled_at'], submit_attempt_count=0), ensure_ascii=False, sort_keys=True)
                db.execute("UPDATE publish_jobs SET status='CANCELLED',current_step='USER_CANCELLED',"
                    'error_code=?,error_message=?,updated_at=? WHERE job_id=?', (reason, audit, now, row['job_id']))
                db.execute("UPDATE startup_production_dispatch SET state='BLOCKED',error_code='JOB_CANCELLED',"
                    'completed_at=? WHERE job_id=?', (now, row['job_id']))
                db.execute('INSERT INTO state_events(job_id,step,attempt,outcome,started_at,duration_ms) VALUES(?,?,?,?,?,0)',
                    (row['job_id'], 'PLAN_CANCELLED', 1, audit, now))
            db.execute("UPDATE publish_plans SET status='CANCELLED' WHERE plan_id=?", (plan_id,))
            released = []
            for content_id in sorted({r['content_id'] for r in rows}):
                if not db.execute("SELECT 1 FROM publish_jobs WHERE content_id=? AND status NOT IN ('CANCELLED','FAILED')",
                                  (content_id,)).fetchone():
                    changed = db.execute("UPDATE startup_contents SET publish_status='NOT_SCHEDULED' "
                        "WHERE content_id=? AND production_status='READY' AND publish_status='SCHEDULED'", (content_id,))
                    if changed.rowcount:
                        released.append(content_id)
            if db.execute('PRAGMA foreign_key_check').fetchall():
                raise RuntimeError('CANCELLATION_INTEGRITY_ERROR')
        return dict(plan_id=plan_id, status='CANCELLED', cancelled_jobs=len(rows),
                    released_content_ids=released, cancel_reason=reason, cancelled_at=now, submit_attempt_count=0)

    def record_scheduled_success(self, job_id, claim_token, proof, *, allow_reconciliation=False):
        """同一事务登记已同步；只认本次单击的严格关联证据，不标PUBLISHED。"""
        with self.store.connect(write=True) as db:
            row = db.execute('SELECT * FROM startup_production_dispatch WHERE job_id=?', (job_id,)).fetchone()
            if not row or row['claim_token'] != claim_token:
                raise PermissionError('PRODUCTION_CLAIM_REQUIRED')
            if row['state'] == 'SCHEDULED_QUEUED':
                return {'idempotent': True}
            policy = json.loads(row['context_json'])
            states = {'CLAIMED', 'SUBMIT_RESULT_UNCERTAIN'} if allow_reconciliation else {'CLAIMED'}
            if (row['state'] not in states or proof.get('verified') is not True
                or proof.get('job_id') != job_id or proof.get('content_id') != policy['content_id']
                or proof.get('scheduled_at') != policy['scheduled_at'] or proof.get('task_status') != '已同步'
                or proof.get('final_submit_invocations') != 1 or proof.get('account_id') != policy['account_id']):
                raise PermissionError('SCHEDULED_RESULT_NOT_VERIFIED')
            guard_publish_job(db, job_id)
            if db.execute('SELECT count(*) FROM state_events WHERE job_id=? AND step=?', (job_id, RESERVE_STEP)).fetchone()[0] != 1:
                raise PermissionError('SINGLE_DURABLE_SUBMIT_RESERVATION_REQUIRED')
            if file_digest(policy['video_path']) != policy['video_sha256']:
                raise PermissionError('VIDEO_CHANGED_AFTER_SUBMIT')
            db.execute("UPDATE publish_jobs SET status='SCHEDULED_QUEUED',current_step='UI_TASK_SYNCED_AWAIT_PLATFORM_PUBLICATION',error_code=NULL,error_message=NULL,updated_at=? WHERE job_id=?",
                       (utc_now_iso(), job_id))
            db.execute("UPDATE startup_contents SET publish_status='SUBMITTED' WHERE content_id=?", (policy['content_id'],))
            db.execute("UPDATE startup_production_dispatch SET state='SCHEDULED_QUEUED',completed_at=?,error_code=NULL WHERE job_id=?", (utc_now_iso(), job_id))
            db.execute('INSERT INTO state_events(job_id,step,attempt,outcome,started_at,duration_ms) VALUES(?,?,?,?,?,0)',
                       (job_id, 'PRODUCTION_SCHEDULED_RESULT_VERIFIED', 1, json.dumps(proof, ensure_ascii=False), utc_now_iso()))
        return {'job_id': job_id, 'content_status': 'SUBMITTED', 'job_status': 'SCHEDULED_QUEUED'}


def dispatch_confirmed_publish_jobs(store, token, plan_id, *, dry_run=True):
    """8502/正式服务入口；真实执行使用同一现有Worker，不接受客户端scope。"""
    dispatcher = ProductionDispatcher(store)
    if dry_run:
        return dispatcher.dry_dispatch(token, plan_id)
    from xiaovcat_adapter.desktop_worker.production_worker import run_plan
    return run_plan(dispatcher, token, plan_id)


class ProductionScope:
    """由已原子领取的正式Job生成，不读取/创建startup_real_acceptance_jobs。"""
    def __init__(self, dispatcher, job_id, claim_token, results):
        self.dispatcher, self.store = dispatcher, dispatcher.store
        self.job_id, self.results, self.claim_token = job_id, Path(results), claim_token
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM startup_production_dispatch WHERE job_id=?', (job_id,)).fetchone()
            if not row or row['state'] != 'CLAIMED' or row['claim_token'] != claim_token:
                raise PermissionError('PRODUCTION_CLAIM_REQUIRED')
            self.policy = json.loads(row['context_json'])
        self.confirmation = CONFIRMATION

    def check(self, policy):
        if policy != self.policy:
            raise PermissionError('PRODUCTION_CONTEXT_CHANGED')
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM startup_production_dispatch WHERE job_id=?', (self.job_id,)).fetchone()
            if (not row or row['state'] != 'CLAIMED' or row['claim_token'] != self.claim_token
                or json.loads(row['context_json']) != policy):
                raise PermissionError('PRODUCTION_CLAIM_LOST')
            if self.dispatcher._context(db, self.job_id, claimed=True) != policy:
                raise PermissionError('PRODUCTION_LIVE_CONTEXT_CHANGED')
        return policy
