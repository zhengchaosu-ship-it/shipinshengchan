"""账号级去重异常和后台只读验证恢复。所有身份来自稳定ID。"""
from contextlib import closing
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from startup_autopilot.production import utcnow


def classify(reason):
    reason=str(reason)
    from startup_render.failure_messages import render_message
    render=render_message(reason)
    if render:return 'RENDER',render,'核对原视频的渲染记录和成片；修复后由您确认恢复托管，不自动重新生成或发布',False
    if 'RESTORE_' in reason:return 'RESTORE','备份恢复需要核对平台历史','在高级管理完成恢复检查；核对前不产生新的生成、渲染或发布',False
    if any(x in reason for x in ('UNBOUND','MAPPING','BINDING_CHANGED','ACCOUNT_IDENTITY_MISMATCH','ACCOUNT_EVIDENCE_UNAVAILABLE')):
        return 'MAPPING', '发布账号绑定需要核对', '在高级管理确认唯一的账号ID映射', False
    if any(x in reason.upper() for x in ('TIMEOUT','TIMED OUT','CONNECTION','NETWORK','HTTP_503','HTTP 503','HTTP_502','超时','网络不可用')):
        return 'PROVIDER_TEMPORARY', '后台连接暂时不可用', '系统保留原任务并每15分钟只读复查；不会重复发布', True
    if any(x in reason for x in ('ACCOUNT_NOT_VALID','ACCOUNT_OFFLINE','账号失效','账号离线','认证','验证','短信','扫码','登录','AUTH','客户端未运行')):
        if any(x in reason for x in ('创作者中心','账号存在风险','官方平台检测')):
            return 'ACCOUNT_AUTH','抖音平台需要人工验证','前往抖音创作者中心完成平台提示的验证，再回到这里点击重新检查',True
        return 'ACCOUNT_AUTH', '发布账号或客户端需要验证', '在蚁小二完成短信、扫码、登录或重新授权，然后点击重新检查', True
    if any(x in reason for x in ('UNCERTAIN','不确定','SUBMIT_INTENT')):
        return 'UNCERTAIN', '平台提交结果尚未确认', '点击重新检查；结果未确认前保留原任务，不重复发布', False
    if any(x in reason for x in ('未找到此作品','可能已删除')):
        return 'WORK_MISSING', '平台作品记录需要核对', '在抖音创作者中心确认作品是否存在或已删除；核对后再确认恢复托管', False
    if any(x in reason for x in ('FAILED','发布失败','发布需要处理')):
        return 'PUBLISH_FAILED', '平台发布失败', '查看蚁小二失败原因；原失败任务保留，修复后由您确认恢复托管', False
    if any(x in reason for x in ('Render','渲染','工作站')):
        return 'RENDER', '渲染工作站需要检查', '检查工作站、剪映和渲染输出，核验已有任务后恢复托管', False
    if any(x in reason for x in ('SCHEDULE','提前量','TIME')):
        return 'SCHEDULE', '原发布时间已错过安全提前量', '保留原任务，重新检查后确认恢复；系统仅安排新的未来时段', False
    if any(x in reason for x in ('素材','疲劳','MATERIAL','BACKGROUND')):
        return 'ASSET', '账号素材或视觉设置需要处理', '补充素材或调整账号设置，然后确认恢复托管', False
    return 'OTHER', '托管遇到异常', '查看异常详情，修复后确认恢复托管', False


def failure_reason(provider):
    try:
        tasks=json.loads(provider.get('provider_raw_status') or '{}').get('tasks',[])
        message=tasks[0].get('errorMessage') if len(tasks)==1 else None
        if message:return '发布需要处理：'+str(message)
    except (ValueError,TypeError,AttributeError):pass
    return '发布需要处理：'+provider['state']


def acknowledged_auth_failure(db, account, provider):
    if classify(failure_reason(provider))[0]!='ACCOUNT_AUTH':return False
    for row in db.execute("SELECT result_json FROM production_recovery_requests WHERE account_id=? AND state='CHECKED' ORDER BY finished_at DESC LIMIT 20",(account,)):
        result=json.loads(row[0])
        if result.get('resumed') and provider['job_id'] in result.get('auth_failed_job_ids',[]):return True
    return False


