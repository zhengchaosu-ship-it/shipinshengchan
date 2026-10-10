"""真实2060验收的隔离业务库：复用正式登记、RenderQueue、Confirm和ProviderStore。"""
from datetime import datetime,timedelta,timezone,time as daytime
import json
from pathlib import Path
from types import SimpleNamespace

from publish_planner.storage import PlannerStore
from publish_planner.models import Plan
from startup_pipeline.service import StartupPipeline
from startup_pipeline.registration import StartupContentRegistration
from startup_render.queue import RenderQueue
from startup_render.common import read,save,package
from yixiaoer_adapter.storage import ProviderStore,enroll_confirmed,check_slots
from .production import ProductionControlPlane


ROOT=Path(__file__).resolve().parents[1]/'outputs/lan_render/2060_acceptance_20261007_v2'
UNC='\\\\PC-20260617GEOP\\RenderOutput\\2060_acceptance_20261007_v2'


def initialize():
    if (ROOT/'setup.json').exists():return read(ROOT/'setup.json')
    ROOT.mkdir(parents=True,exist_ok=True)
    store=PlannerStore(ROOT/'operations.db');store.migrate()
    password=__import__("os").environ["XUNZHEN_ACCEPTANCE_PASSWORD"]
    with store.connect() as db:existing=db.execute("SELECT employee_id FROM employees WHERE login_name='acceptance'").fetchone()
    admin=existing[0] if existing else store.bootstrap_admin('acceptance',password)
    token=store.login('acceptance',password)
    store.sync_snapshot({'run_id':'ACCEPTANCE-'+datetime.now(timezone.utc).isoformat(),'complete':True,'groups':[{'group_id':'TEST','group_name':'TEST','identity_status':'SOURCE_ID'}],
        'accounts':[{'account_id':'ACCEPT-'+key,'group_id':'TEST','display_name':'2060验收'+key,'platform':'抖音','online_status':'ONLINE','is_available':True,'identity_evidence':'ISOLATED_MOCK_PROVIDER'} for key in ('A','B')]},session_token=token)
    store.save_employee(token,employee_id=admin,employee_name='acceptance',login_name='acceptance',role='ADMIN',group_bindings=[{'group_id':'TEST','group_role':'STARTUP'}])
    token=store.login('acceptance',password)
    pipeline=StartupPipeline(store,batch_root=ROOT/'batches');pipeline.migrate()
    from startup_pipeline.plan_confirmation import migrate
    migrate(store)
    provider=ProviderStore(store);provider.migrate();provider.migrate_production()
    for key in ('A','B'):provider.bind('ACCEPT-'+key,{'id':'MOCK-PROVIDER-'+key,'status':1},source='ISOLATED_ACCEPTANCE')
    with store.connect(write=True) as db:
        db.execute("INSERT OR IGNORE INTO yixiaoer_settings VALUES('production_enabled','true')")
        db.execute("INSERT OR IGNORE INTO yixiaoer_settings VALUES('canary_pass',?)",(json.dumps({'result':'YIXIAOER_8502_PRODUCTION_CANARY_PASS','scope':'ISOLATED_MOCK_ONLY'}),))
    registration=StartupContentRegistration(pipeline,RenderQueue(ROOT/'render_jobs.db'))
    contexts=[registration.begin(token,'ACCEPT-'+key,5) for key in ('A','B')]
    config={'operations_db':str(store.path),'state_root':str(ROOT),'worker_ids':['WORKER-2060S-01'],
            'render_output_unc':UNC+'\\archive','startup_assets_root':str(ROOT/'assets'),'startup_assets_unc':UNC+'\\assets','task_files_unc':UNC+'\\packages'}
    control=ProductionControlPlane(config,SimpleNamespace(db_path=ROOT/'render_jobs.db'));control.migrate()
    with control.connect(write=True) as db:
        db.execute("UPDATE media_execution_settings SET value=? WHERE key='cutover_at'",(str(min(datetime.fromisoformat(c['started_at']).timestamp() for c in contexts)-1),))
    control.set_account('ACCEPT-A','BLOCKED_RISK','ONLINE',reason='ISOLATED_RISK_CASE')
    control.set_account('ACCEPT-B','OPEN','ONLINE')
    # 登录令牌只存在隔离业务库旁的验收配置；不能访问正式库。
    setup={'config':config,'contexts':contexts,'token':token,'scope':'REAL_RENDER_MOCK_PROVIDER_ONLY'}
    save(ROOT/'setup.json',setup)
    save(ROOT/'draft_requests.json',{'contexts':contexts,'shared_root':UNC,'duration_us':3000000})
    return setup


