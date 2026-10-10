"""六账号隔离、未来时段和轻量对账；仅临时库与模拟执行器，无真实Provider调用。"""
from datetime import timedelta
import json
import unittest
from unittest.mock import patch

from media_execution.tests import test_execution as media_fixture
from startup_autopilot.tests import test_production as production_fixture
from production_autopilot.account_runtime import pause, allowed, runtime, activate, PAUSED
from production_autopilot.control_tower import ProductionReadinessEvaluator
from production_autopilot.test_control_tower import fixture, set_detail, NOW
from production_autopilot.test_account_recovery import ProvenProbe
from media_execution.control import ControlPlane


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.f=media_fixture.ExecutionTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.c=self.f.control;self.node=self.f.worker
        self.c.set_account('F','OPEN','ONLINE')

    def test_A_job_failure_same_account_future_and_other_five_continue(self):
        self.f.enroll_render(1,'A');self.f.enroll_render(2,'A')
        for index,account in enumerate('BCDEF',3):self.f.enroll_render(index,account)
        def render(job,ctx):
            if job['job_id']=='r1': raise RuntimeError('DRAFT_CORRUPT')
            return self.f.render(job,ctx)
        coordinator=self.f.coordinator(render=render)
        results=[coordinator.run_once() for _ in range(7)]
        self.assertEqual(results[0]['state'],'FAILED_JOB_LEVEL')
        self.assertEqual(sum(r['state']=='COMPLETED' for r in results),6)
        self.assertEqual(len(set(r['job_id'] for r in results)),7)
        self.assertIsNone(self.c.snapshot(self.node)['active'])
        with self.c.connect() as db:
            self.assertTrue(allowed(db,'A'))
            self.assertEqual(db.execute('SELECT domain FROM production_faults').fetchone()[0],'JOB')

    def test_B_account_pause_skips_both_queues_other_five_continue(self):
        self.c.set_account('A','BLOCKED_RISK','ONLINE',reason='ACCOUNT_RISK')
        self.f.enroll_render(1,'A');self.f.enroll_publish(1,'A')
        for index,account in enumerate('BCDEF',2): self.f.enroll_render(index,account)
        results=[self.f.coordinator().run_once() for _ in range(6)]
        self.assertEqual(sum(r['state']=='COMPLETED' for r in results),5)
        self.assertEqual(results[-1]['state'],'IDLE')
        with self.c.connect() as db:self.assertEqual(runtime(db,'A')['status'],PAUSED)
        self.c.set_account('A','OPEN','ONLINE')
        self.assertIsNone(self.c.claim(self.node))  # 登录恢复不代表用户重新授权运行。

    def scheduled(self):
        self.f.seed_output(1);self.f.enroll_publish(1)
        self.f.coordinator().run_once()
        return self.c.row('PUBLISH','p1')

    def test_D_queued_then_account_paused_keeps_entire_job_and_latch(self):
        before=self.scheduled()
        self.c.set_account('A','BLOCKED_RISK','ONLINE',reason='ACCOUNT_RISK')
        self.assertEqual(self.c.row('PUBLISH','p1'),before)
        query=self.c.claim_reconciliation(self.node)
        self.c.record_reconciliation(self.node,query['lease_token'],{
            'state':'SUBMITTED','provider_task_id':before['provider_task_id']})
        self.assertEqual(self.c.row('PUBLISH','p1'),before)

    def test_E_six_hour_platform_wait_never_holds_heavy_slot(self):
        before=self.scheduled()
        for i in range(6):
            self.f.now+=3600
            query=self.c.claim_reconciliation(self.node)
            self.assertIsNone(self.c.snapshot(self.node)['active'])
            self.f.enroll_render(i+2,'B')
            self.assertEqual(self.f.coordinator().run_once()['state'],'COMPLETED')
            with self.assertRaises(PermissionError):self.c.reserve_submit(self.node,query['lease_token'],{})
            self.c.record_reconciliation(self.node,query['lease_token'],{
                'state':'SUBMITTED','provider_task_id':before['provider_task_id']})
        self.assertEqual(self.c.row('PUBLISH','p1'),before)

    def test_query_error_only_schedules_readonly_retry_no_job_failure(self):
        before=self.scheduled();query=self.c.claim_reconciliation(self.node)
        self.c.reconciliation_error(self.node,query['lease_token'],'QUERY_TIMEOUT')
        self.assertEqual(self.c.row('PUBLISH','p1'),before)
        self.f.enroll_render(2,'B');self.assertEqual(self.f.coordinator().run_once()['state'],'COMPLETED')

    def test_legacy_reconcile_recovery_releases_only_lease(self):
        before=self.scheduled()
        with self.c.connect(write=True) as db:
            db.execute("INSERT INTO media_execution_leases VALUES(?,?,?,?,?,?,?,'PUBLISH_RECONCILING')",
                       (self.node,'PUBLISH','p1','old',self.f.now,self.f.now,self.f.now+120))
        self.c.recovery(self.node,executor_quiescent=True)
        self.assertEqual(self.c.row('PUBLISH','p1'),before)
        self.assertIsNone(self.c.snapshot(self.node)['active'])

    def test_F_only_shared_fault_red_account_and_job_yellow(self):
        data=fixture();set_detail(data,status='READY')
        data['account_runtime']=[{'account_id':'a','status':PAUSED}]
        self.assertEqual(ProductionReadinessEvaluator().evaluate(data)['readiness'],'DEGRADED')
        data['health'][0]['received_at']=NOW-100
        r=ProductionReadinessEvaluator().evaluate(data)
        self.assertEqual(r['readiness'],'BLOCKED')
        self.assertTrue(all(x['scope']=='SYSTEM' for x in r['reasons'] if x['blocking']))