def confirmed_terminal_failure(provider):
    """失败不是活动任务；必须有同一已提交Task的官方终态证据。"""
    try:
        tasks=json.loads(provider.get('provider_raw_status') or '{}')['tasks']
        return bool(provider['state']=='FAILED' and provider['submit_attempt_count']>=1 and provider['provider_task_set_id']
            and len(tasks)==1 and tasks[0]['id']==provider['provider_task_id']
            and tasks[0].get('stageStatus') in ('fail','failed'))
    except (ValueError,TypeError,KeyError):return False


class ReliabilityStore:
    def __init__(self, production):
        self.production=production
        self.planner=production.planner

    def migrate(self):
        with self.planner.connect() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='production_incidents'").fetchone():return
            backup=self.planner.path.with_name(self.planner.path.name+'.consolidation-'+utcnow().strftime('%Y%m%d%H%M%S%f')+'.bak')
            with closing(sqlite3.connect(backup)) as out:db.backup(out)
        with self.planner.connect(write=True) as db:
            schema=db.execute("SELECT sql FROM sqlite_master WHERE name='autopilot_allocations'").fetchone()[0]
            if 'UNIQUE(account_id,composition_signature)' in schema.replace(' ','').replace('\n',''):
                db.executescript(Path(__file__).with_name('allocation_migration.sql').read_text('utf-8'))
            db.executescript('BEGIN IMMEDIATE;'+Path(__file__).with_name('migration.sql').read_text('utf-8'))
            if db.execute('PRAGMA foreign_key_check').fetchall():raise RuntimeError('CONSOLIDATION_MIGRATION_INTEGRITY_ERROR')

    def incident(self, account, reason, source='ACCOUNT', *, category=None):
        kind,_,_,resume=classify(reason);kind=category or kind
        at=utcnow().isoformat()
        with self.planner.connect(write=True) as db:
            db.execute('''INSERT INTO production_incidents VALUES(?,?,?,?,?,'OPEN',?,?,?,NULL)
                ON CONFLICT(account_id,category,source_key) DO UPDATE SET reason=excluded.reason,
                state='OPEN',last_seen_at=excluded.last_seen_at,resolved_at=NULL''',
                (str(uuid4()),account,kind,source,str(reason),int(resume),at,at))

    def request(self, token, account):
        with self.planner.connect() as db:
            from media_execution.integration import enabled
            unified=enabled(db)
        if unified:
            from .account_recovery import forced_check
            return forced_check(self.production,token,account)['check_id']
        self.production.actor(token).require(account)
        actor=self.production.actor(token)
        with self.planner.connect(write=True) as db:
            self.planner._principal(db,token)
            old=db.execute("SELECT request_id FROM production_recovery_requests WHERE account_id=? AND state='PENDING'",(account,)).fetchone()
            if old:return old[0]
            key=str(uuid4())
            db.execute("INSERT INTO production_recovery_requests VALUES(?,?,?,?,'PENDING',NULL,NULL)",
                (key,account,actor.employee_id,utcnow().isoformat()))
            return key

    def rows(self, accounts):
        with self.planner.connect() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='production_incidents'").fetchone():return []
            return [dict(r) for r in db.execute("SELECT * FROM production_incidents WHERE state='OPEN' ORDER BY first_seen_at") if r['account_id'] in accounts]

    def queue_transient_recovery(self):
        now=utcnow()
        with self.planner.connect(write=True) as db:
            for auth in db.execute("SELECT * FROM autopilot_authorizations WHERE status='ATTENTION_REQUIRED' AND enabled=0").fetchall():
                if classify(auth['attention_reason'])[0]!='PROVIDER_TEMPORARY':continue
                last=db.execute('SELECT * FROM production_recovery_requests WHERE account_id=? ORDER BY requested_at DESC LIMIT 1',(auth['account_id'],)).fetchone()
                if last and (last['state']=='PENDING' or now-datetime.fromisoformat(last['requested_at'])<timedelta(minutes=15)):continue
                db.execute("INSERT INTO production_recovery_requests VALUES(?,?,?,?,'PENDING',NULL,NULL)",
                    (str(uuid4()),auth['account_id'],'AUTOPILOT_PROVIDER_RECOVERY',now.isoformat()))

    def process_recovery(self, adapter):
        """只调用list_accounts和reconcile；不能claim、create_plan或create_publish_job。"""
        from startup_autopilot.production import ServiceGrant
        with self.planner.connect() as db:
            pending=[dict(r) for r in db.execute("SELECT * FROM production_recovery_requests WHERE state='PENDING'")]
        if not pending:return []
        from yixiaoer_adapter.account_registry import BusinessAccountRegistry
        registry=BusinessAccountRegistry(self.planner.path)
        result=[]
        # 一个批次只读取一次Provider；失败不改变上次成功账号快照。
        run=registry.begin()
        try:
            registry.apply(adapter.clean(adapter.list_accounts()),run_id=run)
            sync_error=None
        except Exception as error:
            sync_error=str(error);registry.fail(run,'RECOVERY_QUERY_FAILED')
        for request in pending:
            account=request['account_id'];errors=[];auth_failed_ids=[];identity_checked=False
            if sync_error:errors.append(sync_error)
            try:
                from yixiaoer_adapter.storage import cached_binding
                with self.planner.connect() as db:
                    cached_binding(db,account,required=True)
                    # 包含既有人工计划；严格按business_account_id限定。
                    jobs=[dict(r) for r in db.execute('''SELECT p.* FROM provider_publish_jobs p
                        JOIN publish_plan_items i USING(job_id) WHERE i.account_id=? AND p.submit_attempt_count=1''',(account,))]
                if not sync_error:
                    for job in jobs:
                        if job['state'] not in ('PUBLISHED','CANCELLED') and (job['state']!='FAILED' or job['provider_task_set_id']):
                            adapter.reconcile_publish_result(job['job_id'])
                refreshed=[adapter.store.row(j['job_id']) for j in jobs] if jobs and not sync_error else jobs
                identity_checked=not sync_error
                blockers=[j['job_id'] for j in refreshed if j['state'] in ('SUBMIT_INTENT','SUBMIT_RESULT_UNCERTAIN')]
                if blockers:errors.append('UNCERTAIN_JOB_REQUIRES_EVIDENCE')
                auth=self.production.authorization(account)
                from startup_autopilot.models import aware
                auth_failed_ids=[j['job_id'] for j in refreshed if j['state']=='FAILED' and classify(failure_reason(j))[0]=='ACCOUNT_AUTH']
                if auth and any(j['state']=='FAILED' and j['job_id'] not in auth_failed_ids and aware(j['updated_at'])+timedelta(seconds=1)>=aware(auth['autopilot_confirmed_at']) for j in refreshed):errors.append('FAILED_JOB_REQUIRES_USER_REVIEW')
                # 验证期间错过时段的未提交分配只做本地对账；不重新生成、不改平台排期。
                if not sync_error:
                    from yixiaoer_adapter.storage import schedule_gate
                    with self.planner.connect(write=True) as db:
                        allocations=db.execute("SELECT * FROM autopilot_allocations WHERE account_id=? AND state IN ('PLANNED','GENERATING','RENDER_PENDING','READY_TO_DISPATCH')",(account,)).fetchall()
                        for allocation in allocations:
                            if allocation['state']=='GENERATING':errors.append('INTERRUPTED_GENERATION_REQUIRES_REVIEW');continue
                            p=db.execute('SELECT * FROM provider_publish_jobs WHERE job_id=?',(allocation['job_id'],)).fetchone() if allocation['job_id'] else None
                            if p and any(p[k] for k in ('submit_attempt_count','intent_json','worker_id','provider_task_set_id','provider_task_id')):
                                if not p['submit_attempt_count']:errors.append('INTERRUPTED_UPLOAD_REQUIRES_REVIEW')
                                continue
                            try:schedule_gate(allocation['scheduled_at'])
                            except Exception:
                                db.execute("UPDATE autopilot_allocations SET state='MISSED_NOT_SUBMITTED',error='SCHEDULE_EXPIRED_DURING_VERIFICATION',updated_at=? WHERE allocation_id=?",(utcnow().isoformat(),allocation['allocation_id']))
            except Exception as error:errors.append(str(error))
            resumed=False;awaiting=[]
            auth=self.production.authorization(account)
            recoverable=bool(auth and (classify(auth.get('attention_reason'))[0] in ('ACCOUNT_AUTH','PROVIDER_TEMPORARY') or classify(auth.get('attention_reason'))[0]=='PUBLISH_FAILED' and auth_failed_ids))
            if not errors and auth and auth['status']=='ATTENTION_REQUIRED' and recoverable:
                try:
                    with self.planner.connect(write=True) as db:
                        _,current,actor,profile,_=self.production.verify(db,ServiceGrant(account,auth['config_hash']),require_enabled=False)
                        allowed=('ACCOUNT_AUTH','PROVIDER_TEMPORARY','METRICS','PUBLISH_FAILED') if auth_failed_ids else ('ACCOUNT_AUTH','PROVIDER_TEMPORARY','METRICS')
                        # NULL字段已用原payload/hash核验通过，解除此前兼容性误报。
                        db.execute("UPDATE production_incidents SET state='RESOLVED',resolved_at=? WHERE account_id=? AND reason='YIXIAOER_TASK_ACCOUNT_IDENTITY_MISMATCH'",(utcnow().isoformat(),account))
                        open_other=db.execute("SELECT 1 FROM production_incidents WHERE account_id=? AND state='OPEN' AND category NOT IN ("+','.join('?' for _ in allowed)+")",(account,*allowed)).fetchone()
                        health=db.execute("SELECT component FROM production_health_snapshots WHERE component IN ('Render Worker','数据库','磁盘空间','Render输出目录') AND state NOT IN ('OK')").fetchall()
                        awaiting=[r[0] for r in health]
                        # 请求处理期间用户暂停/结束优先；不重建、不换授权。
                        if not open_other and not awaiting and current['status']=='ATTENTION_REQUIRED' and current['attention_reason']==auth['attention_reason']:
                            from dataclasses import replace
                            profile=replace(profile,enabled=True,status='COLD_START',attention_reason=None)
                            db.execute("UPDATE autopilot_authorizations SET enabled=1,status='COLD_START',attention_reason=NULL,updated_at=? WHERE account_id=?",(utcnow().isoformat(),account))
                            self.production.event(db,account,request['requested_by'],'AUTH_RECOVERED_READ_ONLY',{'request_id':request['request_id'],'publish_calls':0})
                            resumed=True
                    if resumed:self.production.sync_profile(account,profile)
                except Exception as error:errors.append(str(error))
            at=utcnow().isoformat();out={'account_id':account,'errors':errors,'resumed':resumed,'awaiting_components':awaiting,'auth_failed_job_ids':auth_failed_ids,'publish_calls':0}
            with self.planner.connect(write=True) as db:
                if identity_checked:
                    # 账号/任务证据已经逐项核验；其它业务阻塞不能保留此次兼容性误报。
                    db.execute("UPDATE production_incidents SET state='RESOLVED',resolved_at=? WHERE account_id=? AND reason='YIXIAOER_TASK_ACCOUNT_IDENTITY_MISMATCH'",(at,account))
                if not errors:
                    db.execute("UPDATE production_incidents SET state='RESOLVED',resolved_at=? WHERE account_id=? AND category IN ('ACCOUNT_AUTH','PROVIDER_TEMPORARY')",(at,account))
                    if resumed and auth_failed_ids:db.execute("UPDATE production_incidents SET state='RESOLVED',resolved_at=? WHERE account_id=? AND category='PUBLISH_FAILED'",(at,account))
                db.execute('UPDATE production_recovery_requests SET state=?,finished_at=?,result_json=? WHERE request_id=?',
                    ('FAILED' if errors else 'CHECKED',at,json.dumps(out,ensure_ascii=False),request['request_id']))
            result.append(out)
        return result

    def link_replacement(self, token, parent, child):
        """用户确认把已正常保留额度的未来分配作为补位；不重试或改变父任务。"""
        with self.planner.connect(write=True) as db:
            actor=self.production.actor(token);self.planner._principal(db,token)
            old=db.execute('SELECT * FROM autopilot_allocations WHERE allocation_id=?',(parent,)).fetchone()
            new=db.execute('SELECT * FROM autopilot_allocations WHERE allocation_id=?',(child,)).fetchone()
            if not old or not new or old['account_id']!=new['account_id']:raise ValueError('REPLACEMENT_ACCOUNT_MISMATCH')
            actor.require(old['account_id'])
            if old['state'] not in ('FAILED','MISSED_NOT_SUBMITTED','STOPPED_UNSUBMITTED') or new['state']!='PLANNED':raise ValueError('REPLACEMENT_STATE_INVALID')
            if old['job_id']:
                p=db.execute('SELECT * FROM provider_publish_jobs WHERE job_id=?',(old['job_id'],)).fetchone()
                if not p or p['state']!='FAILED' or not p['provider_task_set_id']:raise ValueError('TERMINAL_FAILURE_EVIDENCE_REQUIRED')
            from startup_autopilot.models import aware
            if old['local_day']!=new['local_day'] or aware(old['scheduled_at'])<=utcnow()+timedelta(seconds=8100):
                raise ValueError('SLOT_CATCH_UP_FORBIDDEN')
            if aware(new['scheduled_at'])<=utcnow()+timedelta(seconds=8100):raise ValueError('REPLACEMENT_MUST_BE_FUTURE')
            profile=self.production.shadows.load(actor,new['account_id'])[1]
            if self.production.occupancy(db,new['account_id'],new['local_day'])>min(5,profile.daily_publish_limit):raise ValueError('DAILY_BUDGET_EXCEEDED')
            db.execute('INSERT INTO production_job_lineage VALUES(?,?,?,?,?,?)',
                (child,parent,new['account_id'],actor.employee_id,utcnow().isoformat(),json.dumps({'parent_job_id':old['job_id'],'original_unchanged':True})))
            self.production.event(db,new['account_id'],actor.employee_id,'REPLACEMENT_LINEAGE_CONFIRMED',{'parent':parent,'child':child})


