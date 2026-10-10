"""上线恢复回归：真实服务均为fixture，不执行Render/上传/发布。"""
import json
from contextlib import closing, nullcontext
import sqlite3
import unittest
from unittest.mock import patch
from startup_autopilot.tests import test_production as fixtures
from startup_render import test_lan_resident as lan_fixtures
from production_autopilot.preflight import run
from production_autopilot.reconciliation import ReadOnlyAdapter,repair_disabled_accounts


class GoLiveTests(unittest.TestCase):
    def fixture(self):
        base=fixtures.ProductionTests();base.setUp();self.addCleanup(base.doCleanups);return base

    def test_preflight_checks_services_and_capacity_without_enabling(self):
        f=self.fixture();f.start();f.production.control(f.token,f.account,'pause')
        worker,cli,_=f.make_worker()
        infra={'render_ready':True,'render_reason':'已就绪','publisher_ready':True}
        ready=run(f.production,f.token,f.account,infra=infra)
        self.assertTrue(ready['ready'],ready['missing'])
        blocked=run(f.production,f.token,f.account,infra=dict(infra,render_ready=False,render_reason='工作站需要核验'))
        self.assertFalse(blocked['ready']);self.assertIn('工作站需要核验',blocked['missing'])
        self.assertFalse(f.production.authorization(f.account)['enabled']);self.assertEqual(cli.submits(),[])

    def test_preflight_missing_template_and_target_are_actionable(self):
        f=self.fixture();worker,cli,_=f.make_worker()
        infra={'render_ready':True,'render_reason':'已就绪','publisher_ready':True}
        with patch.object(f.production.builder,'active',side_effect=PermissionError('UNCONFIRMED')):
            report=run(f.production,f.token,f.account,infra=infra)
        self.assertFalse(report['ready']);self.assertIn('请预览并保存视频模板',report['missing'])
        self.assertEqual(cli.submits(),[])

    def test_start_dialog_disables_confirmation_when_render_not_ready(self):
        from startup_autopilot.workbench_autopilot import start_dialog
        f=self.fixture();f.start();f.production.control(f.token,f.account,'pause')
        profile=f.production.shadows.load(f.production.actor(f.token),f.account)[1]
        buttons=[]
        class View:
            def dialog(self,title):return lambda function:function
            def spinner(self,text):return nullcontext()
            def write(self,text):pass
            def caption(self,text):pass
            def warning(self,text):pass
            def success(self,text):pass
            def button(self,label,**kwargs):buttons.append(kwargs);return False
        infra={'render_ready':False,'render_reason':'渲染节点需要处理','publisher_ready':True}
        with patch('production_autopilot.preflight.infrastructure',return_value=infra):
            start_dialog(View(),f.production,f.token,{'account_id':f.account,'display_name':'隔离测试账号'},profile)
        self.assertTrue(buttons[0]['disabled'])
        self.assertFalse(f.production.authorization(f.account)['enabled'])

    def test_read_only_adapter_refuses_writes(self):
        adapter=object.__new__(ReadOnlyAdapter)
        for args in (['publish','video'],['upload','file'],['draft','save']):
            with self.assertRaisesRegex(PermissionError,'READ_ONLY'):adapter.call(args)

    def test_repair_legacy_failure_changes_state_only_and_stays_disabled(self):
        f=self.fixture();worker,cli,row=f.ready_job()
        claim=worker.provider_store.claim('ISOLATED_AUTOPILOT',[row['plan_id']]);worker.adapter.create_publish_job(*claim)
        worker.adapter.reconcile_publish_result(row['job_id'])
        f.production.attention(f.account,'发布需要处理：FAILED')
        old=f.production.authorization(f.account)
        repaired=repair_disabled_accounts(f.production,[{'account_id':f.account}])
        self.assertEqual(repaired,[f.account]);new=f.production.authorization(f.account)
        self.assertEqual(new['status'],'PAUSED');self.assertFalse(new['enabled'])
        for key in ('config_hash','template_hash','autopilot_confirmed_at','provider_account_id'):self.assertEqual(new[key],old[key])
        self.assertEqual(len(cli.submits()),1)
        worker.reconcile(row)
        self.assertEqual(f.production.authorization(f.account)['status'],'PAUSED')

    def test_paused_account_cannot_claim_queued_render_then_explicit_enable_can(self):
        f=lan_fixtures.RegistryTests();f.setUp();self.addCleanup(f.tearDown)
        path=f.root/'operations.fixture.db';f.config['operations_db']=str(path)
        with closing(sqlite3.connect(path)) as db:
            db.executescript('CREATE TABLE autopilot_allocations(content_id TEXT,account_id TEXT,state TEXT);CREATE TABLE autopilot_authorizations(account_id TEXT,enabled INTEGER,status TEXT);')
            db.execute("INSERT INTO autopilot_allocations VALUES('CONTENT-ONE','ACCOUNT-A','RENDER_PENDING')")
            db.execute("INSERT INTO autopilot_authorizations VALUES('ACCOUNT-A',0,'PAUSED')")
            db.commit()
        self.assertIsNone(f.claim())
        with f.broker.connect() as db:self.assertEqual(db.execute('SELECT status FROM jobs').fetchone()[0],'QUEUED')
        with closing(sqlite3.connect(path)) as db:
            db.execute("UPDATE autopilot_authorizations SET enabled=1,status='COLD_START'");db.commit()
        self.assertIsNotNone(f.claim())

    def test_confirmed_old_failure_cannot_reopen_paused_account(self):
        f=self.fixture();worker,cli,row=f.ready_job()
        claim=worker.provider_store.claim('ISOLATED_AUTOPILOT',[row['plan_id']]);worker.adapter.create_publish_job(*claim)
        worker.adapter.reconcile_publish_result(row['job_id'])
        native=worker.provider_store.row(row['job_id']);raw=json.loads(native['provider_raw_status'])
        raw['tasks'][0]['stageStatus']='failed'
        raw['tasks'][0]['errorMessage']='历史作品不存在'
        with f.production.planner.connect(write=True) as db:
            db.execute("UPDATE provider_publish_jobs SET state='FAILED',provider_raw_status=? WHERE job_id=?",(json.dumps(raw),row['job_id']))
        f.production.control(f.token,f.account,'pause')
        worker.reconcile(row)
        self.assertEqual(f.production.authorization(f.account)['status'],'PAUSED')
        self.assertFalse(f.production.authorization(f.account)['enabled'])
        self.assertEqual(len(cli.submits()),1)


if __name__=='__main__':unittest.main()
