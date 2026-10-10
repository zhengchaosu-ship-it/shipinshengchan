"""Server生产桥：原Render/Publish身份、Provider闩锁与执行租约同事务回写。"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from .control import ControlPlane, Policy, encoded
from .integration import enabled, output_for


class ProductionControlPlane(ControlPlane):
    def __init__(self, config, broker, *, clock=time.time):
        self.config,self.broker=config,broker
        super().__init__(config['operations_db'],policy=Policy(ready_backlog_limit_per_account=config.get('ready_backlog_limit_per_account',15)),clock=clock,authorize=self.authorized)

    @contextmanager
    def connect(self, *, write=False):
        with super().connect(write=write) as db:
            db.execute('ATTACH DATABASE ? AS render_queue',(str(self.broker.db_path),))
            yield db

    def migrate(self):
        super().migrate()
        with self.connect(write=True) as db:
            statement=''
            for line in (Path(__file__).parent/'migrations/002_production.sql').read_text('utf-8').splitlines(True):
                statement+=line
                if sqlite3.complete_statement(statement):
                    db.execute(statement);statement=''
            defaults={'enabled':'true','cutover_at':str(self.clock()),'publisher_execution_node':self.config['worker_ids'][0],
                'server_provider_upload':'LEGACY_AVAILABLE','release_stage':'WIRED_AWAITING_WORKER',
                'ready_backlog_limit_per_account':str(self.policy.ready_backlog_limit_per_account)}
            for key,value in defaults.items():
                db.execute('INSERT OR IGNORE INTO media_execution_settings VALUES(?,?)',(key,value))

    def authorized(self, db, job):
        from production_autopilot.restore_guard import assert_dispatch_allowed
        from startup_pipeline.account_binding import require_account
        try:
            from production_autopilot.account_runtime import allowed
            if not allowed(db,job['business_account_id']): return False
            assert_dispatch_allowed(db)
            require_account(db,job['content_id'],job['business_account_id'])
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='autopilot_allocations'").fetchone():
                # 新的手工确认计划可使用旧托管未提交的成片；按当前PublishJob校验授权。
                # Render仍按内容归属校验，原托管Publish仍受原授权暂停约束。
                scope='a.content_id' if job['job_type']=='RENDER' else 'a.job_id'
                identity=job['content_id'] if job['job_type']=='RENDER' else job['job_id']
                allocation=db.execute('SELECT a.*,u.enabled,u.config_hash,u.status AS auth_status FROM autopilot_allocations a '
                    'JOIN autopilot_authorizations u USING(account_id) WHERE '+scope+'=?',(identity,)).fetchone()
                if allocation and (not allocation['enabled'] or allocation['authorization_hash']!=allocation['config_hash']):
                    return False
            if job['job_type']=='RENDER':
                row=db.execute('SELECT status FROM render_queue.jobs WHERE job_id=?',(job['job_id'],)).fetchone()
                return bool(row and row[0] in ('QUEUED','CLAIMED'))
            row=db.execute('SELECT p.*,j.scheduled_at,j.status AS job_status,plan.status AS plan_status '
                'FROM provider_publish_jobs p JOIN publish_jobs j USING(job_id) JOIN publish_plans plan ON plan.plan_id=p.plan_id WHERE p.job_id=?',(job['job_id'],)).fetchone()
            if not row or row['submit_attempt_count'] or row['intent_json'] or row['job_status']=='CANCELLED' or row['plan_status']!='CONFIRMED':
                return False
            from yixiaoer_adapter.storage import cached_binding
            binding=cached_binding(db,job['business_account_id'],required=True)
            return binding['provider_account_id']==row['provider_account_id'] and datetime.fromisoformat(row['scheduled_at']).timestamp()==job['scheduled_at']
        except (PermissionError,ValueError,KeyError):
            return False

    def tick(self):
        """常驻LAN服务每轮调用；不执行Provider写命令。"""
        self.refresh_accounts()
        with self.connect(write=True) as db:
            from production_autopilot.account_runtime import reconcile_accounts
            reconcile_accounts(db,self.clock())
            # Broker中的未开工任务同时取消，防止之后重新登记已取消的业务任务。
            db.execute("UPDATE render_queue.jobs SET status='CANCELLED',error='CANCELLED_BY_ACCOUNT_PAUSE' WHERE status='QUEUED' AND job_id IN (SELECT render_job_id FROM autopilot_allocations WHERE state='CANCELLED_BY_ACCOUNT_PAUSE')")
        with self.connect() as db:
            cutoff=float(db.execute("SELECT value FROM media_execution_settings WHERE key='cutover_at'").fetchone()[0])
            rows=[dict(r) for r in db.execute("SELECT * FROM render_queue.jobs WHERE status='QUEUED' AND job_id NOT IN (SELECT job_id FROM media_execution_jobs WHERE job_type='RENDER')")]
        for row in rows:
            manifest=json.loads(row['payload'])
            created=manifest.get('pending_at') or manifest.get('created_at')
            if not created or datetime.fromisoformat(created).timestamp()<cutoff:
                continue
            manifest['output_layout']='LAN_RESIDENT_V1'
            for entry in manifest.get('files',[]):
                source=Path(entry['source']).resolve();assets=Path(self.config['startup_assets_root']).resolve()
                entry['source_unc_path']=str(Path(self.config['startup_assets_unc'])/source.relative_to(assets)) if entry['relative'].startswith('assets/') and source.is_relative_to(assets) else str(Path(self.config['task_files_unc'])/row['job_id']/entry['relative'])
                entry['asset_id']=hashlib.sha256(entry['source'].encode()).hexdigest()[:20]
            self.enroll('RENDER',row['job_id'],self.config['worker_ids'][0],manifest['target_account_id'],manifest['content_id'],
                        {'render_manifest':manifest,'composition_id':manifest['composition_signature'],
                         'width':manifest['canvas']['width'],'height':manifest['canvas']['height'],'fps':manifest['fps'],
                         'duration':float(manifest['duration_us'])/1000000,'codec':'h264'})
        self.refresh_accounts()
        with self.connect(write=True) as db:
            expired=db.execute('SELECT * FROM media_execution_leases WHERE expires_at<=?',(self.clock(),)).fetchall()
            for lease in expired:
                if lease['stage']!='LEASE_EXPIRED_NEEDS_RECOVERY':
                    db.execute("UPDATE media_execution_leases SET stage='LEASE_EXPIRED_NEEDS_RECOVERY' WHERE worker_id=?",(lease['worker_id'],))
            # 预先计算队列等待原因供8502读取；Worker领取时仍重新验证。
            for worker in self.config['worker_ids']:
                self._candidates(db,worker,update=True)

    def refresh_accounts(self):
        from .coordinator import classify_failure
        with self.connect(write=True) as db:
            accounts=db.execute("SELECT * FROM provider_account_bindings WHERE provider='yixiaoer'").fetchall()
            for account in accounts:
                key=account['business_account_id']
                old=db.execute('SELECT * FROM media_account_publish_gates WHERE business_account_id=?',(key,)).fetchone()
                auth=db.execute('SELECT * FROM autopilot_authorizations WHERE account_id=?',(key,)).fetchone() if db.execute("SELECT 1 FROM sqlite_master WHERE name='autopilot_authorizations'").fetchone() else None
                state=account['provider_account_status'] if account['provider_account_status'] in ('ONLINE','OFFLINE') else 'UNKNOWN'
                if old:
                    if old['gate']=='CONDITIONAL_OPEN' and state=='OFFLINE':
                        self._account(db,key,'BLOCKED_RISK',state,'ACCOUNT_AUTH_EXPIRED',None)
                        continue
                    if old['gate']=='OPEN' and auth and not auth['enabled'] and auth['status']=='ATTENTION_REQUIRED':
                        # 用户在原异常之后完成账号恢复，不等于重新开启长期托管。
                        # 旧attention不能每轮覆盖已核验的发布门；新的attention仍可阻止。
                        recovered=False
                        if db.execute("SELECT 1 FROM sqlite_master WHERE name='production_recovery_requests'").fetchone():
                            proof=db.execute("SELECT finished_at,result_json FROM production_recovery_requests WHERE account_id=? AND state='CHECKED' ORDER BY finished_at DESC LIMIT 1",(key,)).fetchone()
                            if proof:
                                result=json.loads(proof['result_json'] or '{}')
                                recovered=(result.get('gate_recovered') is True and not result.get('errors')
                                    and datetime.fromisoformat(proof['finished_at'])>datetime.fromisoformat(auth['updated_at']))
                        if not recovered:
                            self._account(db,key,'BLOCKED_MANUAL_ACTION',state,auth['attention_reason'],None)
                    db.execute('UPDATE media_account_publish_gates SET provider_account_status=?,checked_at=? WHERE business_account_id=?',(state,self.clock(),key))
                    continue  # ONLINE不是解除官方人工验证的证据。
                reason=auth['attention_reason'] if auth else None
                failure=classify_failure(RuntimeError(reason or ''))
                gate=failure.gate if failure.domain=='ACCOUNT_LEVEL' else 'BLOCKED_AUTH' if state!='ONLINE' else 'OPEN'
                if auth and auth['status'] in ('PAUSED','FINISHED'):
                    gate='PAUSED_BY_USER'
                elif auth and not auth['enabled'] and gate=='OPEN':
                    gate='BLOCKED_MANUAL_ACTION'
                self._account(db,key,gate,state,reason,None)

    def claim(self, worker):
        # 直接采集水位，不依赖Codex或巡检文件；不干预已领取任务与只读核对。
        from server_maintenance.storage import heavy_dispatch_allowed
        if not heavy_dispatch_allowed(self.path):
            return None
        with self.connect() as db:
            health=db.execute('SELECT * FROM media_execution_worker_health WHERE worker_id=?',(worker,)).fetchone()
            if not health or self.clock()-health['received_at']>90:
                return None
            details=json.loads(health['details_json'])
            if details.get('protocol')!='MEDIA_EXECUTION_V1' or details.get('status') not in ('READY','IDLE'):
                return None
        return super().claim(worker)

    def event(self, db, event, job=None, evidence=None):
        super().event(db,event,job,evidence)
        if job and event in ('RENDER_READY_ARCHIVE_PENDING','PROVIDER_RESULT_OBSERVED','READ_ONLY_RECONCILIATION_OBSERVED'):
            table='media_reconciliation_leases' if event=='READ_ONLY_RECONCILIATION_OBSERVED' else 'media_execution_leases'
            lease=db.execute('SELECT * FROM '+table+' WHERE job_type=? AND job_id=?',(job['job_type'],job['job_id'])).fetchone()
            if lease:
                kind={'RENDER_READY_ARCHIVE_PENDING':'render-complete','PROVIDER_RESULT_OBSERVED':'publish-complete','READ_ONLY_RECONCILIATION_OBSERVED':'reconciliation-result'}[event]
                db.execute('INSERT INTO media_execution_receipts VALUES(?,?,?,?,?)',(lease['worker_id'],lease['lease_token'],kind,hashlib.sha256(encoded(evidence).encode()).hexdigest(),'{"saved":true}'))
        if not job or event=='SERVER_JOB_ENROLLED':
            return
        if event not in ('EXECUTION_LEASE_ACQUIRED','RENDER_READY_ARCHIVE_PENDING','EXECUTION_FAILED',
                         'SUBMIT_INTENT','PROVIDER_RESULT_OBSERVED','READ_ONLY_RECONCILIATION_OBSERVED',
                         'RESTART_RECONCILE_ONLY','RESTART_PRE_INTENT_RECLAIMABLE','PROVIDER_VALIDATED'):
            return
        current=db.execute('SELECT * FROM media_execution_jobs WHERE job_type=? AND job_id=?',(job['job_type'],job['job_id'])).fetchone()
        if not current:
            return
        now=datetime.now(timezone.utc).isoformat()
        if current['job_type']=='RENDER':
            if event=='EXECUTION_LEASE_ACQUIRED':
                lease=db.execute('SELECT lease_token FROM media_execution_leases WHERE worker_id=?',(current['worker_id'],)).fetchone()
                db.execute("UPDATE render_queue.jobs SET status='CLAIMED',claim=? WHERE job_id=? AND status='QUEUED'",(lease[0],current['job_id']))
            elif event=='RENDER_READY_ARCHIVE_PENDING':
                output=output_for(db,current['content_id']);media=output['media']
                from startup_pipeline.account_binding import require_account
                require_account(db,current['content_id'],current['business_account_id'])
                content=db.execute('SELECT * FROM startup_contents WHERE content_id=?',(current['content_id'],)).fetchone()
                if not content or content['publish_status']!='NOT_SCHEDULED':
                    raise PermissionError('RENDER_CONTENT_CHANGED')
                db.execute("UPDATE startup_contents SET production_status='READY',video_path=?,duration_seconds=?,size_bytes=?,mtime_ns=?,media_json=?,error=NULL WHERE content_id=?",
                    (output['local_output_path'],media['duration'],media['size'],media['mtime_ns'],encoded(media),current['content_id']))
                db.execute("UPDATE render_queue.jobs SET status='COMPLETED',receipt=?,error=NULL WHERE job_id=?",(encoded(evidence),current['job_id']))
                manifest=json.loads(current['payload_json'])['render_manifest']
                from startup_render.common import output_relative
                destination=str(Path(self.config['render_output_unc'])/output_relative(manifest))
                db.execute('INSERT OR IGNORE INTO media_execution_archive_jobs VALUES(?,?,?,\'ARCHIVE_PENDING\',?)',(current['content_id'],current['worker_id'],destination,self.clock()))
            elif event=='EXECUTION_FAILED':
                db.execute("UPDATE render_queue.jobs SET status='NEEDS_MANUAL',error=? WHERE job_id=?",(current['error_json'],current['job_id']))
            return
        provider=db.execute('SELECT * FROM provider_publish_jobs WHERE job_id=?',(current['job_id'],)).fetchone()
        if not provider:
            raise PermissionError('FORMAL_PROVIDER_JOB_REQUIRED')
        if event=='EXECUTION_LEASE_ACQUIRED':
            lease=db.execute('SELECT lease_token FROM media_execution_leases WHERE worker_id=?',(current['worker_id'],)).fetchone()
            if provider['submit_attempt_count'] or provider['intent_json']:
                raise PermissionError('LEGACY_SUBMIT_LATCH_CONSUMED')
            db.execute("UPDATE provider_publish_jobs SET worker_id=?,claim_token=?,state='UPLOADING',updated_at=? WHERE job_id=?",(current['worker_id'],lease[0],now,current['job_id']))
        elif event=='SUBMIT_INTENT':
            if provider['submit_attempt_count'] or provider['intent_json']:
                raise PermissionError('LEGACY_SUBMIT_LATCH_CONSUMED')
            db.execute("UPDATE provider_publish_jobs SET submit_attempt_count=1,intent_json=?,state='SUBMIT_INTENT',payload_sha256=?,request_hash=?,provider_submitted_at=?,updated_at=? WHERE job_id=?",
                (current['intent_json'],evidence['payload_sha256'],evidence['request_hash'],now,now,current['job_id']))
        elif event in ('PROVIDER_RESULT_OBSERVED','READ_ONLY_RECONCILIATION_OBSERVED'):
            state='FAILED' if current['state']=='FAILED_JOB_LEVEL' else current['state']
            db.execute('UPDATE provider_publish_jobs SET state=?,provider_task_set_id=COALESCE(?,provider_task_set_id),provider_task_id=COALESCE(?,provider_task_id),provider_video_id=COALESCE(?,provider_video_id),provider_raw_status=?,provider_last_checked_at=?,updated_at=? WHERE job_id=?',
                (state,evidence.get('provider_task_set_id'),current['provider_task_id'],current['provider_video_id'],encoded(evidence.get('provider_response',{})),now,now,current['job_id']))
        elif event in ('EXECUTION_FAILED','RESTART_RECONCILE_ONLY'):
            state='SUBMIT_RESULT_UNCERTAIN' if current['submit_attempt_count'] else 'FAILED' if current['state']=='FAILED_JOB_LEVEL' else 'ATTENTION_REQUIRED'
            db.execute('UPDATE provider_publish_jobs SET state=?,last_error=?,updated_at=? WHERE job_id=?',(state,current['error_json'],now,current['job_id']))
        elif event=='RESTART_PRE_INTENT_RECLAIMABLE':
            db.execute("UPDATE provider_publish_jobs SET worker_id=NULL,claim_token=NULL,state='READY_TO_DISPATCH' WHERE job_id=? AND submit_attempt_count=0",(current['job_id'],))
        elif event=='PROVIDER_VALIDATED':
            db.execute("UPDATE provider_publish_jobs SET state='PROVIDER_VALIDATED' WHERE job_id=?",(current['job_id'],))
        observed=db.execute('SELECT state FROM provider_publish_jobs WHERE job_id=?',(current['job_id'],)).fetchone()[0]
        db.execute('UPDATE publish_jobs SET status=?,current_step=?,updated_at=? WHERE job_id=?',(observed,'MEDIA_'+current['state'],now,current['job_id']))
        from yixiaoer_adapter.storage import audit
        audit(db,'MEDIA_'+event,job_id=current['job_id'],state=observed,evidence=evidence)

    def report_worker(self, worker, details):
        if worker not in self.config['worker_ids'] or details.get('protocol')!='MEDIA_EXECUTION_V1':
            raise PermissionError('MEDIA_WORKER_IDENTITY_REQUIRED')
        with self.connect(write=True) as db:
            db.execute('INSERT INTO media_execution_worker_health VALUES(?,?,?) ON CONFLICT(worker_id) DO UPDATE SET received_at=excluded.received_at,details_json=excluded.details_json',(worker,self.clock(),encoded(details)))
            network=details.get('network',{}).get('state','PUBLISH_NETWORK_ATTENTION')
            ready=details.get('yixiaoer_local_ready') is True
            self._infrastructure(db,worker,'ONLINE' if ready and network=='ONLINE' else 'PUBLISH_NETWORK_ATTENTION' if network!='ONLINE' else 'DEGRADED','WORKER_HEALTH_OBSERVATION')
        return {'saved':True}

    def prior_receipt(self, worker, token, kind, value):
        with self.connect() as db:
            row=db.execute('SELECT * FROM media_execution_receipts WHERE worker_id=? AND lease_token=? AND kind=?',(worker,token,kind)).fetchone()
            if not row:
                return None
            if row['digest']!=hashlib.sha256(encoded(value).encode()).hexdigest():
                raise PermissionError('COMPLETION_RECEIPT_IMMUTABLE')
            return json.loads(row['response_json'])

    def archive_pending(self, worker):
        with self.connect() as db:
            if self.pending_provider_execution(db,worker):return []
            return [dict(r) for r in db.execute("SELECT a.*,o.local_output_path,o.output_sha256 FROM media_execution_archive_jobs a JOIN media_execution_outputs o USING(content_id) WHERE a.worker_id=? AND a.state!='ARCHIVED' ORDER BY updated_at LIMIT 1",(worker,))]

    def archive_report(self, worker, content_id, receipt=None, error=None):
        with self.connect() as db:
            row=db.execute('SELECT worker_id FROM media_execution_outputs WHERE content_id=?',(content_id,)).fetchone()
            if not row or row[0]!=worker:
                raise PermissionError('ARCHIVE_OWNER_MISMATCH')
        self.archive_result(content_id,receipt=receipt,error=error)
        with self.connect(write=True) as db:
            db.execute('UPDATE media_execution_archive_jobs SET state=?,updated_at=? WHERE content_id=?',('ARCHIVED' if receipt else 'ARCHIVE_FAILED',self.clock(),content_id))
        return {'saved':True}
