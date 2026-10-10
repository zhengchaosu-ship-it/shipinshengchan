"""真实用户长期授权、持久额度与生命周期；不代替用户确认，不重复提交。"""
from dataclasses import asdict, dataclass, replace
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from publish_planner.storage import PlannerStore
from .models import Actor, Profile, SHANGHAI, aware, digest, policy
from .shadow_store import ShadowStore, EXCLUDED_BUSINESS, EXCLUDED_PROVIDER
from .template_store import TemplateBuilderStore


def utcnow():return datetime.now(timezone.utc)


def production_policy():
    """按官方当前可取得指标学习；不编造涨粉或完播，不改变基础Shadow策略。"""
    result=policy()
    result.update(policy_version='startup-production-policy-v1',execution_mode='PRODUCTION',minimum_learning_coverage=.5,
        scoring_weights={'views':.5,'likes':.1,'comments':.15,'shares':.15,'favorites':.1,'follow':0,'completion':0})
    return result


@dataclass(frozen=True)
class ServiceGrant:
    account_id: str
    config_hash: str


class ProductionStore:
    def __init__(self, planner=None, shadows=None):
        from .single_studio import planner_store
        self.planner=planner or planner_store()
        self.shadows=shadows or ShadowStore()
        self.builder=TemplateBuilderStore(self.shadows)
        self.builder.operations_path=self.planner.path

    def migrate(self):
        from production_autopilot.account_runtime import migrate, migrate_slots
        with self.planner.connect() as db:
            backup=self.planner.path.with_name(self.planner.path.name+'.before-fault-isolation.bak')
            if not backup.exists():
                with closing(sqlite3.connect(backup)) as saved: db.backup(saved)
            migrate_slots(db)
        with self.planner.connect(write=True) as db:
            migrate(db)
            from production_autopilot.account_recovery import migrate as migrate_recovery
            migrate_recovery(db)
        with self.planner.connect() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='autopilot_authorizations'").fetchone():return
            backup=self.planner.path.with_name(self.planner.path.name+'.autopilot-'+utcnow().strftime('%Y%m%d%H%M%S')+'.bak')
            with closing(sqlite3.connect(backup)) as saved:db.backup(saved)
        with self.planner.connect(write=True) as db:
            db.executescript('BEGIN IMMEDIATE;'+Path(__file__).with_name('migrations').joinpath('003_production.sql').read_text('utf-8'))
        with self.planner.connect() as db: migrate_slots(db)

    def actor(self, token):
        with self.planner.connect() as db:
            principal=self.planner._principal(db,token)
            accounts=self.planner._generation_accounts(db,principal,'STARTUP')
        return Actor(principal['employee_id'],frozenset(a['account_id'] for a in accounts if a['account_id']!=EXCLUDED_BUSINESS),principal['role'])

    def accounts(self,token):
        with self.planner.connect() as db:
            principal=self.planner._principal(db,token)
            from .single_studio import ACTOR_ID
            return [a for a in self.planner._generation_accounts(db,principal,'STARTUP') if principal['employee_id']==ACTOR_ID or a['account_id']!=EXCLUDED_BUSINESS]

    def authorization(self,account_id):
        with self.planner.connect() as db:
            row=db.execute('SELECT * FROM autopilot_authorizations WHERE account_id=?',(account_id,)).fetchone()
        return dict(row) if row else None

    def account_runtime(self, account_id):
        from production_autopilot.account_runtime import runtime
        with self.planner.connect() as db: return runtime(db,account_id)

    def resume(self, token, account_id, *, now=None, recovery_probe=None):
        """用户点击触发强制无发布检查；充分恢复证据成立后才恢复未来授权。"""
        from production_autopilot.account_recovery import forced_check
        return forced_check(self,token,account_id,resume=True,probe=recovery_probe,now=now)

    def event(self,db,account_id,actor,event,evidence):
        from .single_studio import ACTOR_ID,ACTOR_TYPE
        if actor==ACTOR_ID:evidence={**evidence,'actor_type':ACTOR_TYPE,'actor_id':ACTOR_ID}
        db.execute('INSERT INTO autopilot_events(account_id,actor_id,event,recorded_at,evidence_json) VALUES(?,?,?,?,?)',
                   (account_id,actor,event,utcnow().isoformat(),json.dumps(evidence,ensure_ascii=False)))

    def start(self,token,account_id,*,daily_limit,publish_times,target_follower_count,now=None):
        actor=self.actor(token);actor.require(account_id)
        row,base,_,_=self.shadows.load(actor,account_id)
        template=self.builder.active(actor,account_id)
        now=now or utcnow()
        profile=replace(base,execution_mode='PRODUCTION',enabled=True,status='COLD_START',
            template_version='composition-v'+str(template.version),template_hash=template.config_hash(),policy_hash=digest(production_policy()),
            policy_version=production_policy()['policy_version'],
            daily_publish_limit=int(daily_limit),publish_times=tuple(sorted(publish_times)),target_follower_count=target_follower_count,
            confirmed_by=actor.employee_id,confirmed_at=now.isoformat(),attention_reason=None)
        profile=replace(profile,confirmed_config_hash=profile.config_hash());profile.validate()
        with self.planner.connect(write=True) as db:
            self.planner._principal(db,token)
            eligible=self.planner._require_publish_accounts(db,self.planner._principal(db,token),[account_id],'STARTUP')
            account=eligible[account_id]
            if account.get('provider')!='yixiaoer' or account.get('provider_account_id')!=row['provider_account_id'] or row['provider_account_id']==EXCLUDED_PROVIDER:
                raise PermissionError('正式账号绑定不一致')
            from yixiaoer_adapter.storage import production_enabled,cached_binding
            if not production_enabled(db):raise PermissionError('蚁小二正式通道未启用')
            cached_binding(db,account_id,required=True)
            old=db.execute('SELECT * FROM autopilot_authorizations WHERE account_id=?',(account_id,)).fetchone()
            from production_autopilot.account_runtime import allowed, resume_check
            # 首次启动沿用完整preflight；轻量同步检查专用于runtime暂停后的重新ON。
            from production_autopilot.account_runtime import runtime, PAUSED
            if (runtime(db,account_id) or {}).get('status') == PAUSED:
                raise PermissionError('账号运行态已暂停，请使用“重新开启托管”')
            if old and old['enabled']:raise PermissionError('账号已开启托管，请勿重复开始')
            db.execute('''INSERT INTO autopilot_authorizations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL)
                ON CONFLICT(account_id) DO UPDATE SET employee_id=excluded.employee_id,provider_account_id=excluded.provider_account_id,
                status=excluded.status,enabled=0,template_version=excluded.template_version,template_hash=excluded.template_hash,
                config_hash=excluded.config_hash,config_json=excluded.config_json,autopilot_confirmed_by=excluded.autopilot_confirmed_by,
                autopilot_confirmed_at=excluded.autopilot_confirmed_at,updated_at=excluded.updated_at,attention_reason=NULL,finish_choice=NULL''',
                (account_id,actor.employee_id,row['provider_account_id'],'COLD_START',0,template.version,template.config_hash(),profile.config_hash(),
                 json.dumps(asdict(profile),ensure_ascii=False),actor.employee_id,now.isoformat(),now.isoformat()))
            self.event(db,account_id,actor.employee_id,'USER_CONFIRMED_LONG_TERM_PRODUCTION',{'config_hash':profile.config_hash(),'template_version':template.version,'daily_publish_limit':daily_limit,'publish_times':publish_times})
        self.sync_profile(account_id,profile)
        with self.planner.connect(write=True) as db:
            self.planner._principal(db,token)
            self.verify(db,ServiceGrant(account_id,profile.config_hash()),require_enabled=False)
            db.execute('UPDATE autopilot_authorizations SET enabled=1 WHERE account_id=? AND config_hash=?',(account_id,profile.config_hash()))
            from production_autopilot.account_runtime import activate
            activate(db,account_id,now.timestamp())
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='production_incidents'").fetchone():
                db.execute("UPDATE production_incidents SET state='ACKNOWLEDGED',resolved_at=? WHERE account_id=? AND state='OPEN' AND category NOT IN ('UNCERTAIN','METRICS')",(utcnow().isoformat(),account_id))
        return profile

    def sync_profile(self,account_id,profile):
        with self.shadows.connect() as db:
            db.execute('UPDATE shadow_profiles SET payload_json=?,updated_at=? WHERE business_account_id=?',
                (json.dumps(asdict(profile),ensure_ascii=False),utcnow().isoformat(),account_id))

    def verify(self,db,grant,*,require_enabled=True):
        if require_enabled:
            from production_autopilot.restore_guard import assert_dispatch_allowed
            assert_dispatch_allowed(db)
        if not isinstance(grant,ServiceGrant) or grant.account_id==EXCLUDED_BUSINESS:raise PermissionError('DURABLE_AUTOPILOT_GRANT_REQUIRED')
        if require_enabled:
            from production_autopilot.account_runtime import allowed
            if not allowed(db,grant.account_id): raise PermissionError('ACCOUNT_RUNTIME_PAUSED')
        auth=db.execute('SELECT * FROM autopilot_authorizations WHERE account_id=?',(grant.account_id,)).fetchone()
        if not auth or auth['config_hash']!=grant.config_hash or require_enabled and not auth['enabled']:
            raise PermissionError('托管已暂停或授权已变更')
        from .single_studio import StudioPlannerStore,LocalOperator,ACTOR_ID
        if isinstance(self.planner,StudioPlannerStore) and self.planner.is_studio():
            principal=self.planner._principal(db,LocalOperator())
        else:
            if auth['employee_id']==ACTOR_ID:raise PermissionError('LOCAL_OPERATOR_MODE_DISABLED')
            principal=db.execute('SELECT * FROM employees WHERE employee_id=? AND enabled=1',(auth['employee_id'],)).fetchone()
        if not principal:raise PermissionError('EMPLOYEE_DISABLED')
        accounts=self.planner._generation_accounts(db,principal,'STARTUP')
        account=next((a for a in accounts if a['account_id']==grant.account_id),None)
        if not account or account.get('provider_account_id')!=auth['provider_account_id'] or auth['provider_account_id']==EXCLUDED_PROVIDER:
            raise PermissionError('ACCOUNT_PERMISSION_OR_BINDING_CHANGED')
        from yixiaoer_adapter.storage import cached_binding
        from media_execution.integration import enabled as media_enabled
        binding=cached_binding(db,grant.account_id,required=not media_enabled(db))
        if not binding or binding['provider_account_id']!=auth['provider_account_id']:
            raise PermissionError('ACCOUNT_PERMISSION_OR_BINDING_CHANGED')
        profile=Profile(**{**json.loads(auth['config_json']),'publish_times':tuple(json.loads(auth['config_json'])['publish_times'])})
        profile.validate()
        if profile.policy_hash!=digest(production_policy()):raise PermissionError('托管策略已变更，需要重新确认')
        actor=Actor(principal['employee_id'],frozenset([grant.account_id]),principal['role'])
        template=self.builder.active(actor,grant.account_id)
        current=self.shadows.load(actor,grant.account_id)[1]
        if template.version!=auth['template_version'] or template.config_hash()!=auth['template_hash'] or current.config_hash()!=auth['config_hash']:
            raise PermissionError('模板或账号设置已修改，需要重新确认托管')
        return principal,auth,actor,profile,template

    def control(self,token,account_id,action,*,finish_choice='KEEP_PLATFORM_QUEUE'):
        actor=self.actor(token);actor.require(account_id)
        if action not in ('pause','finish'):raise ValueError('INVALID_CONTROL')
        with self.planner.connect(write=True) as db:
            self.planner._principal(db,token)
            row=db.execute('SELECT * FROM autopilot_authorizations WHERE account_id=?',(account_id,)).fetchone()
            if not row or row['employee_id']!=actor.employee_id and actor.role!='ADMIN':raise PermissionError('托管授权不存在')
            state='PAUSED' if action=='pause' else 'FINISHED'
            db.execute('UPDATE autopilot_authorizations SET enabled=0,status=?,finish_choice=?,updated_at=? WHERE account_id=?',
                (state,finish_choice if action=='finish' else None,utcnow().isoformat(),account_id))
            from production_autopilot.account_runtime import cancel_future
            db.execute("INSERT INTO autopilot_account_runtime(account_id,status,updated_at) VALUES(?,'OFF',?) ON CONFLICT(account_id) DO UPDATE SET status='OFF',updated_at=excluded.updated_at",(account_id,utcnow().timestamp()))
            cancel_future(db,account_id,utcnow().timestamp())
            if action=='finish' and finish_choice=='STOP_UNSUBMITTED':
                for allocation in db.execute('SELECT * FROM autopilot_allocations WHERE account_id=?',(account_id,)).fetchall():
                    job_id=allocation['job_id']
                    if job_id:
                        provider=db.execute('SELECT * FROM provider_publish_jobs WHERE job_id=?',(job_id,)).fetchone()
                        if not provider or provider['submit_attempt_count'] or provider['intent_json'] or provider['worker_id'] or provider['provider_task_set_id'] or provider['provider_task_id']:continue
                        db.execute("UPDATE provider_publish_jobs SET state='CANCELLED',updated_at=? WHERE job_id=?",(utcnow().isoformat(),job_id))
                        db.execute("UPDATE publish_jobs SET status='CANCELLED',current_step='AUTOPILOT_USER_STOPPED_UNSUBMITTED',updated_at=? WHERE job_id=?",(utcnow().isoformat(),job_id))
                    db.execute("UPDATE autopilot_allocations SET state='STOPPED_UNSUBMITTED',updated_at=? WHERE allocation_id=?",(utcnow().isoformat(),allocation['allocation_id']))
            self.event(db,account_id,actor.employee_id,'USER_'+state,{'finish_choice':finish_choice,'provider_cancel_count':0})
        raw=json.loads(row['config_json']);raw.update(enabled=False,status=state)
        self.sync_profile(account_id,Profile(**{**raw,'publish_times':tuple(raw['publish_times'])}))

    def attention(self,account_id,reason):
        from media_execution.coordinator import classify_failure
        from production_autopilot.account_runtime import pause, fault
        failure=classify_failure(RuntimeError(str(reason)))
        with self.planner.connect(write=True) as db:
            if failure.domain=='ACCOUNT_LEVEL': pause(db,account_id,failure.reason)
            else: fault(db,failure.domain,account_id,None,failure.reason,'此异常仅影响相关任务')

    def occupancy(self,db,account_id,day):
        identities=set()
        for r in db.execute("SELECT allocation_id,content_id FROM autopilot_allocations WHERE account_id=? AND local_day=? AND state!='CANCELLED_BY_ACCOUNT_PAUSE'",(account_id,day)):
            identities.add(r['content_id'] or 'allocation:'+r['allocation_id'])
        for r in db.execute("SELECT i.content_id,i.scheduled_at FROM publish_plan_items i JOIN publish_jobs j USING(job_id) WHERE i.account_id=? AND j.status!='CANCELLED'",(account_id,)):
            if aware(r['scheduled_at']).astimezone(SHANGHAI).date().isoformat()==day:identities.add(r['content_id'])
        with self.shadows.connect(readonly=True) as profile_db:
            for public in profile_db.execute('SELECT work_id,actual_published_at FROM composition_public_samples WHERE account_id=?',(account_id,)):
                if aware(public['actual_published_at']).astimezone(SHANGHAI).date().isoformat()!=day:continue
                match=db.execute('SELECT j.content_id FROM provider_publish_jobs p JOIN publish_jobs j USING(job_id) JOIN publish_plan_items i USING(job_id) WHERE p.provider_video_id=? AND i.account_id=?',(public['work_id'],account_id)).fetchone()
                identities.add(match[0] if match else 'public:'+public['work_id'])
        return len(identities)

    def reserve_daily(self,grant,now=None):
        from .composition_planner import preview
        now=now or utcnow()
        with self.planner.connect() as db:
            _,auth,actor,profile,template=self.verify(db,grant)
            history=[dict(r) for r in db.execute('SELECT * FROM autopilot_allocations WHERE account_id=? ORDER BY scheduled_at',(grant.account_id,))]
        catalogs=self.builder.catalog.refresh(actor,grant.account_id,hash_budget=5)
        samples,affinities=self.builder.context(actor,grant.account_id)
        material_history=[{'account_id':grant.account_id,'slot_position':s['slot_position'],'material_id':s['material_id'],'used_at':r['scheduled_at']} for r in history for s in json.loads(r['proposal_json'])['selections']]
        composition_history=[{'account_id':grant.account_id,'signature':r['composition_signature'],'used_at':r['scheduled_at']} for r in history]
        occupied_times={r['scheduled_at'] for r in history if r['state']!='CANCELLED_BY_ACCOUNT_PAUSE'}
        first=now.astimezone(SHANGHAI).date()
        candidates=[aware(first.isoformat()+'T'+t+':00+08:00') for t in profile.publish_times]
        if not any(at>=now+timedelta(seconds=8100) for at in candidates):first+=timedelta(days=1)
        with self.planner.connect(write=True) as db:
            self.verify(db,grant)
            available=max(0,profile.daily_publish_limit-self.occupancy(db,grant.account_id,first.isoformat()))
            eligible=[]
            for t in profile.publish_times:
                at=aware(first.isoformat()+'T'+t+':00+08:00')
                if at<now+timedelta(seconds=8100) or at>now+timedelta(days=14) or at.isoformat() in occupied_times:continue
                if db.execute("SELECT 1 FROM publish_plan_items i JOIN publish_jobs j USING(job_id) WHERE i.account_id=? AND i.scheduled_at=? AND j.status!='CANCELLED'",(grant.account_id,at.isoformat())).fetchone():continue
                eligible.append(at.isoformat())
            eligible=eligible[:available]
            if not eligible:return []
            result=preview(actor,template,catalogs,now,days=1,daily_limit=profile.daily_publish_limit,samples=samples,affinities=affinities,
                material_history=material_history,composition_history=composition_history,publish_times=profile.publish_times,
                learning_threshold=profile.learning_threshold,start_day=first,eligible_times=set(eligible))
            # 合法组合按原slot生产；不能组成的slot自然留空，不下调用户额度或连累其它slot。
            blocked=result['days'][0]['blocked']
            ids=[]
            for proposal in result['days'][0]['proposals']:
                key=str(uuid4());at=utcnow().isoformat()
                db.execute('''INSERT INTO autopilot_allocations(allocation_id,account_id,local_day,scheduled_at,composition_signature,template_version,
                    proposal_json,authorization_hash,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,'PLANNED',?,?)''',
                    (key,grant.account_id,first.isoformat(),proposal['scheduled_at'],proposal['composition_signature'],template.version,json.dumps(proposal,ensure_ascii=False),grant.config_hash,at,at))
                ids.append(key)
                from production_autopilot.reliability import link_reserved_replacement
                link_reserved_replacement(db,self,grant,key)
            if ids or blocked:
                self.event(db,grant.account_id,'AUTOPILOT_WORKER','DAILY_CAPACITY_RESERVED',{'allocation_ids':ids,
                    'existing_occupied':profile.daily_publish_limit-available,'daily_limit':profile.daily_publish_limit,
                    'unfilled_slots':blocked,'catch_up':False,'carry_over':False})
            return ids


class AutopilotPlannerStore(PlannerStore):
    """后台使用经验证的长期授权；不伪造登录会话或每日用户Confirm。"""
    def __init__(self,production):
        super().__init__(production.planner.path);self.production=production

    def _principal(self,db,token,*,admin=False):
        if isinstance(token,ServiceGrant):
            principal,*_=self.production.verify(db,token)
            if admin:raise PermissionError('AUTOPILOT_ADMIN_FORBIDDEN')
            return principal
        return super()._principal(db,token,admin=admin)

    def _generation_accounts(self,db,actor,business_type):
        accounts=super()._generation_accounts(db,actor,business_type)
        return [a for a in accounts if a['account_id']!=EXCLUDED_BUSINESS]

    def _accounts(self,db,actor,**kwargs):
        from .single_studio import ACTOR_ID
        if actor['employee_id']==ACTOR_ID:return self.production.planner._accounts(db,actor,**kwargs)
        return super()._accounts(db,actor,**kwargs)

    def generation_owner_available(self,db,owner):
        return self.production.planner.generation_owner_available(db,owner)