def register_drafts():
    setup=read(ROOT/'setup.json');store=PlannerStore(ROOT/'operations.db')
    from startup_render.common import rewrite,normalized
    mapping={normalized(UNC+'\\assets\\synthetic-3s.mp4'):str(ROOT/'assets/synthetic-3s.mp4')}
    for context in setup['contexts']:
        for name in context['draft_names']:
            for path in (ROOT/'drafts'/name).glob('*.json'):
                save(path,rewrite(read(path),mapping))
    pipeline=StartupPipeline(store,batch_root=ROOT/'batches');registration=StartupContentRegistration(pipeline,RenderQueue(ROOT/'render_jobs.db'))
    for context in setup['contexts']:
        manifest={'batch_id':context['batch_id'],'created_at':context['started_at'],'completed_at':datetime.now(timezone.utc).isoformat(),
            'videos':[{'video_index':index,'status':'success','composition_signature':'ACCEPTANCE-'+context['batch_id']+'-'+str(index),
                'draft_name':name,'draft_path':str(ROOT/'drafts'/name),'selected_materials':[]} for index,name in enumerate(context['draft_names'],1)]}
        path=ROOT/'batches'/context['batch_id']/'batch_manifest.json';save(path,manifest)
        registration.complete(setup['token'],context,dict(manifest,manifest_path=str(path)))
    with store.connect() as db:
        pass
    import sqlite3
    with sqlite3.connect(ROOT/'render_jobs.db') as db:
        rows=db.execute('SELECT job_id,payload FROM jobs').fetchall()
        for job_id,raw in rows:
            identity=json.loads(raw);folder=ROOT/'packages'/job_id
            frozen=read(folder/'manifest.json') if (folder/'manifest.json').exists() else package(identity['draft_path'],folder,identity)
            db.execute("UPDATE jobs SET status='QUEUED',payload=? WHERE job_id=? AND status='PENDING'",(json.dumps(frozen,ensure_ascii=False),job_id))
    save(ROOT/'REGISTERED.json',{'render_jobs':len(rows),'real_provider_calls':0})


class AcceptanceControlPlane(ProductionControlPlane):
    def __init__(self):
        self.setup=read(ROOT/'setup.json')
        super().__init__(self.setup['config'],SimpleNamespace(db_path=ROOT/'render_jobs.db'))
        self.store=PlannerStore(ROOT/'operations.db');self.pipeline=StartupPipeline(self.store,batch_root=ROOT/'batches')

    def tick(self):
        # 只有隔离Mock账号；持续返回Mock Provider ONLINE，保持长时GUI测试不受缓存TTL干扰。
        with self.connect(write=True) as db:
            db.execute("UPDATE provider_account_bindings SET provider_last_verified_at=? WHERE business_account_id IN ('ACCEPT-A','ACCEPT-B') AND provider_account_id IN ('MOCK-PROVIDER-A','MOCK-PROVIDER-B')",(datetime.now(timezone.utc).isoformat(),))
        super().tick()
        with self.connect() as db:
            ready=[dict(r) for r in db.execute("SELECT c.*,b.target_account_id FROM startup_contents c JOIN startup_content_bindings b USING(content_id) WHERE c.production_status='READY' AND c.publish_status='NOT_SCHEDULED'")]
        for content in ready:self.create_mock_plan(content)

    def create_mock_plan(self, content):
        from .integration import output_for
        day=(datetime.now(timezone.utc)+timedelta(days=2)).date()
        account=content['target_account_id']
        with self.connect(write=True) as db:
            if db.execute('SELECT 1 FROM publish_plan_items WHERE content_id=?',(content['content_id'],)).fetchone():return
            index=db.execute('SELECT count(*) FROM publish_plan_items WHERE account_id=?',(account,)).fetchone()[0]
            plan=Plan('ACCEPT-'+content['content_id'],day,day,daytime(9+index*2),
                (account,),(content['video_path'],),daily_count=1,title='',description='')
            principal=self.store._principal(db,self.setup['token'])
            slots,rows,profile=self.pipeline._slots(db,self.setup['token'],plan,[content['content_id']],'startup-default')
            check_slots(db,slots)
            accounts=self.store._require_publish_accounts(db,principal,plan.account_ids,'STARTUP')
            output=output_for(db,content['content_id'])
            prep={'files':[{'content_id':content['content_id'],'video_path':content['video_path'],'sha256':output['output_sha256'],
                'cover_path':output['media']['cover_path'],'cover_sha256':output['media']['cover_sha256']}],'scope':'ISOLATED_MOCK_ONLY'}
            db.execute('INSERT INTO provider_production_previews VALUES(?,?,?,?,?,?,?)',(plan.plan_id,principal['employee_id'],json.dumps([content['content_id']]),plan.payload(),'startup-default',json.dumps(prep),datetime.now(timezone.utc).isoformat()))
            self.pipeline._write_simulation(db,principal,plan,slots,rows,profile,'startup-default',accounts)
            db.execute("UPDATE publish_plans SET status='CONFIRMED' WHERE plan_id=?",(plan.plan_id,))
            db.execute('UPDATE publish_plan_items SET test_only=0 WHERE plan_id=?',(plan.plan_id,))
            db.execute("UPDATE startup_job_metadata SET dispatch_mode='CONFIRMED_NOT_DISPATCHED' WHERE source_plan_id=?",(plan.plan_id,))
            enroll_confirmed(db,plan.plan_id)


if __name__=='__main__':
    import sys
    initialize() if sys.argv[-1]=='init' else register_drafts()
    print('ACCEPTANCE_FIXTURE_READY')
