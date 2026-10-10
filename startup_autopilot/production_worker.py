"""正式常驻托管Worker：持久规划→既有Render→既有LOCAL Adapter；授权空则完全空闲。"""
import argparse
from dataclasses import asdict
from datetime import datetime, time as daytime, timezone, timedelta
import json
from pathlib import Path
import time
import urllib.request

from publish_planner.models import Plan
from startup_pipeline.service import StartupPipeline
from startup_pipeline.registration import StartupContentRegistration
from startup_render.queue import RenderQueue
from yixiaoer_adapter.cli_runner import run_hidden
from yixiaoer_adapter.publisher import YixiaoerPublisherAdapter
from yixiaoer_adapter.storage import ProviderStore, check_slots, enroll_confirmed, file_sha
from yixiaoer_adapter.worker import single_instance, write_json
from .models import SHANGHAI, aware
from .production import ProductionStore, AutopilotPlannerStore, ServiceGrant, utcnow

ROOT=Path(__file__).resolve().parents[1]


class ScopedProviderStore(ProviderStore):
    def __init__(self,planner,production=None):
        super().__init__(planner);self.production=production

    def claim_principal(self,db,owner,row):
        if self.production:
            allocation=db.execute('SELECT account_id,authorization_hash FROM autopilot_allocations WHERE job_id=?',(row['job_id'],)).fetchone()
            if allocation:return self.production.verify(db,ServiceGrant(allocation['account_id'],allocation['authorization_hash']))[0]
        return super().claim_principal(db,owner,row)

    def refresh_bindings(self,accounts):
        by_id={a['id']:a for a in accounts}
        with self.planner.connect(write=True) as db:
            for auth in db.execute('SELECT account_id,provider_account_id FROM autopilot_authorizations'):
                account=by_id.get(auth['provider_account_id'])
                db.execute('UPDATE provider_account_bindings SET provider_account_status=?,provider_last_verified_at=?,raw_account_json=? WHERE business_account_id=? AND provider_account_id=?',
                    ('ONLINE' if account and account.get('status')==1 else 'OFFLINE',utcnow().isoformat(),json.dumps(account or {},ensure_ascii=False),auth['account_id'],auth['provider_account_id']))


class AuthorizedAdapter(YixiaoerPublisherAdapter):
    def __init__(self,config,store,production):
        super().__init__(config,store);self.production=production

    def call(self,args,**kwargs):
        # 外部写操作前重新检查暂停/结束与不可变授权。只读对账不受暂停影响。
        if args and args[0] in ('upload','publish') and '--dry-run' not in args:
            job_id=kwargs.get('job_id')
            with self.production.planner.connect() as db:
                allocation=db.execute('SELECT account_id,authorization_hash FROM autopilot_allocations WHERE job_id=?',(job_id,)).fetchone()
                if not allocation:raise PermissionError('AUTOPILOT_JOB_SCOPE_REQUIRED')
                self.production.verify(db,ServiceGrant(allocation['account_id'],allocation['authorization_hash']))
        return super().call(args,**kwargs)


