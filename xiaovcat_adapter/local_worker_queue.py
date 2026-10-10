"""本机可信Windows用户消费既有正式队列；不创建Plan/Job/验收scope。"""
from datetime import datetime, timezone
import json
from pathlib import Path
from startup_pipeline.production_dispatch import ProductionDispatcher, ProductionScope, RESERVE_STEP
from xiaovcat_adapter.models import utc_now_iso


class LocalWorkerQueue:
    def __init__(self, dispatcher, config, authority):
        self.dispatcher, self.store = dispatcher, dispatcher.store
        self.config, self.authority = config, authority

    def allowed(self, row):
        return (row['plan_id'] in self.config['allowed_plan_ids']
                and row['job_id'] in self.config['allowed_job_ids'])

    def discover(self):
        # 缺库不能生成空库；启动/部署不做隐式迁移。
        if not self.store.path.is_file():
            raise RuntimeError('OPERATIONS_DB_NOT_FOUND')
        with self.store.connect() as db:
            rows = db.execute("SELECT d.*,p.status AS plan_status FROM startup_production_dispatch d "
                              "JOIN publish_plans p USING(plan_id) JOIN publish_jobs j USING(job_id) "
                              "WHERE p.status='CONFIRMED' ORDER BY j.scheduled_at,d.job_id").fetchall()
        return [dict(r) for r in rows if self.allowed(r) and r['state'] in
                {'QUEUED', 'CLAIMED', 'SUBMIT_RESULT_UNCERTAIN'}]

    def context_preview(self, row):
        """只构造当前正式Job字段；不等于账号在线预检或UI回读。"""
        if not self.allowed(row):
            raise PermissionError('LOCAL_WORKER_SCOPE_DENIED')
        with self.store.connect() as db:
            r = db.execute('SELECT j.*,m.account_id,m.topics_json,m.business_type,m.employee_id '
                           'FROM publish_jobs j JOIN startup_job_metadata m USING(job_id) WHERE j.job_id=?',
                           (row['job_id'],)).fetchone()
            from startup_pipeline.account_binding import guard_publish_job
            guard_publish_job(db, row['job_id'])
        if not r:
            raise RuntimeError('FORMAL_JOB_METADATA_REQUIRED')
        return dict(job_id=r['job_id'],content_id=r['content_id'],plan_id=row['plan_id'],
                    account_id=r['account_id'],account_name=r['account_name'],platform=r['platform'],
                    video_path=r['video_path'],scheduled_at=r['scheduled_at'],title=r['title'],
                    description=r['description'],topics=json.loads(r['topics_json']),business_type=r['business_type'])

    def claim(self, row):
        # 本机启动配置=OS用户授权范围，不伪造员工登录、不签发token。
        # 即使配置允许，原_context仍校验CONFIRMED、有效员工/组、在线快照、绑定、媒体、排期。
        self.authority()
        if (self.config['dry_run_mode'] or not self.config['real_submit_armed']) and not self.config.get('production_execution_authorized'):
            raise PermissionError('ARMED_REQUIRED')
        if not self.allowed(row):
            raise PermissionError('LOCAL_WORKER_SCOPE_DENIED')
        with self.store.connect(write=True) as db:
            return self.dispatcher._claim_in_transaction(db,row['plan_id'],row['job_id'],self.config['worker_id'])

    def scope(self, row, nonce, results):
        scope = ProductionScope(self.dispatcher,row['job_id'],nonce,results)
        scope.capture_screenshots = False
        scope.uia_only = True
        return scope

    def submission(self, job_id):
        with self.store.connect() as db:
            events = db.execute('SELECT started_at FROM state_events WHERE job_id=? AND step=? ORDER BY id',
                                (job_id,RESERVE_STEP)).fetchall()
            returned = db.execute("SELECT started_at FROM state_events WHERE job_id=? AND step='LOCAL_SUBMIT_RETURNED' ORDER BY id DESC LIMIT 1",(job_id,)).fetchone()
        return dict(submit_attempt_count=len(events),submit_started_at=events[0][0] if events else None,
                    submit_returned_at=returned[0] if returned else None)

    def row(self, job_id):
        with self.store.connect() as db:
            return dict(db.execute('SELECT * FROM startup_production_dispatch WHERE job_id=?',(job_id,)).fetchone())

    def stage(self, job_id, state):
        with self.store.connect(write=True) as db:
            db.execute('INSERT INTO state_events(job_id,step,attempt,outcome,started_at,duration_ms) VALUES(?,?,?,?,?,0)',
                       (job_id,'LOCAL_PUBLISH_STAGE',1,state,utc_now_iso()))

    def refresh_snapshot(self, row, results):
        """复用单组读取与严格稳定ID持久化，仅该Job所属授权组。"""
        self.authority()
        if not self.allowed(row) or ((self.config['dry_run_mode'] or not self.config['real_submit_armed']) and not self.config.get('production_execution_authorized')):
            raise PermissionError('ARMED_REQUIRED')
        from startup_pipeline.selector_refresh import read_group, _SnapshotWriter
        from xiaovcat_adapter.group_sync import persist_group_snapshot
        queue = self
        with self.store.connect() as db:
            meta = db.execute('SELECT * FROM startup_job_metadata WHERE job_id=?',(row['job_id'],)).fetchone()
            item = db.execute('SELECT group_id FROM publish_plan_items WHERE job_id=?',(row['job_id'],)).fetchone()
            employee_id, group_id = meta['employee_id'],item['group_id']
        class BoundStore:
            # 只为既有快照服务提供固定Job员工上下文，非公开登录/鉴权接口。
            def connect(self, **kwargs):return queue.store.connect(**kwargs)
            def _principal(self, db, token):
                queue.authority()
                actor=db.execute('SELECT * FROM employees WHERE employee_id=? AND enabled=1',(employee_id,)).fetchone()
                if not actor or token is not self:
                    raise PermissionError('LOCAL_WORKER_SCOPE_DENIED')
                return actor
        bound=BoundStore()
        with self.store.connect() as db:
            bound._principal(db,bound)
            if not db.execute("SELECT 1 FROM employee_group_bindings WHERE employee_id=? AND group_id=? AND group_role='STARTUP' AND enabled=1",(employee_id,group_id)).fetchone():
                raise PermissionError('ACCOUNT_PERMISSION_DENIED')
            ids={r[0] for r in db.execute('SELECT account_id FROM xiaovcat_accounts WHERE group_id=? AND is_active=1',(group_id,))}
        snapshot=read_group(group_id,ids,results,capture_screenshots=False)
        writer=_SnapshotWriter(bound,bound,group_id,ids)
        return persist_group_snapshot(writer,bound,snapshot,group_id,ids)

    def returned(self, job_id, submitted):
        if submitted.get('invoke_returned') is True:
            with self.store.connect(write=True) as db:
                if not db.execute("SELECT 1 FROM state_events WHERE job_id=? AND step='LOCAL_SUBMIT_RETURNED'",(job_id,)).fetchone():
                    db.execute('INSERT INTO state_events(job_id,step,attempt,outcome,started_at,duration_ms) VALUES(?,?,?,?,?,0)',
                               (job_id,'LOCAL_SUBMIT_RETURNED',1,'INVOKE_RETURNED',submitted.get('submit_returned_at') or utc_now_iso()))

    def success(self, row, proof):
        self.authority()
        if not self.allowed(row):raise PermissionError('LOCAL_WORKER_SCOPE_DENIED')
        return self.dispatcher.record_scheduled_success(row['job_id'],row['claim_token'],proof,allow_reconciliation=True)
