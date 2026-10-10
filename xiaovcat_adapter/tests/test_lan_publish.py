"""LAN仓库/本机互斥回归，仅隔离库/Mock，不操作2060S或生产UI。"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'startup_pipeline'/'tests'))
import test_production_dispatch as fixtures

from xiaovcat_adapter import lan_publish_server as api
from xiaovcat_adapter import lan_publish_worker as local
from xiaovcat_adapter.desktop_ui_lane import desktop_ui_lane


class LanRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.base=fixtures.ProductionDispatchTests();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.f=self.base.f;self.job=self.base.jobs[0]
        self.stack=[]
        for key,value in [('JOB_ID',self.job),('PLAN_ID',self.base.plan_id),('check_policy',lambda p:p)]:
            p=patch.object(api,key,value);p.start();self.addCleanup(p.stop)
        switch=self.f.root/'adapter.json';switch.write_text(json.dumps({'real_publish_enabled':False}),'utf-8')
        self.repo=api.Repository(dict(runtime_dir=str(self.f.root/'api'),operations_db=str(self.f.store.path),
                adapter_config=str(switch),job3_video_unc=r'\\fixture\RenderOutput\fixture.mp4'),dispatcher=self.base.d)
    def call(self,route,**value):
        return self.repo.handle('/publish/'+route,dict(worker_id=api.WORKER_ID,job_id=self.job,**value))
    def claim(self):return self.call('claim',user_confirmation=api.USER_CONFIRMATION)

    def test_data_read_no_claim_no_business_write(self):
        data=self.call('jobs');self.assertEqual(len(data['jobs']),1);self.assertEqual(data['submit_attempt_count'],0)
        with self.f.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM state_events').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT state FROM startup_production_dispatch WHERE job_id=?',(self.job,)).fetchone()[0],'QUEUED')

    def test_foreign_worker_rejected(self):
        with self.assertRaisesRegex(PermissionError,'WORKER_ID_MISMATCH'):
            self.repo.handle('/publish/jobs',{'worker_id':'other'})

    def test_real_claim_requires_explicit_user_entry(self):
        with self.assertRaisesRegex(PermissionError,'USER_ONE_SHOT'):self.call('claim')

    def test_expired_snapshot_no_claim(self):
        with self.f.store.connect(write=True) as db:db.execute("UPDATE xiaovcat_accounts SET last_synced_at='2020-01-01T00:00:00+00:00'")
        with self.assertRaisesRegex(PermissionError,'SNAPSHOT_EXPIRED'):self.claim()

    def test_reserve_committed_before_ack_at_most_once(self):
        claimed=self.claim();nonce=claimed['claim_token']
        result=self.call('reserve',claim_token=nonce)
        self.assertEqual(result,{'attempt_committed':True,'submit_attempt_count':1})
        with self.f.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM state_events WHERE job_id=? AND step='V04_FINAL_SUBMIT_RESERVED'",(self.job,)).fetchone()[0],1)
        with self.assertRaisesRegex(PermissionError,'NOT_ARMED'):self.call('reserve',claim_token=nonce)

    def test_server_restart_cannot_reissue_submit_permission(self):
        claimed=self.claim();self.repo.capabilities.clear()
        with self.assertRaisesRegex(PermissionError,'NOT_ARMED'):self.call('reserve',claim_token=claimed['claim_token'])

    def test_foreign_job_never_accepted(self):
        with self.assertRaisesRegex(PermissionError,'JOB3_ONLY'):
            self.repo.handle('/publish/claim',dict(worker_id=api.WORKER_ID,job_id=self.base.jobs[1],user_confirmation=api.USER_CONFIRMATION))

    def test_nonce_cannot_be_forged(self):
        self.claim()
        with self.assertRaisesRegex(PermissionError,'CLAIM_REQUIRED'):self.call('guard',claim_token='wrong')

    def test_dry_verified_does_not_create_attempt(self):
        policy=self.call('context')
        self.call('dry-verified',proof=dict(policy,status='READY_FOR_SINGLE_SUBMIT',all_checks_passed=True))
        with self.f.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM state_events').fetchone()[0],0)

    def test_duplicate_claim_never_dispatches_again(self):
        self.claim()
        with self.assertRaises(PermissionError):self.claim()
        with self.f.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0],3)

    def test_success_original_job_preserves_other_jobs(self):
        claimed=self.claim();nonce=claimed['claim_token'];self.call('reserve',claim_token=nonce)
        proof=dict(verified=True,job_id=self.job,content_id=claimed['policy']['content_id'],account_id='A1',
                   scheduled_at=claimed['policy']['scheduled_at'],task_status='已同步',final_submit_invocations=1)
        self.call('result',claim_token=nonce,proof=proof)
        with self.f.store.connect() as db:
            self.assertEqual(db.execute('SELECT status FROM publish_jobs WHERE job_id=?',(self.job,)).fetchone()[0],'SCHEDULED_QUEUED')
            self.assertEqual(db.execute("SELECT count(*) FROM startup_production_dispatch WHERE state='QUEUED'").fetchone()[0],2)

    def test_uncertain_attempt_remains_one_and_not_published(self):
        claimed=self.claim();nonce=claimed['claim_token'];self.call('reserve',claim_token=nonce)
        self.call('result',claim_token=nonce,proof={'verified':False})
        with self.f.store.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM startup_production_dispatch WHERE job_id=?',(self.job,)).fetchone()[0],'SUBMIT_RESULT_UNCERTAIN')
        with self.assertRaises(PermissionError):self.claim()


class LaneTests(unittest.TestCase):
    def kernel(self,result):
        kernel=Mock();kernel.CreateMutexW.return_value=123;kernel.WaitForSingleObject.side_effect=result
        return kernel
    def test_render_and_publish_share_same_name(self):
        from xiaovcat_adapter.lan_publish_contract import DESKTOP_UI_LANE
        from xiaovcat_adapter.desktop_ui_lane import NAME
        self.assertEqual(NAME,DESKTOP_UI_LANE)
    def test_busy_never_enters_gui(self):
        kernel=self.kernel([258]);wait=Mock();action=Mock()
        with patch('ctypes.WinDLL',return_value=kernel),self.assertRaisesRegex(RuntimeError,'WAITING_UI_LANE'):
            with desktop_ui_lane(waiting=wait):action()
        wait.assert_called_once();action.assert_not_called();kernel.ReleaseMutex.assert_not_called()
    def test_free_lane_released_after_error(self):
        kernel=self.kernel([0])
        with patch('ctypes.WinDLL',return_value=kernel),self.assertRaises(ValueError):
            with desktop_ui_lane():raise ValueError('fixture')
        kernel.ReleaseMutex.assert_called_once_with(123)
    def test_render_waits_for_publish_without_starting_gui_early(self):
        kernel=self.kernel([258,0]);events=[]
        with patch('ctypes.WinDLL',return_value=kernel),patch('time.sleep'):
            with desktop_ui_lane(wait_seconds=5,waiting=lambda:events.append('WAITING')):events.append('GUI')
        self.assertEqual(events,['WAITING','GUI'])
    def test_abandoned_lane_stops_without_gui(self):
        kernel=self.kernel([128]);action=Mock()
        with patch('ctypes.WinDLL',return_value=kernel),self.assertRaisesRegex(RuntimeError,'ABANDONED'):
            with desktop_ui_lane():action()
        action.assert_not_called()


class RemoteStoreTests(unittest.TestCase):
    def test_real_entry_without_real_dry_receipt_never_touches_desktop(self):
        worker=object.__new__(local.Worker)
        with tempfile.TemporaryDirectory() as folder:
            worker.root=Path(folder)
            with patch.object(local,'check_session') as session:
                with self.assertRaisesRegex(PermissionError,'REAL_UI_DRY_RUN_REQUIRED'):worker.run_ui_once(real=True)
            session.assert_not_called()
    def test_fixture_dry_receipt_is_not_real_uia_evidence(self):
        worker=object.__new__(local.Worker)
        with tempfile.TemporaryDirectory() as folder:
            worker.root=Path(folder);path=worker.root/'jobs'/local.JOB_ID/'dry'/'UI_DRY_RUN_PASS.json'
            path.parent.mkdir(parents=True);path.write_text(json.dumps({'status':'LOCAL_UIA_DRY_RUN_PASS','source':'FIXTURE','submit_attempt_count':0}),'utf-8')
            with patch.object(local,'check_session') as session:
                with self.assertRaisesRegex(PermissionError,'REAL_UI_DRY_RUN_REQUIRED'):worker.run_ui_once(real=True)
            session.assert_not_called()
    def test_legacy_server_real_executor_stops_before_any_ui_or_claim(self):
        from xiaovcat_adapter.desktop_worker.production_worker import run_plan
        dispatcher=Mock()
        with patch('socket.gethostname',return_value='PC-20260617GEOP'),patch('xiaovcat_adapter.desktop_worker.production_worker.settings') as settings:
            with self.assertRaisesRegex(PermissionError,'SERVER_PUBLISH_EXECUTION_RETIRED'):
                run_plan(dispatcher,None,'plan')
        settings.assert_not_called();dispatcher.claim.assert_not_called()
    def scope(self,dry=False):
        return Mock(dry=dry,real_submit_armed=not dry,policy={},job_id=local.JOB_ID)
    def test_dry_cannot_reserve(self):
        scope=self.scope(True);store=local.LanOperations(scope)
        with self.assertRaises(PermissionError):store.reserve_submit_once(local.JOB_ID,scope)
        scope.call.assert_not_called()
    def test_reserve_ack_must_be_durable(self):
        scope=self.scope();scope.call.return_value={'attempt_committed':False};store=local.LanOperations(scope)
        with self.assertRaisesRegex(PermissionError,'NOT_ACKNOWLEDGED'):store.reserve_submit_once(local.JOB_ID,scope)
    def test_unarmed_cannot_reserve(self):
        scope=self.scope();scope.real_submit_armed=False;store=local.LanOperations(scope)
        with self.assertRaises(PermissionError):store.reserve_submit_once(local.JOB_ID,scope)
    def test_dry_preparation_never_writes_job(self):
        scope=self.scope(True);store=local.LanOperations(scope)
        store.prepare_verified_job(local.JOB_ID,scope.policy,{'scheduled_at':local.SCHEDULED_AT})
        scope.check.assert_called_once();scope.call.assert_not_called()


if __name__=='__main__':unittest.main()