class ProductionWorker:
    def __init__(self,config,production=None,*,generator=None,registration=None,adapter=None,render_health=None,probe=None):
        self.config=config;self.production=production or ProductionStore()
        self.service_store=AutopilotPlannerStore(self.production)
        self.pipeline=StartupPipeline(self.service_store,probe=probe)
        render=json.loads(Path(config['render_config']).read_text('utf-8')) if config.get('render_config') else {}
        self.registration=registration or StartupContentRegistration(self.pipeline,RenderQueue(Path(render['state_root'])/'render_jobs.db'))
        self.provider_store=ScopedProviderStore(self.production.planner,self.production)
        self.adapter=adapter or AuthorizedAdapter(config,self.provider_store,self.production)
        self.generator=generator
        self.render_health=render_health or self._render_online
        from production_autopilot.reliability import ReliabilityStore
        self.reliability=ReliabilityStore(self.production)
        self.reliability.migrate()
        self.account_cursor=0
        self.metrics_queue=None
        if config.get('async_metrics',False):
            from production_autopilot.metrics_queue import MetricsQueue
            self.metrics_queue=MetricsQueue(self.production,self.adapter,self.reliability,config.get('metrics_parallel_accounts',2))

    def _render_online(self):
        from startup_render.lan_protocol import token_from
        c=json.loads(Path(self.config['render_config']).read_text('utf-8'))
        request=urllib.request.Request(f"http://{c['bind']}:{c['port']}/health",headers={'Authorization':'Bearer '+token_from(c)})
        with urllib.request.urlopen(request,timeout=8) as response:data=json.loads(response.read())
        allowed=self.config.get('render_worker_ids',['WORKER-2060S-01'])
        workers=[w for w in data.get('workers',[]) if w.get('worker_id') in allowed]
        self.render_failure_reason=('剪映导出需要处理，请核对原任务和窗口' if any(w.get('status')=='HALTED_NEEDS_MANUAL' for w in workers)
                                    else '渲染工作站离线')
        return any(w.get('status') in ('ONLINE','IDLE','BUSY') for w in workers)

    def update(self,key,state,**values):
        values.update(state=state,updated_at=utcnow().isoformat())
        with self.production.planner.connect(write=True) as db:
            db.execute('UPDATE autopilot_allocations SET '+','.join(k+'=?' for k in values)+' WHERE allocation_id=?',(*values.values(),key))

    def allocations(self,account_id):
        with self.production.planner.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM autopilot_allocations WHERE account_id=? ORDER BY scheduled_at',(account_id,))]

    def generate(self,grant,row, *, recovery_context=None):
        from yixiaoer_adapter.storage import schedule_gate
        schedule_gate(row['scheduled_at'])
        if not self.render_health():raise RuntimeError(getattr(self,'render_failure_reason','渲染工作站离线'))
        if self.generator is None:
            from jianying_auto.memory_safety import require_draft_budget
            require_draft_budget()  # 在预留Generation/Draft及事务之前检查Commit。
        from account_visuals.storage import AccountBackgroundStore
        # 视觉层独立于TemplateVersion/授权hash；缺失必需背景在新任务写入前拒绝。
        proposal = json.loads(row['proposal_json'])
        background = AccountBackgroundStore(self.production.planner.path).snapshot(grant.account_id,
            template_requires_background=bool(proposal.get('requires_background', False)))
        with self.production.planner.connect(write=True) as db:
            self.production.verify(db,grant)
            expected_state = 'FAILED_RETRYABLE' if recovery_context is not None else 'PLANNED'
            current = db.execute('SELECT * FROM autopilot_allocations WHERE allocation_id=?', (row['allocation_id'],)).fetchone()
            if recovery_context is not None:
                if (not current or current['content_id'] or current['render_job_id'] or current['job_id']
                    or current['account_id'] != grant.account_id
                    or current['authorization_hash'] != grant.config_hash
                    or json.loads(current['generation_context_json'] or '{}') != recovery_context
                    or db.execute('SELECT 1 FROM startup_content_registrations WHERE generation_id=?', (recovery_context['generation_id'],)).fetchone()):
                    raise RuntimeError('DRAFT_RECOVERY_IDENTITY_OR_SIDE_EFFECT_CHANGED')
            changed=db.execute("UPDATE autopilot_allocations SET state='GENERATING',updated_at=? WHERE allocation_id=? AND state=?",(utcnow().isoformat(),row['allocation_id'],expected_state)).rowcount
            if not changed:return
        # 已持久化GENERATING后异常退出，禁止再次生成：人工处理而非重复批次。
        context=recovery_context if recovery_context is not None else self.registration.begin(grant,grant.account_id,1)
        with self.production.planner.connect(write=True) as db:
            db.execute('UPDATE autopilot_allocations SET generation_context_json=? WHERE allocation_id=?',(json.dumps(context,ensure_ascii=False),row['allocation_id']))
        path=Path(self.config['runtime_dir'])/'compositions'/(row['allocation_id']+'.json')
        write_json(path,json.loads(row['proposal_json']))
        generator=self.generator
        if generator is None:
            from benchmark.experiments.dino_july_web.jianying_adapter import generate_draft
            generator=generate_draft
        generated=generator('手法',draft_name=context['draft_names'][0],selection_manifest=str(path),
            business_account_id=grant.account_id,background_snapshot=background)
        expected=[str(Path(s['path']).resolve()).casefold() for s in json.loads(row['proposal_json'])['selections']]
        actual=[str(Path(s['path']).resolve()).casefold() for s in generated.get('selected_materials',[])]
        if expected!=actual:raise RuntimeError('实际草稿素材顺序与用户模板不一致')
        with self.production.planner.connect() as db:self.production.verify(db,grant)
        results=self.registration.complete(grant,context,generated)
        if len(results)!=1:raise RuntimeError('AUTOPILOT_SINGLE_CONTENT_REQUIRED')
        item=results[0]
        self.update(row['allocation_id'],'RENDER_PENDING',content_id=item['content_id'],render_job_id=item['render_job_id'],error=None)

    def create_plan(self,grant,row):
        from yixiaoer_adapter.storage import schedule_gate
        schedule_gate(row['scheduled_at'])
        with self.production.planner.connect() as db:
            self.production.verify(db,grant)
            content=dict(db.execute('SELECT * FROM startup_contents WHERE content_id=?',(row['content_id'],)).fetchone())
            # 托管专用发布文字配置，不改变已有业务Profile。
            profile=db.execute('SELECT * FROM startup_publish_profiles WHERE profile_id=?',('AUTOPILOT_DEFAULT',)).fetchone()
        if content['production_status']!='READY':return
        from media_execution.integration import observed_media,output_for
        with self.production.planner.connect() as db:
            observed=observed_media(db,content,self.pipeline.probe)
            remote=output_for(db,content['content_id'])
        if (observed['size_bytes'],observed['mtime_ns'])!=(content['size_bytes'],content['mtime_ns']):raise RuntimeError('READY_MP4_CHANGED')
        scheduled=aware(row['scheduled_at']).astimezone(SHANGHAI)
        plan=Plan('AUTOPILOT-'+row['allocation_id'],scheduled.date(),scheduled.date(),scheduled.time().replace(tzinfo=None),
            (grant.account_id,),(content['video_path'],),daily_count=1,title=profile['title_template'],description=profile['description_template'])
        if remote:
            files=[{'content_id':row['content_id'],'video_path':content['video_path'],'sha256':remote['output_sha256'],
                    'cover_path':remote['media']['cover_path'],'cover_sha256':remote['media']['cover_sha256']}]
        else:
            cover=Path(self.config['runtime_dir'])/'covers'/(row['allocation_id']+'.jpg');cover.parent.mkdir(parents=True,exist_ok=True)
            run_hidden([self.config['ffmpeg'],'-hide_banner','-loglevel','error','-y','-i',content['video_path'],'-frames:v','1','-q:v','2',str(cover)],check=True,timeout=45)
            if not cover.is_file() or cover.stat().st_size==0:raise RuntimeError('封面生成失败')
            files=[{'content_id':row['content_id'],'video_path':content['video_path'],'sha256':file_sha(content['video_path']),
                    'cover_path':str(cover.resolve()),'cover_sha256':file_sha(cover)}]
        with self.production.planner.connect(write=True) as db:
            principal,auth,*_=self.production.verify(db,grant)
            allocation=db.execute('SELECT * FROM autopilot_allocations WHERE allocation_id=?',(row['allocation_id'],)).fetchone()
            if allocation['plan_id']:return
            # 同一持久额度预留只能生成一个既有PublishPlan/PublishJob。
            slots,rows,publish_profile=self.pipeline._slots(db,grant,plan,[row['content_id']],'AUTOPILOT_DEFAULT')
            check_slots(db,slots)
            accounts=self.service_store._require_publish_accounts(db,principal,plan.account_ids,'STARTUP')
            prep={'files':files,'long_term_authorization_hash':auth['config_hash'],'allocation_id':row['allocation_id']}
            db.execute('INSERT INTO provider_production_previews VALUES(?,?,?,?,?,?,?)',(plan.plan_id,principal['employee_id'],json.dumps([row['content_id']]),plan.payload(),'AUTOPILOT_DEFAULT',json.dumps(prep),utcnow().isoformat()))
            self.pipeline._write_simulation(db,principal,plan,slots,rows,publish_profile,'AUTOPILOT_DEFAULT',accounts)
            db.execute("UPDATE publish_plans SET status='CONFIRMED' WHERE plan_id=?",(plan.plan_id,))
            db.execute('UPDATE publish_plan_items SET test_only=0 WHERE plan_id=?',(plan.plan_id,))
            db.execute("UPDATE startup_job_metadata SET dispatch_mode='CONFIRMED_NOT_DISPATCHED' WHERE source_plan_id=?",(plan.plan_id,))
            enroll_confirmed(db,plan.plan_id)
            job_id=db.execute('SELECT job_id FROM publish_plan_items WHERE plan_id=?',(plan.plan_id,)).fetchone()[0]
            db.execute("UPDATE autopilot_allocations SET plan_id=?,job_id=?,state='READY_TO_DISPATCH',updated_at=? WHERE allocation_id=?",
                       (plan.plan_id,job_id,utcnow().isoformat(),row['allocation_id']))
            self.production.event(db,grant.account_id,'AUTOPILOT_WORKER','LONG_TERM_AUTHORIZED_PLAN_CREATED',{'plan_id':plan.plan_id,'job_id':job_id,'authorization_hash':grant.config_hash,'scheduled_at':row['scheduled_at']})

    def reconcile(self,row):
        if not row['job_id']:return
        provider=self.provider_store.row(row['job_id'])
        if provider['submit_attempt_count']>=1:
            if provider['state']=='SUBMIT_INTENT':
                self.provider_store.transition(row['job_id'],'SUBMIT_RESULT_UNCERTAIN',{'reason':'RESTART_AFTER_INTENT_NO_REPOST'})
            if provider['state'] not in ('PUBLISHED','FAILED','CANCELLED'):
                self.adapter.reconcile_publish_result(row['job_id'])
            provider=self.provider_store.row(row['job_id'])
            self.update(row['allocation_id'],provider['state'])
        if provider['state'] in ('FAILED','SUBMIT_RESULT_UNCERTAIN'):
            from production_autopilot.reliability import failure_reason, acknowledged_auth_failure, confirmed_terminal_failure, classify
            auth=self.production.authorization(row['account_id'])
            with self.production.planner.connect() as db:acknowledged=provider['state']=='FAILED' and acknowledged_auth_failure(db,row['account_id'],provider)
            # 用户之后明确重新确认，可生产未来新任务；原FAILED永不重试。
            retired_failure=bool(auth and not auth['enabled'] and confirmed_terminal_failure(provider) and classify(failure_reason(provider))[0]!='ACCOUNT_AUTH')
            if auth and not acknowledged and not retired_failure and (provider['state']=='SUBMIT_RESULT_UNCERTAIN' or aware(auth['autopilot_confirmed_at'])<=aware(provider['updated_at'])+timedelta(seconds=1)):
                self.production.attention(row['account_id'],failure_reason(provider))

    def cycle(self):
        # 平台已接受作品的生命周期独立于长期授权；此队列只允许官方只读查询。
        if self.metrics_queue:self.metrics_queue.tick()
        # 磁盘危急只拒绝新生产；轻量指标/平台核对及常驻心跳继续运行。
        from server_maintenance.storage import heavy_dispatch_allowed
        if not heavy_dispatch_allowed(self.production.planner.path):
            return {'state':'STORAGE_CRITICAL','active_accounts':0,'publish_calls':0}
        from media_execution.integration import enabled as media_enabled
        with self.production.planner.connect() as db:
            unified=media_enabled(db)
        if unified:
            from media_execution.planner import cycle
            return cycle(self)
        self.reliability.queue_transient_recovery()
        recovery=self.reliability.process_recovery(self.adapter)
        if recovery:return {'state':'READ_ONLY_RECOVERY_ONLY','recoveries':recovery,'publish_calls':0,'active_accounts':0}
        with self.production.planner.connect() as db:
            auths=[dict(r) for r in db.execute('SELECT * FROM autopilot_authorizations')]
        if not auths:return {'state':'IDLE_AWAITING_USER_CONFIRM','active_accounts':0,'publish_calls':0}
        auths.sort(key=lambda a:a['account_id'])
        offset=self.account_cursor%len(auths);auths=auths[offset:]+auths[:offset]
        self.account_cursor+=1
        active=0
        for auth in auths:
            account=auth['account_id'];grant=ServiceGrant(account,auth['config_hash'])
            try:
                # 暂停后已消费闩锁只读对账；不创建或提交任何新任务。
                for row in self.allocations(account):self.reconcile(row)
                from .production_metrics import collect_account
                try:
                    if self.metrics_queue:self.metrics_queue.submit(account)
                    else:collect_account(self.production,self.adapter,account)
                except Exception as metrics_error:
                    self.reliability.incident(account,str(metrics_error),'METRICS',category='METRICS')
                current=self.production.authorization(account)
                if not current['enabled']:continue
                active+=1
                with self.production.planner.connect() as db:self.production.verify(db,grant)
                if self.config.get('client_executable'):
                    process=run_hidden(['powershell.exe','-NoProfile','-Command',"@(Get-Process -Name '蚁小二4.0' -ErrorAction SilentlyContinue).Count"],timeout=10)
                    if process.returncode or int(process.stdout.decode().strip())==0:raise RuntimeError('蚁小二客户端未运行，请正常启动并登录')
                from yixiaoer_adapter.account_registry import exists
                with self.production.planner.connect() as db:
                    registry_enabled = exists(db)
                if not registry_enabled:
                    accounts=self.adapter.clean(self.adapter.list_accounts())
                    matched=[a for a in accounts if a.get('id')==auth['provider_account_id']]
                    if len(matched)!=1 or matched[0].get('status')!=1:raise RuntimeError('抖音账号失效或离线')
                    with self.production.planner.connect(write=True) as db:
                        db.execute('UPDATE provider_account_bindings SET provider_account_status=\'ONLINE\',provider_last_verified_at=?,raw_account_json=? WHERE business_account_id=? AND provider_account_id=?',
                            (utcnow().isoformat(),json.dumps(matched[0],ensure_ascii=False),account,auth['provider_account_id']))
                # Registry存在时，verify已严格读取本地状态；周期查询只由AccountSyncWorker负责。
                # 恢复已有任务优先；失去合法提前量即停止，不先制造下一批。
                from yixiaoer_adapter.storage import schedule_gate
                missed=[]
                for pending in self.allocations(account):
                    if pending['state'] in ('PLANNED','GENERATING','RENDER_PENDING','READY_TO_DISPATCH'):
                        try:schedule_gate(pending['scheduled_at'])
                        except Exception:
                            provider=self.provider_store.row(pending['job_id']) if pending['job_id'] else None
                            never_submitted=not provider or not any(provider.get(k) for k in ('submit_attempt_count','intent_json','worker_id','provider_task_set_id','provider_task_id'))
                            if pending['state']!='GENERATING' and never_submitted:
                                self.update(pending['allocation_id'],'MISSED_NOT_SUBMITTED',error='SCHEDULE_EXPIRED_NO_RETRY');missed.append(pending['allocation_id'])
                            else:raise
                if missed:raise RuntimeError('DOUYIN_SCHEDULE_TOO_SOON：'+str(len(missed))+'条未提交任务错过提前量；保留记录，确认恢复后仅安排未来视频')
                self.production.reserve_daily(grant)
                generated_this_cycle=0
                for row in self.allocations(account):
                    with self.production.planner.connect() as db:self.production.verify(db,grant)
                    if row['authorization_hash']!=grant.config_hash:continue
                    if row['state']=='PLANNED':
                        if generated_this_cycle>=self.config.get('max_generations_per_account_cycle',1):continue
                        self.generate(grant,row);generated_this_cycle+=1
                    elif row['state']=='GENERATING':raise RuntimeError('生成进程曾中断，需检查已有草稿；禁止重复生成')
                    elif row['job_id']:
                        prior=self.provider_store.row(row['job_id'])
                        if prior['submit_attempt_count']==0 and prior['worker_id']:
                            raise RuntimeError('上传或校验进程曾中断，已停止自动重试，请核查原任务')
                    elif row['state']=='RENDER_PENDING':
                        with self.production.planner.connect() as db:
                            content=db.execute('SELECT * FROM startup_contents WHERE content_id=?',(row['content_id'],)).fetchone()
                        if content and content['production_status']=='READY':self.create_plan(grant,row)
                        elif content and 'FAIL' in content['production_status']:
                            from startup_render.failure_messages import content_failure
                            raise RuntimeError(content_failure(content))
                        elif not self.render_health():raise RuntimeError(getattr(self,'render_failure_reason','渲染工作站离线'))
                with self.production.planner.connect() as db:
                    plans=[r[0] for r in db.execute("SELECT plan_id FROM autopilot_allocations WHERE account_id=? AND authorization_hash=? AND state='READY_TO_DISPATCH' AND plan_id IS NOT NULL",(account,grant.config_hash))]
                    self.production.verify(db,grant)
                if plans:
                    claim=self.provider_store.claim(self.config['worker_id'],plans)
                    if claim:
                        job,token=claim
                        self.adapter.create_publish_job(job,token)
                        self.adapter.reconcile_publish_result(job)
                try:
                    if not self.metrics_queue:collect_account(self.production,self.adapter,account)
                except Exception as metrics_error:self.reliability.incident(account,str(metrics_error),'METRICS',category='METRICS')
            except Exception as error:
                self.reliability.incident(account,str(error))
                self.production.attention(account,str(error))
        return {'state':'RUNNING' if active else 'IDLE_NO_ACTIVE_ACCOUNTS','active_accounts':active}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--once',action='store_true');args=parser.parse_args()
    config=json.loads(Path(args.config).read_text('utf-8-sig'))
    config.setdefault('async_metrics',True)
    from server_maintenance.precheck import service_precheck
    service_precheck('planner')
    production=ProductionStore()
    worker=ProductionWorker(config,production)
    from production_autopilot.operations import Operations
    operations=Operations(production,config,worker.registration.queue.path)
    with single_instance(config['runtime_dir']):
        from production_autopilot.resident_events import record_error, safe_write
        while True:
            try:operations.tick(worker.render_health)
            except Exception as error:
                record_error(config['runtime_dir'],'OPERATIONS',error)
                safe_write(Path(config['runtime_dir'])/'consolidation'/'operations.error.json',{'at':utcnow().isoformat(),'reason':str(error)},runtime=config['runtime_dir'],stage='OPERATIONS_ERROR_WRITE')
                try:worker.reliability.incident('__SYSTEM__',str(error),'OPERATIONS',category='SYSTEM')
                except Exception:pass
            try:result=worker.cycle()
            except Exception as error:
                record_error(config['runtime_dir'],'PLANNER_CYCLE',error)
                result={'state':'SERVICE_ATTENTION_REQUIRED','error':str(error)}
            result.update(pid=__import__('os').getpid(),last_heartbeat=utcnow().isoformat())
            if worker.metrics_queue:
                result['publication_integration']='PRODUCTION_V1'
                result['readonly_accounts_inflight']=len(worker.metrics_queue.pending)
            safe_write(Path(config['runtime_dir'])/'heartbeat.json',result,runtime=config['runtime_dir'],stage='HEARTBEAT_WRITE')
            if args.once:break
            time.sleep(config.get('poll_seconds',60))


if __name__=='__main__':main()