def link_reserved_replacement(db, production, grant, child):
    """仅日内尚有效slot可记录替换；过期或跨天失败不是新一天的欠账。"""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='production_job_lineage'").fetchone():return
    from startup_autopilot.models import aware
    auth=db.execute('SELECT * FROM autopilot_authorizations WHERE account_id=?',(grant.account_id,)).fetchone()
    new=db.execute('SELECT * FROM autopilot_allocations WHERE allocation_id=?',(child,)).fetchone()
    rows=db.execute('''SELECT a.*,p.state AS provider_state,p.provider_task_set_id,p.provider_stage_status,p.provider_raw_status,p.updated_at AS failure_at
        FROM autopilot_allocations a JOIN provider_publish_jobs p USING(job_id)
        WHERE a.account_id=? AND a.state='FAILED' AND p.state='FAILED'
        AND NOT EXISTS(SELECT 1 FROM production_job_lineage l WHERE l.parent_allocation_id=a.allocation_id)
        ORDER BY a.scheduled_at''',(grant.account_id,)).fetchall()
    parent=None
    for row in rows:
        if not new or row['local_day']!=new['local_day'] or aware(row['scheduled_at'])<=utcnow()+timedelta(seconds=8100):continue
        if not row['provider_task_set_id'] or row['provider_stage_status'] not in ('fail','failed'):continue
        explicitly_resumed=aware(row['failure_at'])+timedelta(seconds=1)<aware(auth['autopilot_confirmed_at'])
        if explicitly_resumed or acknowledged_auth_failure(db,grant.account_id,dict(row)):
            parent=row;break
    if parent:
        db.execute('INSERT INTO production_job_lineage VALUES(?,?,?,?,?,?)',
            (child,parent['allocation_id'],grant.account_id,auth['autopilot_confirmed_by'],utcnow().isoformat(),json.dumps({'parent_job_id':parent['job_id'],'authorization_hash':grant.config_hash,'new_future_content':True,'parent_unchanged':True})))
        production.event(db,grant.account_id,'AUTOPILOT_WORKER','FUTURE_REPLACEMENT_LINEAGE_RECORDED',{'parent':parent['allocation_id'],'child':child})
