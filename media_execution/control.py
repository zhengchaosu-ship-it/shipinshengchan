"""Server持久执行账本：业务任务保持原ID，候选集合排序后原子领取。"""
from contextlib import contextmanager, closing
from dataclasses import dataclass
import json
import hashlib
import math
from pathlib import Path
import re
import secrets
import sqlite3
import time


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


@dataclass(frozen=True)
class Policy:
    ready_backlog_limit_per_account: int = 15
    lease_seconds: int = 120
    # 沿用既有抖音LOCAL的8100秒安全提前量；P0相对提交截止时间。
    minimum_publish_lead_seconds: int = 8100
    maximum_publish_horizon_seconds: int = 14 * 86400
    urgent_deadline_seconds: int = 1800

    def __post_init__(self):
        if any(type(v) is not int or v <= 0 for v in self.__dict__.values()):
            raise ValueError('INVALID_EXECUTION_POLICY')
        if self.minimum_publish_lead_seconds >= self.maximum_publish_horizon_seconds:
            raise ValueError('INVALID_SCHEDULE_WINDOW')


WAITING = {'WAITING', 'READY_TO_PUBLISH', 'WAITING_FOR_RENDER',
           'WAITING_FOR_WORKSTATION', 'WAITING_ACCOUNT_RECOVERY', 'RENDER_BACKLOG_PAUSED',
           'PUBLISH_NETWORK_ATTENTION', 'WAITING_PUBLISHER_INFRA'}
RENDER_STAGES = ('RENDER_PREPARING', 'RENDERING', 'EXPORTING', 'OUTPUT_VERIFYING')
PUBLISH_STAGES = ('PUBLISH_PREPARING', 'PROVIDER_UPLOADING', 'PROVIDER_VALIDATED',
                  'SUBMIT_INTENT', 'PROVIDER_SUBMITTING', 'PUBLISH_RECONCILING')
GATES = {'OPEN', 'CONDITIONAL_OPEN', 'BLOCKED_AUTH', 'BLOCKED_RISK', 'BLOCKED_MANUAL_ACTION', 'PAUSED_BY_USER'}