class AccountResumeTests(unittest.TestCase):
    def setUp(self):
        self.f=production_fixture.ProductionTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        control=ControlPlane(self.f.store.path);control.migrate()
        control.set_account(self.f.account,'OPEN','ONLINE')
        with self.f.store.connect(write=True) as db:
            db.execute('CREATE TABLE IF NOT EXISTS media_execution_settings(key TEXT PRIMARY KEY,value TEXT)')
            db.execute("INSERT OR REPLACE INTO media_execution_settings VALUES('enabled','true')")

    def test_C_pause_three_hours_reon_only_future_no_debt_no_duplicate(self):
        f=self.f;grant=f.start()
        now=f.now.astimezone(__import__('startup_autopilot.models',fromlist=['SHANGHAI']).SHANGHAI).replace(hour=7,minute=0,second=0,microsecond=0)
        f.production.reserve_daily(grant,now)
        with f.store.connect(write=True) as db:
            before=[dict(r) for r in db.execute('SELECT * FROM autopilot_allocations')]
            pause(db,f.account,'ACCOUNT_VERIFICATION_REQUIRED',now=now.timestamp())
            self.assertTrue(all(r[0]=='CANCELLED_BY_ACCOUNT_PAUSE' for r in db.execute('SELECT state FROM autopilot_allocations')))
        later=now+timedelta(hours=3)
        result=f.production.resume(f.token,f.account,now=later,recovery_probe=ProvenProbe())
        self.assertIn('15:00',result['next_slot'])  # 本LOCAL通道还要求8100秒安全提前量。
        f.production.reserve_daily(grant,later);f.production.reserve_daily(grant,later)
        with f.store.connect() as db:
            rows=[dict(r) for r in db.execute("SELECT * FROM autopilot_allocations WHERE state='PLANNED'")]
            self.assertEqual([r['scheduled_at'][11:16] for r in rows],['15:00','18:00','21:00'])
            self.assertEqual(len({r['scheduled_at'] for r in rows}),len(rows))
            self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0],0)
            self.assertTrue(all(r['local_day']==later.date().isoformat() for r in rows))
        self.assertTrue(f.production.authorization(f.account)['enabled'])

    def test_resume_after_last_slot_reports_next_plan_without_creating_job(self):
        f=self.f;f.start()
        with f.store.connect(write=True) as db: pause(db,f.account,'ACCOUNT_RISK')
        now=f.now.astimezone(__import__('startup_autopilot.models',fromlist=['SHANGHAI']).SHANGHAI).replace(hour=23)
        result=f.production.resume(f.token,f.account,now=now,recovery_probe=ProvenProbe())
        self.assertIsNone(result['next_slot']);self.assertIn('今日无剩余',result['message'])
        with f.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM autopilot_allocations').fetchone()[0],0)

    def test_resume_check_failure_keeps_paused_and_creates_nothing(self):
        f=self.f;f.start()
        with f.store.connect(write=True) as db: pause(db,f.account,'ACCOUNT_RISK')
        result=f.production.resume(f.token,f.account,recovery_probe=ProvenProbe('STILL_BLOCKED'))
        self.assertEqual(result['state'],'STILL_BLOCKED');self.assertFalse(result['resumed'])
        self.assertEqual(f.production.account_runtime(f.account)['status'],PAUSED)
        with f.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM autopilot_allocations').fetchone()[0],0)

    def test_user_off_is_not_overridden_by_account_fault(self):
        f=self.f;f.start()
        f.production.control(f.token,f.account,'pause')
        with f.store.connect(write=True) as db:
            pause(db,f.account,'ACCOUNT_RISK')
            self.assertEqual(runtime(db,f.account)['status'],'OFF')
            self.assertFalse(allowed(db,f.account))
        self.assertFalse(f.production.authorization(f.account)['enabled'])

    def test_account_overview_uses_runtime_pause_not_retained_authorization(self):
        from yixiaoer_adapter.account_sync_ui import overview_rows
        f=self.f;f.start()
        with f.store.connect(write=True) as db:
            db.execute('CREATE TABLE IF NOT EXISTS business_account_registry(business_account_id TEXT,raw_account_json TEXT)')
            pause(db,f.account,'ACCOUNT_RISK')
        accounts=[{'account_id':f.account,'display_name':'测试账号','provider_binding_status':'ONLINE'}]
        row=overview_rows(f.production,accounts)[f.account]
        self.assertFalse(row['running'])
        self.assertTrue(row['attention'])
        self.assertIn('暂停，需要处理',row['label'])
        self.assertTrue(row['runtime_card']['paused'])
        self.assertTrue(f.production.authorization(f.account)['enabled'])


if __name__=='__main__':unittest.main()
