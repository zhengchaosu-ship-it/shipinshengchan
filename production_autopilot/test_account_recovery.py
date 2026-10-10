"""只用隔离库和Provider替身；真实发布/上传/历史任务变更为测试失败。"""
import copy
import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from startup_autopilot.tests import test_production as fixtures
from media_execution.control import ControlPlane
from .account_recovery import AccountRecoveryProbe,evaluate,forced_check,latest,UNAVAILABLE
from .account_runtime import runtime,allowed


def proof(provider_id='PROVIDER-FIXTURE-NEW',state='RECOVERED'):
    signals={'account_exists':True,'online':True,'auth_valid':True,'verification_required':False,
             'publish_allowed':True,'capability_source':'ISOLATED_PROVIDER_CAPABILITY_FIXTURE'}
    if state=='UNKNOWN':signals['verification_required']=None
    if state=='STILL_BLOCKED':signals['verification_required']=True
    result,code,message=evaluate(signals)
    return {'state':result,'reason_code':code,'human_message':message,
            'account':{'id':provider_id,'status':1,'platformName':'抖音','platformAccountName':'测试账号'},
            'provider_raw_status':{},'probe_evidence':{'signals':signals}}


class ProvenProbe:
    def __init__(self,state='RECOVERED'):self.state=state
    def check(self,provider_id):return proof(provider_id,self.state)


class ProbeTests(unittest.TestCase):
    def adapter(self,**changes):
        account={'id':'a','status':1,'isFreeze':False,'isLock':False,'isOperate':True,'platformAccountName':'测试'}|changes
        calls=[]
        def call(args,**kwargs):
            self.assertIn(args[:2],[['accounts','list'],['query','account-overviews']])
            calls.append(args)
            return {'ok':True,'version':'3.2.26','data':[account] if args[0]=='accounts' else {'data':[{'id':'a','status':1,'worksCount':10}]}}
        return SimpleNamespace(call=call,clean=lambda x:x,calls=calls)

    def test_online_unlocked_operable_and_statistics_do_not_prove_recovery(self):
        adapter=self.adapter();p=AccountRecoveryProbe(adapter)
        for _ in range(2):
            result=p.check('a')
            self.assertEqual(result['state'],'UNKNOWN');self.assertEqual(result['reason_code'],UNAVAILABLE)
            self.assertEqual(result['probe_evidence']['submit_calls'],0)
        self.assertEqual(len(adapter.calls),4)  # 每次真正查询，不复用缓存。

    def test_current_provider_offline_freeze_lock_and_permission_are_blocked(self):
        for change in ({'status':0},{'isFreeze':True},{'isLock':True},{'isOperate':False}):
            with self.subTest(change=change):self.assertEqual(AccountRecoveryProbe(self.adapter(**change)).check('a')['state'],'STILL_BLOCKED')

    def test_missing_and_query_failure_distinguished(self):
        self.assertEqual(AccountRecoveryProbe(self.adapter()).check('missing')['state'],'STILL_BLOCKED')
        adapter=self.adapter();adapter.call=lambda *a,**k:(_ for _ in ()).throw(TimeoutError())
        self.assertEqual(AccountRecoveryProbe(adapter).check('a')['reason_code'],'RECOVERY_QUERY_FAILED')


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ProductionTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        f=self.f;f.start()
        self.control=ControlPlane(f.store.path);self.control.migrate()
        with f.store.connect(write=True) as db:
            db.execute('CREATE TABLE IF NOT EXISTS media_execution_settings(key TEXT PRIMARY KEY,value TEXT)')
            db.execute("INSERT OR REPLACE INTO media_execution_settings VALUES('enabled','true')")
        self.control.set_account(f.account,'BLOCKED_RISK','ONLINE',reason='ACCOUNT_VERIFICATION_REQUIRED')

    def check(self,probe=None,**kwargs):
        f=self.f
        return forced_check(f.production,f.token,f.account,probe=probe or ProvenProbe(),**kwargs)

    def test_unknown_stays_paused_and_can_check_again_without_jobs(self):
        f=self.f
        a=self.check(ProvenProbe('UNKNOWN'),resume=True);b=self.check(ProvenProbe('UNKNOWN'),resume=True)
        self.assertNotEqual(a['check_id'],b['check_id'])
        with f.store.connect() as db:
            self.assertFalse(allowed(db,f.account))
            self.assertEqual(db.execute('SELECT gate FROM media_account_publish_gates').fetchone()[0],'BLOCKED_RISK')
            self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0],0)
            self.assertEqual(latest(db,f.account)['state'],'UNKNOWN')

    def test_ui_refresh_is_readonly_and_click_forces_fresh_probe(self):
        from streamlit.testing.v1 import AppTest
        f=self.f
        self.check(ProvenProbe('UNKNOWN'))
        def page(service,token,account):
            import streamlit as st
            from production_autopilot.account_recovery_ui import recovery_controls
            recovery_controls(st,service,token,account)
        with patch('production_autopilot.account_recovery.default_probe',return_value=ProvenProbe('UNKNOWN')) as factory:
            app=AppTest.from_function(page,args=(f.production,f.token,f.account)).run()
            self.assertEqual(len(app.exception),0);factory.assert_not_called()
            self.assertIn('平台未提供明确',app.info[0].value)
            app.button[0].click().run()
            self.assertEqual(len(app.exception),0);factory.assert_called_once()
        with f.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM account_recovery_checks').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0],0)

    def test_explicit_recovery_activates_future_only_and_preserves_historical_rows(self):
        f=self.f
        # 恢复只改变授权和当前门，不能创建新任务。
        with f.store.connect() as db:
            before={t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in ('publish_jobs','provider_publish_jobs')}
        now=f.now.astimezone(__import__('startup_autopilot.models',fromlist=['SHANGHAI']).SHANGHAI).replace(hour=11,minute=45)
        result=self.check(resume=True,now=now)
        self.assertTrue(result['resumed']);self.assertIn('15:00',result['next_slot'])
        with f.store.connect() as db:
            self.assertEqual(runtime(db,f.account)['status'],'ACTIVE')
            self.assertEqual(db.execute('SELECT gate FROM media_account_publish_gates').fetchone()[0],'OPEN')
            self.assertEqual(before,{t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in before})
            self.assertEqual(db.execute('SELECT count(*) FROM autopilot_allocations').fetchone()[0],0)

    def test_query_only_recovery_does_not_enable_paused_runtime(self):
        f=self.f;result=self.check()
        self.assertEqual(result['state'],'RECOVERED');self.assertFalse(result['resumed'])
        with f.store.connect() as db:self.assertFalse(allowed(db,f.account))

    def test_concurrent_user_off_wins_and_network_does_not_hold_write_lock(self):
        f=self.f
        def check(provider):
            # 网络回调期间能另开写事务；模拟用户关闭，不能被迟到结果覆盖。
            f.production.control(f.token,f.account,'pause')
            return proof(provider)
        result=self.check(SimpleNamespace(check=check),resume=True)
        self.assertEqual(result['reason_code'],'ACCOUNT_CHANGED_DURING_RECOVERY')
        self.assertFalse(f.production.authorization(f.account)['enabled'])
        with f.store.connect() as db:self.assertEqual(runtime(db,f.account)['status'],'OFF')

    def test_no_proof_cannot_forge_recovered(self):
        value=proof();value['probe_evidence']={}
        result=self.check(SimpleNamespace(check=lambda p:copy.deepcopy(value)),resume=True)
        self.assertEqual(result['state'],'UNKNOWN')

    def test_other_account_can_write_during_probe_and_is_unchanged_after(self):
        self.control.set_account('OTHER','OPEN','ONLINE')
        def check(provider):
            with self.f.store.connect(write=True) as db:
                db.execute("UPDATE media_account_publish_gates SET checked_at=123 WHERE business_account_id='OTHER'")
            return proof(provider,'UNKNOWN')
        self.check(SimpleNamespace(check=check),resume=True)
        with self.f.store.connect() as db:
            row=db.execute("SELECT * FROM media_account_publish_gates WHERE business_account_id='OTHER'").fetchone()
            self.assertEqual(row['gate'],'OPEN');self.assertEqual(row['checked_at'],123)
            self.assertTrue(allowed(db,'OTHER'))

    def test_same_account_concurrent_check_does_not_call_provider_twice(self):
        def check(provider):
            nested=self.check(SimpleNamespace(check=lambda p:self.fail('DUPLICATE_PROBE')))
            self.assertEqual(nested['state'],'CHECKING')
            return proof(provider,'UNKNOWN')
        self.assertEqual(self.check(SimpleNamespace(check=check))['state'],'UNKNOWN')

    def test_current_recovery_supersedes_old_risk_incident_without_rewriting_history(self):
        f=self.f
        from production_autopilot.reliability import ReliabilityStore
        from production_autopilot.preflight import account_anomalies
        store=ReliabilityStore(f.production);store.migrate();store.incident(f.account,'ACCOUNT_RISK','OLD_RISK')
        with f.store.connect() as db:old=[tuple(r) for r in db.execute('SELECT * FROM production_incidents')]
        self.check(resume=True)
        with f.store.connect() as db:
            gate=dict(db.execute('SELECT * FROM media_account_publish_gates').fetchone())
            self.assertFalse(any(r['blocks_start'] for r in account_anomalies(db,f.account,gate)))
            self.assertEqual(old,[tuple(r) for r in db.execute('SELECT * FROM production_incidents')])