class ControlPlane:
    def __init__(self, path, *, policy=None, clock=time.time, authorize=None):
        self.path = Path(path).resolve()
        self.policy = policy or Policy()
        self.clock = clock
        # 正式接线须由既有Planner/授权层实现；缺失则不能领取/提交。
        self.authorize = authorize or (lambda db, job: False)

    @contextmanager
    def connect(self, *, write=False):
        with closing(sqlite3.connect(self.path, timeout=30)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            if write:
                db.execute('BEGIN IMMEDIATE')
            try:
                yield db
                if write:
                    db.commit()
            except BaseException:
                db.rollback()
                raise

    def migrate(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        from production_autopilot.account_runtime import migrate
        with self.connect(write=True) as db:
            migrate(db)
        with self.connect() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='media_execution_schema'").fetchone():
                if db.execute('SELECT 1 FROM media_execution_schema WHERE version=1').fetchone():
                    return
            backup = self.path.with_name(self.path.name + '.before-media-execution.bak')
            if not backup.exists():
                with closing(sqlite3.connect(backup)) as out:
                    db.backup(out)
        with self.connect(write=True) as db:
            statement = ''
            for line in Path(__file__).with_name('migrations').joinpath('001_execution.sql').read_text('utf-8').splitlines(True):
                statement += line
                if sqlite3.complete_statement(statement):
                    db.execute(statement)
                    statement = ''
            db.execute('INSERT OR IGNORE INTO media_execution_schema VALUES(1,?)', (self.clock(),))

    def event(self, db, event, job=None, evidence=None):
        db.execute('INSERT INTO media_execution_events(at,job_type,job_id,event,evidence_json) VALUES(?,?,?,?,?)',
                   (self.clock(), job['job_type'] if job else None, job['job_id'] if job else None,
                    event, encoded(evidence or {})))

    def enroll(self, job_type, job_id, worker_id, business_account_id, content_id, payload,
               *, scheduled_at=None):
        """Server内部接线调用；不提供Worker enrollment API，不扫描历史任务。"""
        if job_type not in ('RENDER', 'PUBLISH') or not all(
                isinstance(v, str) and v and len(v) <= 160 for v in (job_id, worker_id, business_account_id, content_id)):
            raise ValueError('INVALID_JOB_IDENTITY')
        if job_type == 'PUBLISH':
            if not isinstance(scheduled_at, (float, int)) or not math.isfinite(scheduled_at):
                raise ValueError('SERVER_SCHEDULE_REQUIRED')
            if not payload.get('provider_account_id') or not payload.get('render_job_id'):
                raise ValueError('RENDER_AND_PROVIDER_IDENTITY_REQUIRED')
        values = (job_type, job_id, worker_id, business_account_id, content_id, encoded(payload))
        with self.connect(write=True) as db:
            old = db.execute('SELECT * FROM media_execution_jobs WHERE job_type=? AND job_id=?', values[:2]).fetchone()
            if old:
                if tuple(old[k] for k in ('job_type','job_id','worker_id','business_account_id','content_id','payload_json')) != values or old['scheduled_at'] != scheduled_at:
                    raise PermissionError('EXECUTION_IDENTITY_IMMUTABLE')
                return
            db.execute('INSERT INTO media_execution_jobs(job_type,job_id,worker_id,business_account_id,content_id,'
                       'payload_json,created_at,state,scheduled_at) VALUES(?,?,?,?,?,?,?,?,?)',
                       (*values, self.clock(), 'WAITING' if job_type == 'RENDER' else 'WAITING_FOR_RENDER', scheduled_at))
            self.event(db, 'SERVER_JOB_ENROLLED', {'job_type':job_type,'job_id':job_id})

    def row(self, job_type, job_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM media_execution_jobs WHERE job_type=? AND job_id=?', (job_type,job_id)).fetchone()
            return dict(row) if row else None

    def cancel(self, job_type, job_id):
        """Server取消尚未开始的原任务；在途任务禁止抢占。"""
        with self.connect(write=True) as db:
            job = db.execute('SELECT * FROM media_execution_jobs WHERE job_type=? AND job_id=?', (job_type,job_id)).fetchone()
            if not job or job['submit_attempt_count'] or job['state'] not in WAITING | {'WAITING_REPLAN','STALE_SCHEDULE'}:
                raise PermissionError('UNSTARTED_UNSUBMITTED_JOB_REQUIRED')
            if db.execute('SELECT 1 FROM media_execution_leases WHERE job_type=? AND job_id=?', (job_type,job_id)).fetchone():
                raise PermissionError('ACTIVE_JOB_NON_PREEMPTIBLE')
            db.execute("UPDATE media_execution_jobs SET state='CANCELLED' WHERE job_type=? AND job_id=?", (job_type,job_id))
            self.event(db,'SERVER_CANCELLED',job)

    def accept_replan(self, job_id, scheduled_at, *, planner_approve):
        """仅恢复仍有效的原slot；任何改时追补均拒绝。"""
        with self.connect(write=True) as db:
            job = db.execute("SELECT * FROM media_execution_jobs WHERE job_type='PUBLISH' AND job_id=?", (job_id,)).fetchone()
            if not job or job['state'] not in ('WAITING_REPLAN','STALE_SCHEDULE') or job['submit_attempt_count'] or job['intent_json']:
                raise PermissionError('UNSUBMITTED_REPLAN_REQUIRED')
            if not isinstance(scheduled_at,(int,float)) or not math.isfinite(scheduled_at):
                raise ValueError('INVALID_SCHEDULE')
            if scheduled_at != job['scheduled_at']:
                raise PermissionError('SLOT_CATCH_UP_FORBIDDEN')
            if not self.policy.minimum_publish_lead_seconds <= scheduled_at-self.clock() <= self.policy.maximum_publish_horizon_seconds:
                raise ValueError('SCHEDULE_OUTSIDE_SAFE_WINDOW')
            # 回调必须在此事务内核验当日已发布/已预留总量<=5及内容去重；没有回调拒绝。
            if not callable(planner_approve) or planner_approve(db,dict(job),scheduled_at) is not True:
                raise PermissionError('DAILY_PLANNER_APPROVAL_REQUIRED')
            candidate = dict(job,state='READY_TO_PUBLISH',scheduled_at=scheduled_at)
            if self._eligibility(db,candidate)!='RUNNABLE':
                raise PermissionError('REPLANNED_JOB_NOT_ELIGIBLE')
            db.execute("UPDATE media_execution_jobs SET scheduled_at=?,state='READY_TO_PUBLISH' WHERE job_type='PUBLISH' AND job_id=?", (scheduled_at,job_id))
            self.event(db,'ORIGINAL_SLOT_RESTORED',job,{'scheduled_at':scheduled_at,'schedule_changed':False})

    def set_account(self, account, gate, provider_status, *, reason=None, provider_error=None):
        if gate not in GATES or provider_status not in ('ONLINE','OFFLINE','UNKNOWN'):
            raise ValueError('INVALID_ACCOUNT_GATE')
        with self.connect(write=True) as db:
            self._account(db, account, gate, provider_status, reason, provider_error)

    def _account(self, db, account, gate, status, reason, error):
        old = db.execute('SELECT * FROM media_account_publish_gates WHERE business_account_id=?', (account,)).fetchone()
        if old and (gate not in ('OPEN','CONDITIONAL_OPEN','PAUSED_BY_USER') or status=='OFFLINE'):
            from production_autopilot.manual_recovery import mark_reblocked,current_ack
            if current_ack(db,account):
                gate='BLOCKED_RISK'
                mark_reblocked(db,account,reason,self.clock())
        first = (old['first_seen_at'] if old and old['gate'] != 'OPEN' else self.clock()) if gate != 'OPEN' else None
        db.execute('INSERT INTO media_account_publish_gates VALUES(?,?,?,?,?,?,?) ON CONFLICT(business_account_id) '
                   'DO UPDATE SET gate=excluded.gate,provider_account_status=excluded.provider_account_status,'
                   'block_reason=excluded.block_reason,provider_error=excluded.provider_error,'
                   'first_seen_at=excluded.first_seen_at,checked_at=excluded.checked_at',
                   (account,gate,status,reason,encoded(error),first,self.clock()))
        self.event(db, 'ACCOUNT_GATE_OBSERVED', evidence={'business_account_id':account,'gate':gate,'reason':reason})
        if gate not in ('OPEN','CONDITIONAL_OPEN','PAUSED_BY_USER') or status != 'ONLINE':
            from production_autopilot.account_runtime import pause
            pause(db,account,reason or 'ACCOUNT_AUTH_EXPIRED',now=self.clock())
        if gate == 'OPEN' and old and old['gate'] != 'OPEN':
            # 恢复只进入Planner待处理状态；绝不瞬间倾倒历史READY积压。
            db.execute("UPDATE media_execution_jobs SET state='WAITING_REPLAN' WHERE business_account_id=? "
                       "AND job_type='PUBLISH' AND state='WAITING_ACCOUNT_RECOVERY' AND submit_attempt_count=0",
                       (account,))

    def set_infrastructure(self, worker, state, reason=None):
        if state not in ('ONLINE','OFFLINE','DEGRADED','PUBLISH_NETWORK_ATTENTION'):
            raise ValueError('INVALID_INFRASTRUCTURE_STATE')
        with self.connect(write=True) as db:
            self._infrastructure(db, worker, state, reason)

    def _infrastructure(self, db, worker, state, reason):
        db.execute('INSERT INTO media_publisher_infrastructure VALUES(?,?,?,?) ON CONFLICT(worker_id) '
                   'DO UPDATE SET state=excluded.state,reason=excluded.reason,checked_at=excluded.checked_at',
                   (worker,state,reason,self.clock()))

    def _eligibility(self, db, job):
        if job['state'] not in WAITING or job['submit_attempt_count'] or job['intent_json']:
            return None
        from production_autopilot.account_runtime import allowed
        if not allowed(db,job['business_account_id']):
            return 'ACCOUNT_RUNTIME_PAUSED'
        if not self.authorize(db, dict(job)):
            return 'WAITING_AUTHORIZATION'
        if job['retry_not_before'] > self.clock():
            return 'RETRY_NOT_BEFORE'
        gate = db.execute('SELECT * FROM media_account_publish_gates WHERE business_account_id=?',
                          (job['business_account_id'],)).fetchone()
        if job['job_type'] == 'RENDER':
            health=(db.execute('SELECT received_at,details_json FROM media_execution_worker_health WHERE worker_id=?',
                               (job['worker_id'],)).fetchone() if db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='media_execution_worker_health'").fetchone() else None)
            if health:
                automation=json.loads(health['details_json']).get('jianying_automation')
                if automation and (automation.get('state')!='READY' or self.clock()-health['received_at']>=90):
                    return 'WAITING_FOR_WORKSTATION'
            if gate and gate['gate'] not in ('OPEN','CONDITIONAL_OPEN'):
                ready = db.execute("SELECT count(*) FROM media_execution_outputs o JOIN media_execution_jobs r "
                    "ON r.job_type='RENDER' AND r.job_id=o.render_job_id WHERE r.business_account_id=? AND NOT EXISTS "
                    "(SELECT 1 FROM media_execution_jobs p WHERE p.content_id=o.content_id AND p.job_type='PUBLISH' "
                    "AND p.state='PUBLISHED')", (job['business_account_id'],)).fetchone()[0]
                if ready >= self.policy.ready_backlog_limit_per_account:
                    return 'RENDER_BACKLOG_PAUSED'
            return 'RUNNABLE'
        seconds = job['scheduled_at'] - self.clock()
        if seconds < self.policy.minimum_publish_lead_seconds:
            return 'STALE_SCHEDULE'
        if not gate or gate['gate'] not in ('OPEN','CONDITIONAL_OPEN') or gate['provider_account_status'] != 'ONLINE':
            return 'WAITING_ACCOUNT_RECOVERY'
        infra = db.execute('SELECT state FROM media_publisher_infrastructure WHERE worker_id=?', (job['worker_id'],)).fetchone()
        if not infra or infra['state'] != 'ONLINE':
            return 'PUBLISH_NETWORK_ATTENTION' if infra and infra['state'] == 'PUBLISH_NETWORK_ATTENTION' else 'WAITING_PUBLISHER_INFRA'
        if seconds > self.policy.maximum_publish_horizon_seconds:
            return 'SCHEDULE_WINDOW_NOT_READY'
        output = db.execute('SELECT * FROM media_execution_outputs WHERE content_id=? AND worker_id=?',
                            (job['content_id'], job['worker_id'])).fetchone()
        if not output or output['render_job_id'] != json.loads(job['payload_json'])['render_job_id']:
            return 'WAITING_FOR_RENDER'
        return 'RUNNABLE'

    def _candidates(self, db, worker, *, update=False):
        candidates = []
        for job in db.execute('SELECT * FROM media_execution_jobs WHERE worker_id=?', (worker,)).fetchall():
            reason = self._eligibility(db, job)
            if reason == 'RUNNABLE':
                deadline = job['scheduled_at'] or float('inf')
                priority = (0 if deadline-self.clock()-self.policy.minimum_publish_lead_seconds <= self.policy.urgent_deadline_seconds else 1) if job['job_type']=='PUBLISH' else 2
                candidates.append((priority,deadline,job['created_at'],job['job_id'],dict(job)))
            elif update and reason in WAITING | {'STALE_SCHEDULE'}:
                if job['state'] != reason:
                    db.execute('UPDATE media_execution_jobs SET state=? WHERE job_type=? AND job_id=?',
                               (reason,job['job_type'],job['job_id']))
                    self.event(db, reason, job)
        candidates.sort(key=lambda item:item[:4])
        return [item[-1] for item in candidates]

    def pending_provider_execution(self, db, worker):
        # 本机CLI返回任务ID后，蚁小二客户端仍可能继续上传/提交。
        # 只读对账确认完成或失败之前，不可把“CLI已退出”当成重任务结束。
        return db.execute("SELECT * FROM media_execution_jobs WHERE worker_id=? AND job_type='PUBLISH' "
            "AND submit_attempt_count=1 AND state NOT IN ('SCHEDULED_QUEUED','PUBLISHED','FAILED_JOB_LEVEL','CANCELLED') "
            "ORDER BY created_at LIMIT 1",(worker,)).fetchone()

    def claim(self, worker):
        with self.connect(write=True) as db:
            candidates = self._candidates(db, worker, update=True)
            # 到期租约也不删除：先证明旧执行器停止并恢复journal，禁止超时抢占。
            if db.execute('SELECT 1 FROM media_execution_leases WHERE worker_id=?', (worker,)).fetchone():
                for job in candidates:
                    db.execute("UPDATE media_execution_jobs SET state='WAITING_FOR_WORKSTATION' WHERE job_type=? AND job_id=?",
                               (job['job_type'],job['job_id']))
                return None
            if not candidates:
                return None
            job = candidates[0]
            token = secrets.token_hex(32)
            stage = RENDER_STAGES[0] if job['job_type']=='RENDER' else PUBLISH_STAGES[0]
            now = self.clock()
            db.execute('INSERT INTO media_execution_leases VALUES(?,?,?,?,?,?,?,?)',
                       (worker,job['job_type'],job['job_id'],token,now,now,now+self.policy.lease_seconds,stage))
            db.execute('UPDATE media_execution_jobs SET state=? WHERE job_type=? AND job_id=?',
                       (stage,job['job_type'],job['job_id']))
            self.event(db, 'EXECUTION_LEASE_ACQUIRED', job, {'worker_id':worker})
            return dict(job, state=stage, lease_token=token, payload=json.loads(job['payload_json']))

    def claim_reconciliation(self, worker):
        with self.connect(write=True) as db:
            db.execute('DELETE FROM media_reconciliation_leases WHERE expires_at<=?', (self.clock(),))
            if db.execute('SELECT 1 FROM media_reconciliation_leases WHERE worker_id=?', (worker,)).fetchone():
                return None
            job = db.execute("SELECT j.* FROM media_execution_jobs j LEFT JOIN media_reconciliation_schedule s USING(job_id) "
                "WHERE j.worker_id=? AND j.job_type='PUBLISH' AND j.submit_attempt_count=1 "
                "AND j.state IN ('SUBMIT_INTENT','SUBMIT_RESULT_UNCERTAIN','SUBMITTED','SCHEDULED_QUEUED') "
                "AND COALESCE(s.next_check_at,0)<=? AND NOT EXISTS(SELECT 1 FROM media_execution_leases h WHERE h.job_id=j.job_id) "
                "ORDER BY COALESCE(s.next_check_at,0),j.created_at,j.job_id LIMIT 1", (worker,self.clock())).fetchone()
            if not job:
                return None
            token = secrets.token_hex(32)
            now = self.clock()
            db.execute("INSERT INTO media_reconciliation_leases VALUES(?,?,?,?,?,?,?,'PUBLISH_RECONCILING')",
                       (worker,'PUBLISH',job['job_id'],token,now,now,now+self.policy.lease_seconds))
            db.execute('INSERT INTO media_reconciliation_schedule VALUES(?,?,NULL) ON CONFLICT(job_id) DO UPDATE SET next_check_at=excluded.next_check_at',
                       (job['job_id'],now+60))
            return dict(job,lease_token=token,payload=json.loads(job['payload_json']),reconcile_only=True)

    def record_reconciliation(self, worker, token, response):
        with self.connect(write=True) as db:
            lease,job = self._query_owner(db,worker,token)
            if lease['stage']!='PUBLISH_RECONCILING' or job['submit_attempt_count']!=1:
                raise PermissionError('READ_ONLY_RECONCILIATION_REQUIRED')
            state = response.get('state')
            if state not in ('SUBMIT_RESULT_UNCERTAIN','SUBMITTED','SCHEDULED_QUEUED','PUBLISHED','FAILED_JOB_LEVEL'):
                raise ValueError('INVALID_RECONCILIATION_STATE')
            if state=='PUBLISHED' and not response.get('public_evidence'):
                raise ValueError('PUBLIC_EVIDENCE_REQUIRED')
            from production_autopilot.manual_recovery import provider_risk
            if provider_risk(response.get('provider_response',{})):
                state='FAILED_JOB_LEVEL';response=dict(response,state=state)
            if state not in ('SUBMIT_RESULT_UNCERTAIN','FAILED_JOB_LEVEL') and not response.get('provider_task_id'):
                raise ValueError('PROVIDER_TASK_ID_REQUIRED')
            for key in ('provider_task_id','provider_video_id'):
                if job[key] and response.get(key) not in (None,job[key]):
                    raise PermissionError('PROVIDER_IDENTITY_IMMUTABLE')
            # 已有排期事实不因平台公开等待回到SUBMITTED。重复观察不重写历史行。
            if job['state'] == 'SCHEDULED_QUEUED' and state in ('SUBMITTED','SUBMIT_RESULT_UNCERTAIN','SCHEDULED_QUEUED'):
                state = 'SCHEDULED_QUEUED'
            if state == job['state']:
                db.execute('DELETE FROM media_reconciliation_leases WHERE worker_id=?', (worker,))
                return
            if state=='FAILED_JOB_LEVEL':
                from .coordinator import classify_failure
                failure=provider_risk(response.get('provider_response',{})) or classify_failure(RuntimeError(encoded(response.get('provider_response',{}))))
                if failure.domain=='ACCOUNT_LEVEL':
                    self._account(db,job['business_account_id'],failure.gate,'UNKNOWN',failure.reason,response.get('provider_response'))
                    db.execute("UPDATE media_execution_jobs SET failure_domain=?,error_json=? WHERE job_type='PUBLISH' AND job_id=?",
                        (failure.domain,encoded({'reason':failure.reason,'evidence':response.get('provider_response')}),job['job_id']))
            db.execute("UPDATE media_execution_jobs SET state=?,provider_response=?,provider_task_id=COALESCE(?,provider_task_id),"
                       "provider_video_id=COALESCE(?,provider_video_id),reconciliation_status=?,retry_not_before=? "
                       "WHERE job_type='PUBLISH' AND job_id=?", (state,encoded(response),response.get('provider_task_id'),
                       response.get('provider_video_id'),'REQUIRED' if state=='SUBMIT_RESULT_UNCERTAIN' else 'OBSERVED',
                       self.clock()+60,job['job_id']))
            self.event(db,'READ_ONLY_RECONCILIATION_OBSERVED',job,response)
            from production_autopilot.manual_recovery import observe_success
            observe_success(db,job,response,self.clock())
            db.execute('DELETE FROM media_reconciliation_leases WHERE worker_id=?', (worker,))

    def _query_owner(self, db, worker, token):
        lease = db.execute('SELECT * FROM media_reconciliation_leases WHERE worker_id=? AND lease_token=?', (worker,token)).fetchone()
        if not lease or lease['expires_at'] <= self.clock():
            raise PermissionError('RECONCILIATION_LEASE_REQUIRED')
        job = db.execute("SELECT * FROM media_execution_jobs WHERE job_type='PUBLISH' AND job_id=?", (lease['job_id'],)).fetchone()
        return lease,job

    def reconciliation_error(self, worker, token, error):
        with self.connect(write=True) as db:
            _,job = self._query_owner(db,worker,token)
            db.execute('UPDATE media_reconciliation_schedule SET last_error=?,next_check_at=? WHERE job_id=?',
                       (str(error),self.clock()+60,job['job_id']))
            db.execute('DELETE FROM media_reconciliation_leases WHERE worker_id=?', (worker,))

    def _owner(self, db, worker, token, *, allow_expired=False):
        lease = db.execute('SELECT * FROM media_execution_leases WHERE worker_id=?', (worker,)).fetchone()
        if not lease or not secrets.compare_digest(lease['lease_token'], str(token)):
            raise PermissionError('EXECUTION_LEASE_MISMATCH')
        if not allow_expired and lease['expires_at'] <= self.clock():
            raise PermissionError('EXECUTION_LEASE_EXPIRED_NEEDS_RECOVERY')
        job = db.execute('SELECT * FROM media_execution_jobs WHERE job_type=? AND job_id=?',
                         (lease['job_type'],lease['job_id'])).fetchone()
        return lease, job

    def heartbeat(self, worker, token):
        with self.connect(write=True) as db:
            query = db.execute('SELECT 1 FROM media_reconciliation_leases WHERE worker_id=? AND lease_token=?', (worker,token)).fetchone()
            if query:
                self._query_owner(db,worker,token)
                return  # 只读查询有固定预算，不允许无限续期。
            self._owner(db, worker, token)
            db.execute('UPDATE media_execution_leases SET heartbeat_at=?,expires_at=? WHERE worker_id=?',
                       (self.clock(),self.clock()+self.policy.lease_seconds,worker))

    def stage(self, worker, token, stage):
        with self.connect(write=True) as db:
            lease, job = self._owner(db, worker, token)
            stages = RENDER_STAGES if job['job_type']=='RENDER' else PUBLISH_STAGES
            if stage not in stages or stage == 'SUBMIT_INTENT':
                raise PermissionError('INVALID_EXECUTION_STAGE')
            if stages.index(stage) < stages.index(lease['stage']):
                raise PermissionError('EXECUTION_STAGE_REGRESSION')
            if stage in ('PROVIDER_SUBMITTING','PUBLISH_RECONCILING') and not job['submit_attempt_count']:
                raise PermissionError('SUBMIT_INTENT_REQUIRED')
            db.execute('UPDATE media_execution_leases SET stage=? WHERE worker_id=?', (stage,worker))
            db.execute('UPDATE media_execution_jobs SET state=? WHERE job_type=? AND job_id=?', (stage,job['job_type'],job['job_id']))
            self.event(db, stage, job)

    def reserve_submit(self, worker, token, intent):
        with self.connect(write=True) as db:
            lease, job = self._owner(db, worker, token)
            if job['job_type'] != 'PUBLISH' or job['submit_attempt_count'] or job['intent_json']:
                raise PermissionError('SUBMIT_ONCE_LATCH_CONSUMED')
            if lease['stage'] != 'PROVIDER_VALIDATED':
                raise PermissionError('PROVIDER_VALIDATION_REQUIRED')
            candidate = dict(job, state='READY_TO_PUBLISH')
            if self._eligibility(db,candidate) != 'RUNNABLE':
                raise PermissionError('PUBLISH_NO_LONGER_ELIGIBLE')
            for field in ('payload_sha256','request_hash'):
                if not re.fullmatch('[a-f0-9]{64}', str(intent.get(field,''))):
                    raise ValueError('FROZEN_PAYLOAD_HASH_REQUIRED')
            if intent.get('scheduledTime') != int(job['scheduled_at']*1000):
                raise PermissionError('FROZEN_SCHEDULE_CHANGED')
            db.execute("UPDATE media_execution_jobs SET submit_attempt_count=1,intent_json=?,state='SUBMIT_INTENT' "
                       "WHERE job_type='PUBLISH' AND job_id=?", (encoded(intent),job['job_id']))
            db.execute("UPDATE media_execution_leases SET stage='SUBMIT_INTENT' WHERE worker_id=?", (worker,))
            self.event(db, 'SUBMIT_INTENT', job, intent)
            from production_autopilot.manual_recovery import bind_submit_intent
            bind_submit_intent(db,job,self.clock())
        # 此返回丢失时Worker不能重试reserve后直接POST。只能恢复/对账。
        return {'submit_reserved':True}

    def publish_input(self, worker, token):
        with self.connect() as db:
            query = db.execute('SELECT 1 FROM media_reconciliation_leases WHERE worker_id=? AND lease_token=?', (worker,token)).fetchone()
            _, job = self._query_owner(db,worker,token) if query else self._owner(db,worker,token)
            if job['job_type']!='PUBLISH':
                raise PermissionError('UNSUBMITTED_PUBLISH_LEASE_REQUIRED')
            payload = json.loads(job['payload_json'])
            output = db.execute('SELECT * FROM media_execution_outputs WHERE content_id=? AND worker_id=?',
                                (job['content_id'],worker)).fetchone()
            if not output:
                raise ValueError('VERIFIED_LOCAL_OUTPUT_REQUIRED')
            contract = dict(payload['publish_contract'])
            from datetime import datetime, timezone
            contract.update(business_account_id=job['business_account_id'],provider_account_id=payload['provider_account_id'],
                scheduled_at=datetime.fromtimestamp(job['scheduled_at'],timezone.utc).isoformat(),
                video_path=output['local_output_path'],video_sha256=output['output_sha256'])
            if job['submit_attempt_count']:
                intent = json.loads(job['intent_json'])
                response = json.loads(job['provider_response'] or '{}')
                contract.update(state=job['state'],submit_attempt_count=job['submit_attempt_count'],intent_json=job['intent_json'],
                    payload_sha256=intent.get('payload_sha256'),request_hash=intent.get('request_hash'),
                    provider_task_set_id=response.get('provider_task_set_id'),provider_task_id=job['provider_task_id'],
                    provider_video_id=job['provider_video_id'],provider_video_url=None)
            return contract

    def complete_render(self, worker, token, output):
        with self.connect(write=True) as db:
            lease, job = self._owner(db,worker,token)
            if job['job_type'] != 'RENDER' or lease['stage'] != 'OUTPUT_VERIFYING':
                raise PermissionError('OUTPUT_VERIFYING_REQUIRED')
            validate_output(output)
            expected = json.loads(job['payload_json'])
            media = output['media']
            for field in ('width','height','codec'):
                if field in expected and expected[field] != media[field]:
                    raise ValueError('RENDER_OUTPUT_CONTRACT_MISMATCH')
            if 'fps' in expected:
                a,b = media['fps'].split('/')
                if abs(float(a)/float(b)-float(expected['fps']))>.02:
                    raise ValueError('RENDER_OUTPUT_FPS_MISMATCH')
            if 'duration' in expected and abs(expected['duration']-media['duration']) > max(2,expected['duration']*.02):
                raise ValueError('RENDER_DURATION_MISMATCH')
            db.execute('INSERT INTO media_execution_outputs(content_id,render_job_id,worker_id,local_output_path,'
                       'output_sha256,media_json,render_completed_at) VALUES(?,?,?,?,?,?,?)',
                       (job['content_id'],job['job_id'],worker,output['local_output_path'],media['sha256'],encoded(media),self.clock()))
            db.execute("UPDATE media_execution_jobs SET state='COMPLETED' WHERE job_type='RENDER' AND job_id=?", (job['job_id'],))
            self.event(db, 'RENDER_READY_ARCHIVE_PENDING', job, output)
            db.execute('DELETE FROM media_execution_leases WHERE worker_id=?', (worker,))

    def complete_publish(self, worker, token, response):
        with self.connect(write=True) as db:
            lease, job = self._owner(db,worker,token)
            if job['job_type'] != 'PUBLISH' or not job['submit_attempt_count']:
                raise PermissionError('SUBMIT_INTENT_REQUIRED')
            state = response.get('state')
            if state not in ('SUBMITTED','SCHEDULED_QUEUED','PUBLISHED','FAILED_JOB_LEVEL') or not response.get('provider_task_id'):
                raise ValueError('PROVIDER_RESULT_REQUIRED')
            from production_autopilot.manual_recovery import provider_risk
            if provider_risk(response.get('provider_response',{})):
                state='FAILED_JOB_LEVEL';response=dict(response,state=state)
            if state=='PUBLISHED' and not response.get('public_evidence'):
                raise ValueError('PUBLIC_EVIDENCE_REQUIRED')
            if state=='FAILED_JOB_LEVEL':
                from .coordinator import classify_failure
                failure=provider_risk(response.get('provider_response',{})) or classify_failure(RuntimeError(encoded(response.get('provider_response',{}))))
                if failure.domain=='ACCOUNT_LEVEL':
                    self._account(db,job['business_account_id'],failure.gate,'UNKNOWN',failure.reason,response.get('provider_response'))
                db.execute("UPDATE media_execution_jobs SET failure_domain=?,error_json=? WHERE job_type='PUBLISH' AND job_id=?",
                    (failure.domain,encoded({'reason':failure.reason,'evidence':response.get('provider_response')}),job['job_id']))
            db.execute("UPDATE media_execution_jobs SET state=?,provider_response=?,provider_task_id=?,provider_video_id=?,"
                       "reconciliation_status='OBSERVED' WHERE job_type='PUBLISH' AND job_id=?",
                       (state,encoded(response),response['provider_task_id'],response.get('provider_video_id'),job['job_id']))
            self.event(db, 'PROVIDER_RESULT_OBSERVED', job, response)
            from production_autopilot.manual_recovery import observe_success
            observe_success(db,job,response,self.clock())
            db.execute('DELETE FROM media_execution_leases WHERE worker_id=?', (worker,))

    def fail(self, worker, token, domain, reason, *, gate=None, evidence=None):
        if domain not in ('JOB_LEVEL','ACCOUNT_LEVEL','INFRA_LEVEL'):
            raise ValueError('INVALID_FAILURE_DOMAIN')
        with self.connect(write=True) as db:
            lease, job = self._owner(db,worker,token,allow_expired=True)
            from production_autopilot.manual_recovery import provider_risk,current_ack
            if job['job_type']=='PUBLISH' and current_ack(db,job['business_account_id']):
                risk=provider_risk({'reason':reason,'evidence':evidence})
                if risk:domain,gate='ACCOUNT_LEVEL','BLOCKED_RISK'
            from production_autopilot.account_runtime import fault
            fault(db,domain,job['business_account_id'],job['job_id'],reason,
                  '此任务已隔离，其他任务继续执行' if domain=='JOB_LEVEL' else str(reason),self.clock())
            state = 'FAILED_JOB_LEVEL'
            if job['job_type']=='PUBLISH':
                if domain=='ACCOUNT_LEVEL':
                    if gate not in GATES-{'OPEN','CONDITIONAL_OPEN','PAUSED_BY_USER'}:
                        raise ValueError('ACCOUNT_BLOCK_GATE_REQUIRED')
                    self._account(db,job['business_account_id'],gate,'UNKNOWN',reason,evidence)
                    state = 'WAITING_ACCOUNT_RECOVERY'
                elif domain=='INFRA_LEVEL':
                    infra = 'PUBLISH_NETWORK_ATTENTION' if reason=='PUBLISH_NETWORK_ATTENTION' else 'DEGRADED'
                    self._infrastructure(db,worker,infra,reason)
                    state = infra if infra=='PUBLISH_NETWORK_ATTENTION' else 'WAITING_PUBLISHER_INFRA'
                # Intent之后任何不确定异常保留闩锁，只能对账，不把账号恢复等同于重POST。
                if job['submit_attempt_count']:
                    state = 'SUBMIT_RESULT_UNCERTAIN'
            db.execute('UPDATE media_execution_jobs SET state=?,failure_domain=?,error_json=?,reconciliation_status=? '
                       'WHERE job_type=? AND job_id=?', (state,domain,encoded({'reason':reason,'evidence':evidence}),
                       'REQUIRED' if job['submit_attempt_count'] else None,job['job_type'],job['job_id']))
            self.event(db, 'EXECUTION_FAILED', job, {'domain':domain,'reason':reason,'state':state})
            db.execute('DELETE FROM media_execution_leases WHERE worker_id=?', (worker,))
            return state

    def recovery(self, worker, *, executor_quiescent, journal=None):
        """必须先持有本机Mutex并证实旧子进程停止；只恢复同一个Job。"""
        if executor_quiescent is not True:
            raise PermissionError('OLD_EXECUTOR_QUIESCENCE_REQUIRED')
        with self.connect(write=True) as db:
            lease = db.execute('SELECT * FROM media_execution_leases WHERE worker_id=?', (worker,)).fetchone()
            if not lease:
                return None
            job = db.execute('SELECT * FROM media_execution_jobs WHERE job_type=? AND job_id=?',
                             (lease['job_type'],lease['job_id'])).fetchone()
            if job['job_type']=='RENDER' and db.execute("SELECT 1 FROM sqlite_master WHERE name='media_execution_worker_health'").fetchone():
                health=db.execute('SELECT received_at,details_json FROM media_execution_worker_health WHERE worker_id=?',(worker,)).fetchone()
                automation=json.loads(health['details_json']).get('jianying_automation') if health else None
                if automation and (automation.get('state')!='READY' or self.clock()-health['received_at']>=90):
                    raise RuntimeError('RENDER_AUTOMATION_NOT_READY_NO_RECOVERY')
            if journal and any(journal.get(k) != lease[k] for k in ('worker_id','job_type','job_id','lease_token')):
                same_job=all(journal.get(k)==lease[k] for k in ('worker_id','job_type','job_id'))
                last=db.execute("SELECT evidence_json FROM media_execution_events WHERE job_type=? AND job_id=? AND event='RESTART_SAME_RENDER_VERIFY_FIRST' ORDER BY id DESC LIMIT 1",(job['job_type'],job['job_id'])).fetchone()
                previous=hashlib.sha256(str(journal.get('lease_token','')).encode()).hexdigest()
                if same_job and job['job_type']=='RENDER' and lease['stage']=='RENDER_PREPARING' and last and json.loads(last[0]).get('previous_lease_sha256')==previous:
                    return dict(job,state='RENDER_PREPARING',lease_token=lease['lease_token'],payload=json.loads(job['payload_json']),recover_render=True)
                raise PermissionError('EXECUTION_JOURNAL_IDENTITY_MISMATCH')
            if job['submit_attempt_count'] or job['intent_json']:
                if job['state'] in ('SCHEDULED_QUEUED','PUBLISHED','FAILED_JOB_LEVEL'):
                    # 旧版本将只读核对放进重槽；恢复只释放租约，保留历史任务逐字段不变。
                    db.execute('DELETE FROM media_execution_leases WHERE worker_id=?', (worker,))
                    return {'state':job['state'],'job_id':job['job_id'],'job_type':job['job_type']}
                state = 'SUBMIT_RESULT_UNCERTAIN'
                db.execute("UPDATE media_execution_jobs SET state=?,reconciliation_status='REQUIRED' WHERE job_type=? AND job_id=?",
                           (state,job['job_type'],job['job_id']))
                db.execute('DELETE FROM media_execution_leases WHERE worker_id=?', (worker,))
                self.event(db, 'RESTART_RECONCILE_ONLY', job)
                return {'state':state,'job_id':job['job_id'],'job_type':job['job_type']}
            if job['job_type']=='RENDER':
                # 原Render ID交回验证器；不能清空租约后另建Job。验证成片或明确恢复草稿。
                token = secrets.token_hex(32)
                db.execute("UPDATE media_execution_leases SET lease_token=?,heartbeat_at=?,expires_at=?,stage='RENDER_PREPARING' WHERE worker_id=?",
                           (token,self.clock(),self.clock()+self.policy.lease_seconds,worker))
                db.execute("UPDATE media_execution_jobs SET state='RENDER_PREPARING' WHERE job_type='RENDER' AND job_id=?", (job['job_id'],))
                self.event(db, 'RESTART_SAME_RENDER_VERIFY_FIRST', job,{'previous_lease_sha256':hashlib.sha256(lease['lease_token'].encode()).hexdigest()})
                return dict(job, state='RENDER_PREPARING',lease_token=token,payload=json.loads(job['payload_json']),recover_render=True)
            db.execute("UPDATE media_execution_jobs SET state='READY_TO_PUBLISH' WHERE job_type='PUBLISH' AND job_id=?", (job['job_id'],))
            db.execute('DELETE FROM media_execution_leases WHERE worker_id=?', (worker,))
            self.event(db, 'RESTART_PRE_INTENT_RECLAIMABLE', job)
            return {'state':'READY_TO_PUBLISH','job_id':job['job_id'],'job_type':'PUBLISH'}

    def archive_result(self, content_id, *, receipt=None, error=None):
        with self.connect(write=True) as db:
            output = db.execute('SELECT * FROM media_execution_outputs WHERE content_id=?', (content_id,)).fetchone()
            if not output:
                raise ValueError('UNKNOWN_RENDER_OUTPUT')
            if receipt and receipt.get('sha256') != output['output_sha256']:
                raise ValueError('ARCHIVE_HASH_MISMATCH')
            if output['archive_state']=='ARCHIVED':
                return
            db.execute('UPDATE media_execution_outputs SET archive_state=?,archive_receipt=?,archive_error=? WHERE content_id=?',
                       ('ARCHIVED' if receipt else 'ARCHIVE_FAILED', encoded(receipt), error,content_id))

    def cleanup_eligible(self, content_id):
        with self.connect() as db:
            row = db.execute("SELECT 1 FROM media_execution_outputs o JOIN media_execution_jobs p USING(content_id) "
                             "WHERE content_id=? AND o.archive_state='ARCHIVED' AND p.job_type='PUBLISH' "
                             "AND p.state='PUBLISHED' AND p.provider_video_id IS NOT NULL", (content_id,)).fetchone()
            return bool(row)

    def snapshot(self, worker):
        with self.connect() as db:
            lease = db.execute('SELECT * FROM media_execution_leases WHERE worker_id=?', (worker,)).fetchone()
            rows = [dict(r) for r in db.execute('SELECT job_type,state,count(*) AS count FROM media_execution_jobs WHERE worker_id=? GROUP BY job_type,state', (worker,))]
            next_jobs = self._candidates(db,worker)
            return {'worker_id':worker,'execution_slot':1,'active':({k:lease[k] for k in ('worker_id','job_type','job_id','stage','heartbeat_at','expires_at')} if lease else None),
                    'queues':rows,'next_candidate':({k:next_jobs[0][k] for k in ('job_type','job_id','business_account_id','scheduled_at')} if next_jobs else None),
                    'accounts':[dict(r) for r in db.execute('SELECT * FROM media_account_publish_gates')]}


def validate_output(output):
    media = output.get('media',{})
    if not output.get('local_output_path') or media.get('full_decode_verified') is not True:
        raise ValueError('FULL_DECODE_VERIFICATION_REQUIRED')
    if not re.fullmatch('[a-f0-9]{64}', str(media.get('sha256',''))) or media.get('codec') != 'h264':
        raise ValueError('OUTPUT_HASH_OR_CODEC_INVALID')
    for key in ('width','height','size','duration'):
        value = media.get(key)
        if not isinstance(value,(int,float)) or not math.isfinite(value) or value <= 0:
            raise ValueError('OUTPUT_MEDIA_INVALID')
    try:
        numerator, denominator = str(media['fps']).split('/')
        fps = float(numerator)/float(denominator)
        if not math.isfinite(fps) or fps<=0:
            raise ValueError('INVALID_FPS')
    except (ValueError,KeyError,ZeroDivisionError):
        raise ValueError('OUTPUT_FPS_INVALID') from None
