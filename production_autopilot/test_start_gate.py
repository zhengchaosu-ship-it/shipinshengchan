"""启动门禁回归：独立数据库和模拟成片，不调用真实Provider。"""
from contextlib import nullcontext
from dataclasses import replace
from datetime import timedelta
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from startup_autopilot.tests import test_production as fixtures
from startup_autopilot.production import utcnow
from media_execution.production import ProductionControlPlane
from production_autopilot.preflight import infrastructure,run


class StartGateTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ProductionTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        f=self.f
        self.worker,self.cli,self.job=f.ready_job()
        f.production.control(f.token,f.account,'pause')
        self.control=ProductionControlPlane({'operations_db':str(f.store.path),'worker_ids':['WORKER-2060S-01']},
            SimpleNamespace(db_path=self.worker.registration.queue.path))
        self.control.migrate()
        self.control.set_account(f.account,'OPEN','ONLINE')
        self.health={'protocol':'MEDIA_EXECUTION_V1','status':'READY','yixiaoer_local_ready':True,
            'network':{'state':'ONLINE'},'render':{'render_capability':'READY','process_health':'READY','export_automation_health':'READY'}}
        self.control.report_worker('WORKER-2060S-01',self.health)
        with f.store.connect(write=True) as db:
            db.execute("UPDATE media_execution_settings SET value='DISABLED' WHERE key='server_provider_upload'")

    def report(self,**kwargs):
        return run(self.f.production,self.f.token,self.f.account,capacity=False,**kwargs)

    def incident(self,*,state='OPEN',category='ACCOUNT_AUTH'):
        old=(utcnow()-timedelta(minutes=10)).isoformat()
        with self.f.store.connect(write=True) as db:
            db.execute('INSERT INTO production_incidents VALUES(?,?,?,?,?,?,?,?,?,NULL)',
                ('OLD-RISK',self.f.account,category,'ACCOUNT','ACCOUNT_RISK 账号需要验证',state,1,old,old))

    def recover(self,*,errors=None):
        at=(utcnow()-timedelta(minutes=1)).isoformat()
        with self.f.store.connect(write=True) as db:
            db.execute("INSERT INTO production_recovery_requests VALUES(?,?,?,?,'CHECKED',?,?)",
                ('RECOVERY',self.f.account,'TEST',at,at,json.dumps({'gate_recovered':True,'resumed':False,'errors':errors or []})))

    def test_disabled_server_uses_live_2060_without_starting_jobs(self):
        with patch.object(self.f.production,'start',side_effect=AssertionError('NO_ENABLE')),patch.object(self.f.production,'reserve_daily',side_effect=AssertionError('NO_JOBS')):
            result=self.report()
        self.assertTrue(result['eligible'],result['blocking_reasons'])
        self.assertEqual(result['blocking_reasons'],[])
        probe=infrastructure(planner=self.f.store)
        self.assertTrue(probe['publisher_ready']);self.assertEqual(probe['server_provider_upload'],'DISABLED')
        self.assertFalse(self.f.production.authorization(self.f.account)['enabled']);self.assertEqual(self.cli.submits(),[])

    def test_current_infrastructure_failures_block(self):
        for change,code in [({'status':'OFFLINE'},'WORKER_NOT_READY'),({'yixiaoer_local_ready':False},'LOCAL_YIXIAOER_NOT_READY')]:
            with self.subTest(change=change):
                self.control.report_worker('WORKER-2060S-01',dict(self.health,**change))
                self.assertIn(code,[r['code'] for r in self.report()['blocking_reasons']])
        self.control.report_worker('WORKER-2060S-01',self.health)
        self.control.set_infrastructure('WORKER-2060S-01','OFFLINE')
        self.assertIn('PUBLISHER_INFRASTRUCTURE_OFFLINE',[r['code'] for r in self.report()['blocking_reasons']])
        self.control.report_worker('WORKER-2060S-01',self.health)
        with self.f.store.connect(write=True) as db:db.execute('UPDATE media_execution_worker_health SET received_at=received_at-180')
        self.assertIn('WORKER_NOT_READY',[r['code'] for r in self.report()['blocking_reasons']])

    def test_wrong_execution_node_blocks(self):
        with self.f.store.connect(write=True) as db:db.execute("UPDATE media_execution_settings SET value='SERVER' WHERE key='publisher_execution_node'")
        self.assertIn('PUBLISHER_EXECUTION_NODE_INVALID',[r['code'] for r in self.report()['blocking_reasons']])

    def test_current_account_gate_and_offline_provider_block(self):
        for gate,status,code in [('BLOCKED_RISK','ONLINE','ACCOUNT_PUBLISH_GATE_NOT_OPEN'),('OPEN','OFFLINE','PROVIDER_ACCOUNT_NOT_ONLINE')]:
            with self.subTest(gate=gate,status=status):
                self.control.set_account(self.f.account,gate,status)
                self.assertIn(code,[r['code'] for r in self.report()['blocking_reasons']])
        self.control.set_account(self.f.account,'OPEN','ONLINE')
        with self.f.store.connect(write=True) as db:
            db.execute("UPDATE provider_account_bindings SET provider_last_verified_at='2000-01-01T00:00:00+00:00'")
        self.assertIn('PROVIDER_ACCOUNT_NOT_ONLINE_OR_MAPPING_INVALID',[r['code'] for r in self.report()['blocking_reasons']])

    def test_recovery_without_resuming_resolves_old_risk_read_only(self):
        self.incident();self.recover()
        with self.f.store.connect(write=True) as db:
            db.execute("UPDATE provider_publish_jobs SET state='FAILED',submit_attempt_count=1 WHERE job_id=?",(self.job['job_id'],))
            old=dict(db.execute('SELECT * FROM provider_publish_jobs WHERE job_id=?',(self.job['job_id'],)).fetchone())
        result=self.report();self.assertTrue(result['eligible'],result['blocking_reasons'])
        self.assertEqual({a['classification'] for a in result['anomalies']},{'RESOLVED','HISTORICAL'})
        with self.f.store.connect() as db:
            self.assertEqual(old,dict(db.execute('SELECT * FROM provider_publish_jobs WHERE job_id=?',(self.job['job_id'],)).fetchone()))
            self.assertEqual(db.execute('SELECT state FROM production_incidents').fetchone()[0],'OPEN')
        self.assertFalse(self.f.production.authorization(self.f.account)['enabled'])

    def test_new_or_unverified_risk_blocks_even_if_gate_open(self):
        self.incident()
        self.assertIn('ACTIVE_ACCOUNT_RISK',[r['code'] for r in self.report()['blocking_reasons']])
        self.recover(errors=['verification failed'])
        self.assertFalse(self.report()['eligible'])
        with self.f.store.connect(write=True) as db:
            db.execute("UPDATE production_recovery_requests SET result_json=?",(json.dumps({'gate_recovered':True,'errors':[]}),))
            db.execute('UPDATE production_incidents SET last_seen_at=?',(utcnow().isoformat(),))
        self.assertIn('ACTIVE_ACCOUNT_RISK',[r['code'] for r in self.report()['blocking_reasons']])

    def test_provider_risk_codes_block_without_chinese_message(self):
        self.incident(category='OTHER')
        for code in ('ACCOUNT_RISK','AUTH_REQUIRED','SMS_REQUIRED','MANUAL_PUBLISH_REQUIRED','CREATOR_CENTER_VERIFICATION_REQUIRED','MANUAL_ACTION_REQUIRED'):
            with self.subTest(code=code):
                with self.f.store.connect(write=True) as db:db.execute('UPDATE production_incidents SET reason=?',(code,))
                self.assertIn('ACTIVE_ACCOUNT_RISK',[r['code'] for r in self.report()['blocking_reasons']])

    def test_resolved_incident_and_other_account_risk_do_not_block(self):
        self.incident(state='RESOLVED')
        self.control.set_account('ANOTHER-ACCOUNT','BLOCKED_RISK','ONLINE')
        self.assertTrue(self.report()['eligible'])

    def test_missing_template_times_and_materials_still_block(self):
        f=self.f
        with patch.object(f.production.builder,'active',side_effect=ValueError('UNCONFIGURED')):
            self.assertFalse(self.report()['eligible'])
        profile=replace(f.production.shadows.load(f.production.actor(f.token),f.account)[1],publish_times=())
        self.assertFalse(self.report(profile=profile)['eligible'])
        with patch.object(f.production.builder.catalog,'refresh',return_value=[]):
            result=run(f.production,f.token,f.account)
        self.assertIn('PRODUCTION_MATERIAL_INVALID',[r['code'] for r in result['blocking_reasons']])

    def test_scheduled_queue_consumes_budget_not_start_gate(self):
        f=self.f
        with f.store.connect(write=True) as db:
            db.execute("UPDATE provider_publish_jobs SET state='SCHEDULED_QUEUED',submit_attempt_count=1 WHERE job_id=?",(self.job['job_id'],))
            # 构造完整的已提交事实；setUp中用户暂停已取消了尚未开始的预留。
            db.execute("UPDATE publish_jobs SET status='SCHEDULED_QUEUED' WHERE job_id=?",(self.job['job_id'],))
            db.execute("UPDATE autopilot_allocations SET state='SCHEDULED_QUEUED' WHERE job_id=?",(self.job['job_id'],))
        profile=replace(f.production.shadows.load(f.production.actor(f.token),f.account)[1],daily_publish_limit=5,
            publish_times=('09:00','12:00','15:00','18:00','21:00'))
        result=run(f.production,f.token,f.account,profile=profile)
        self.assertTrue(result['eligible'],result['blocking_reasons'])
        self.assertEqual(result['capacity']['existing_occupied'],1)
        self.assertEqual(result['capacity']['required'],4)
        self.assertEqual(result['capacity']['daily'],4)
        self.assertFalse(any(a['code']=='SCHEDULED_QUEUED' for a in result['anomalies']))
        self.assertEqual(self.cli.submits(),[])

    def test_dialog_shows_ready_but_does_not_start_until_click(self):
        from startup_autopilot.workbench_autopilot import start_dialog
        f=self.f;messages=[];buttons=[]
        class View:
            def dialog(self,title):return lambda function:function
            def spinner(self,text):return nullcontext()
            def write(self,text):messages.append(text)
            caption=write;warning=write;success=write
            def button(self,label,**kwargs):buttons.append((label,kwargs));return False
        profile=replace(f.production.shadows.load(f.production.actor(f.token),f.account)[1],daily_publish_limit=5,
            publish_times=('09:08','12:23','15:26','18:18','21:06'))
        with patch.object(f.production,'start',side_effect=AssertionError('NO_ENABLE')):
            start_dialog(View(),f.production,f.token,{'account_id':f.account,'display_name':'夏禾'},profile)
        self.assertIn('可以开始正式托管',messages)
        self.assertIn('每天最多5条；北京时间：09:08, 12:23, 15:26, 18:18, 21:06',messages)
        self.assertEqual(buttons[0][0],'开始正式托管');self.assertFalse(buttons[0][1]['disabled'])
        self.assertFalse(f.production.authorization(f.account)['enabled'])


if __name__=='__main__':unittest.main()