class HistoricalTests(unittest.TestCase):
    def test_failed_queued_and_published_rows_and_submit_latch_are_immutable(self):
        f=fixtures.ProductionTests();f.setUp();self.addCleanup(f.doCleanups)
        worker,cli,row=f.ready_job()  # 临时库、MockCLI，不调用真实Provider。
        control=ControlPlane(f.store.path);control.migrate()
        with f.store.connect(write=True) as db:
            db.execute('CREATE TABLE IF NOT EXISTS media_execution_settings(key TEXT PRIMARY KEY,value TEXT)')
            db.execute("INSERT OR REPLACE INTO media_execution_settings VALUES('enabled','true')")
        for state in ('FAILED','SCHEDULED_QUEUED','PUBLISHED'):
            with self.subTest(state=state):
                with f.store.connect(write=True) as db:
                    db.execute('UPDATE publish_jobs SET status=?',(state,))
                    db.execute('UPDATE provider_publish_jobs SET state=?,submit_attempt_count=1,provider_task_id=?',(state,'IMMUTABLE_TASK'))
                    before={t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in ('publish_jobs','provider_publish_jobs')}
                control.set_account(f.account,'BLOCKED_RISK','ONLINE',reason='ACCOUNT_VERIFICATION_REQUIRED')
                result=forced_check(f.production,f.token,f.account,resume=True,probe=ProvenProbe())
                self.assertTrue(result['resumed'])
                with f.store.connect() as db:
                    self.assertEqual(before,{t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in before})
        self.assertEqual(cli.submits(),[])


if __name__=='__main__':unittest.main()
