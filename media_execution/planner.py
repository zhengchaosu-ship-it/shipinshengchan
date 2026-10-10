"""原DailyPlanner/Composition生产循环的单通道接线；无Provider写操作。"""
from datetime import datetime, timezone
import json

from .integration import backlog_allowed, publish_open
from .coordinator import classify_failure


def cycle(worker):
    from startup_autopilot.production import ServiceGrant
    production=worker.production
    from production_autopilot.manual_recovery import drain_outbox, startup_check
    with production.planner.connect() as db:
        check=startup_check(db)
    if check['planner']!='READY':
        return {'state':'PAUSED_SYSTEM','reason_codes':check['reason_codes'],'active_accounts':0,'publish_calls':0}
    drain_outbox(production.planner)
    recovery=process_recovery(worker)
    # 单账号恢复请求不得阻止其他账号本轮规划。
    from production_autopilot.account_runtime import reconcile_accounts, allowed
    with production.planner.connect(write=True) as db: reconcile_accounts(db)
    with production.planner.connect() as db:
        auths=[dict(r) for r in db.execute('SELECT * FROM autopilot_authorizations WHERE enabled=1 ORDER BY account_id')]
        cutoff=float(db.execute("SELECT value FROM media_execution_settings WHERE key='cutover_at'").fetchone()[0])
    for auth in auths:
        grant=ServiceGrant(auth['account_id'],auth['config_hash'])
        with production.planner.connect() as db:
            if not allowed(db,grant.account_id): continue
        try:
            with production.planner.connect() as db:
                production.verify(db,grant)
                capacity=backlog_allowed(db,grant.account_id)
            from .replanning import replan
            for pending in worker.allocations(grant.account_id):
                replan(worker,grant,pending)
            if capacity:
                production.reserve_daily(grant)
            generated=0
            for row in worker.allocations(grant.account_id):
                if datetime.fromisoformat(row['created_at']).timestamp()<cutoff or row['authorization_hash']!=grant.config_hash:
                    continue
                try:
                    if row['state']=='PLANNED' and capacity and generated<worker.config.get('max_generations_per_account_cycle',1):
                        worker.generate(grant,row);generated+=1
                    elif row['state']=='RENDER_PENDING':
                        with production.planner.connect() as db:
                            content=db.execute('SELECT production_status FROM startup_contents WHERE content_id=?',(row['content_id'],)).fetchone()
                            gate=publish_open(db,grant.account_id)
                        if content and content[0]=='READY' and gate:
                            try:
                                from yixiaoer_adapter.storage import schedule_gate
                                schedule_gate(row['scheduled_at'])
                            except ValueError:
                                worker.update(row['allocation_id'],'STALE_SCHEDULE',error='SLOT_EXPIRED_NO_CATCH_UP')
                                continue
                            worker.create_plan(grant,row)
                    elif row['job_id']:
                        with production.planner.connect() as db:
                            execution=db.execute("SELECT state FROM media_execution_jobs WHERE job_type='PUBLISH' AND job_id=?",(row['job_id'],)).fetchone()
                        if execution and execution[0] in ('PUBLISHED','SCHEDULED_QUEUED','SUBMITTED','SUBMIT_RESULT_UNCERTAIN','FAILED_JOB_LEVEL'):
                            worker.update(row['allocation_id'],execution[0])
                except Exception as error:
                    failure=classify_failure(error)
                    if failure.domain=='ACCOUNT_LEVEL': production.attention(grant.account_id,failure.reason)
                    worker.reliability.incident(grant.account_id,str(error),'MEDIA_JOB:'+row['allocation_id'])
                    if row['state']=='PLANNED':
                        from jianying_auto.memory_safety import allocation_failure
                        if allocation_failure(error):
                            from production_autopilot.resident_events import record_error
                            record_error(worker.config['runtime_dir'], 'DRAFT_MEMORY_ALLOCATION', error)
                            worker.update(row['allocation_id'],'FAILED_RETRYABLE',error=str(error))
                            # 子进程已经退出；不在当前循环反复重试，也不清理未知草稿。
                            import gc
                            gc.collect()
                        else:
                            worker.update(row['allocation_id'],'NEEDS_ATTENTION',error=str(error))
                    # 单Job失败继续遍历，禁止停用整个账号或Worker。
            if worker.metrics_queue:
                worker.metrics_queue.submit(grant.account_id)
        except Exception as error:
            worker.reliability.incident(grant.account_id,str(error),'MEDIA_PLANNER')
    return {'state':'CONTROL_PLANE_RUNNING','active_accounts':len(auths),'publish_calls':0,'publisher_execution_node':'WORKER-2060S-01'}


def process_recovery(worker):
    """正式统一模式只使用新强制检查证据；旧请求不能以ONLINE自动清门。"""
    from production_autopilot.account_recovery import retire_legacy_requests
    return retire_legacy_requests(worker.production)


def _legacy_online_recovery_unused(worker):
    """迁移前诊断实现保留，不作为当前生产恢复入口。"""
    with worker.production.planner.connect() as db:
        requests=[dict(r) for r in db.execute("SELECT * FROM production_recovery_requests WHERE state='PENDING'")]
    if not requests:
        return []
    result=[]
    try:
        accounts=worker.adapter.clean(worker.adapter.list_accounts())
        worker.provider_store.refresh_bindings(accounts)
        online={a['id'] for a in accounts if a.get('status')==1}
    except Exception as error:
        online=set();query_error=str(error)
    for request in requests:
        with worker.production.planner.connect(write=True) as db:
            identity=db.execute("SELECT * FROM provider_account_bindings WHERE business_account_id=? AND provider='yixiaoer'",(request['account_id'],)).fetchone()
            auth=db.execute('SELECT * FROM autopilot_authorizations WHERE account_id=?',(request['account_id'],)).fetchone()
            recovered=bool(identity and identity['provider_account_id'] in online and (not auth or auth['status'] not in ('PAUSED','FINISHED')))
            if recovered:
                db.execute("UPDATE media_account_publish_gates SET gate='OPEN',provider_account_status='ONLINE',block_reason=NULL,provider_error=NULL,first_seen_at=NULL,checked_at=? WHERE business_account_id=?",(datetime.now(timezone.utc).timestamp(),request['account_id']))
                db.execute("UPDATE media_execution_jobs SET state='WAITING_REPLAN' WHERE job_type='PUBLISH' AND business_account_id=? AND state='WAITING_ACCOUNT_RECOVERY' AND submit_attempt_count=0",(request['account_id'],))
            value={'account_id':request['account_id'],'gate_recovered':recovered,'resumed':False,'publish_calls':0,
                   'awaiting_components':[],'errors':[] if recovered else [locals().get('query_error','ACCOUNT_STILL_REQUIRES_CHECK')],
                   'historical_jobs_changed':0,'existing_authorization_unchanged':True}
            db.execute('UPDATE production_recovery_requests SET state=?,finished_at=?,result_json=? WHERE request_id=?',
                ('CHECKED' if recovered else 'FAILED',datetime.now(timezone.utc).isoformat(),json.dumps(value,ensure_ascii=False),request['request_id']))
            result.append(value)
    return result
