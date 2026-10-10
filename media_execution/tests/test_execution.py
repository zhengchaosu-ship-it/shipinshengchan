from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
import shutil
import uuid

from media_execution.control import ControlPlane, Policy
from media_execution.coordinator import MediaExecutionCoordinator, ExecutionFailure, classify_failure
from media_execution.locking import media_lock, LaneBusy
from media_execution.network import inspect_publish_network
from media_execution.archive import archive_file, ArchivePaused
from media_execution.api import ExecutionAPI, RemoteControlPlane


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parents[1]/'runtime'/'tests'
        self.root = parent/uuid.uuid4().hex
        self.root.mkdir(parents=True)
        def cleanup():
            if self.root.resolve().parent!=parent.resolve():
                raise PermissionError('TEST_CLEANUP_OUTSIDE_TEST_ROOT')
            shutil.rmtree(self.root)
        self.addCleanup(cleanup)
        self.now = time.time()
        self.control = ControlPlane(self.root/'isolated.db',clock=lambda:self.now,
                                    authorize=lambda db,job:True)
        self.control.migrate()
        self.worker = 'WORKER-2060S-01'
        self.control.set_infrastructure(self.worker,'ONLINE')
        for account in 'ABCDE':
            self.control.set_account(account,'OPEN','ONLINE')
        self.active,self.maximum = 0,0
        self.observed = []
        self.guard = threading.Lock()

    def enroll_render(self, number, account='A'):
        self.control.enroll('RENDER','r'+str(number),self.worker,account,'c'+str(number),{'composition_id':'composition-'+str(number)})

    def enroll_publish(self, number, account='A', **values):
        self.control.enroll('PUBLISH','p'+str(number),self.worker,account,'c'+str(number),
                           {'provider_account_id':'provider-'+account,'render_job_id':'r'+str(number),**values},
                           scheduled_at=self.now+10000+int(number))

    def output(self, number):
        path = self.root/(str(number)+'.mp4')
        path.write_bytes(b'ISOLATED_MOCK_NOT_A_REAL_VIDEO')
        return {'local_output_path':str(path),'media':{'full_decode_verified':True,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                'width':1080,'height':1920,'size':path.stat().st_size,'duration':8.0,'fps':'30/1','codec':'h264'}}

    def seed_output(self, number, account='A'):
        self.enroll_render(number,account)
        job = self.control.claim(self.worker)
        self.assertEqual(job['job_id'],'r'+str(number))
        self.control.stage(self.worker,job['lease_token'],'OUTPUT_VERIFYING')
        self.control.complete_render(self.worker,job['lease_token'],self.output(number))

    def enter(self, job):
        with self.guard:
            self.active+=1
            self.maximum=max(self.maximum,self.active)
            self.observed.append(job['job_id'])

    def leave(self):
        with self.guard:
            self.active-=1

    def render(self, job, context):
        self.enter(job)
        try:
            context.stage('RENDERING')
            context.stage('EXPORTING')
            return self.output(job['job_id'][1:])
        finally:
            self.leave()

    def intent(self, job):
        return {'payload_sha256':'a'*64,'request_hash':'b'*64,'scheduledTime':int(job['scheduled_at']*1000)}

    def publish(self, job, context):
        self.enter(job)
        try:
            context.stage('PROVIDER_UPLOADING')
            context.stage('PROVIDER_VALIDATED')
            context.reserve_submit(self.intent(job))
            context.stage('PROVIDER_SUBMITTING')
            return {'state':'SCHEDULED_QUEUED','provider_task_id':'task-'+job['job_id'],'provider_video_id':'video-'+job['job_id']}
        finally:
            self.leave()

    def coordinator(self, **overrides):
        options = dict(render=self.render,publish=self.publish,recover_render=self.render,executor_quiescent=lambda:True)
        options.update(overrides)
        return MediaExecutionCoordinator(self.control,self.worker,self.root/'journal.json',**options)

    def test_A_render_export_holds_lane_publish_waits(self):
        self.seed_output(2,'B')
        self.enroll_render(1)
        entered,release = threading.Event(),threading.Event()
        def slow(job,context):
            self.enter(job)
            try:
                context.stage('EXPORTING')
                entered.set()
                if not release.wait(10):
                    raise RuntimeError('TEST_TIMEOUT')
                return self.output(1)
            finally:
                self.leave()
        coordinator = self.coordinator(render=slow)
        with ThreadPoolExecutor(2) as pool:
            running = pool.submit(coordinator.run_once)
            self.assertTrue(entered.wait(5))
            try:
                self.enroll_publish(2,'B')
                self.assertIsNone(self.control.claim(self.worker))
                self.assertEqual(self.control.row('PUBLISH','p2')['state'],'WAITING_FOR_WORKSTATION')
                self.assertEqual(self.coordinator().run_once()['state'],'WAITING_FOR_WORKSTATION')
            finally:
                release.set()
            self.assertEqual(running.result()['state'],'COMPLETED')
        self.assertEqual(coordinator.run_once()['state'],'SCHEDULED_QUEUED')
        self.assertEqual(self.maximum,1)

    def test_B_upload_and_submit_hold_lane_render_waits(self):
        self.seed_output(1)
        self.enroll_publish(1)
        def checked_publish(job,context):
            for stage in ('PROVIDER_UPLOADING','PROVIDER_SUBMITTING'):
                if stage=='PROVIDER_SUBMITTING':
                    context.stage('PROVIDER_VALIDATED')
                    context.reserve_submit(self.intent(job))
                context.stage(stage)
                if stage=='PROVIDER_UPLOADING':
                    self.enroll_render(2,'B')
                self.assertIsNone(self.control.claim(self.worker))
                self.assertEqual(self.control.row('RENDER','r2')['state'],'WAITING_FOR_WORKSTATION')
            return {'state':'SUBMITTED','provider_task_id':'task-1'}
        coordinator = self.coordinator(publish=checked_publish)
        self.assertEqual(coordinator.run_once()['state'],'SUBMITTED')
        self.assertEqual(coordinator.run_once()['state'],'COMPLETED')
        self.assertEqual(self.control.row('RENDER','r2')['state'],'COMPLETED')
        reconcile=self.control.claim_reconciliation(self.worker)
        self.control.record_reconciliation(self.worker,reconcile['lease_token'],{'state':'SCHEDULED_QUEUED','provider_task_id':'task-1','provider_video_id':'video-1'})
        self.assertEqual(coordinator.run_once()['state'],'IDLE')

    def test_C_account_risk_releases_lane_other_publish_runs(self):
        self.seed_output(1)
        self.seed_output(2,'B')
        self.enroll_publish(1)
        self.enroll_publish(2,'B')
        def risk(job,context):
            if job['business_account_id']=='A':
                raise ExecutionFailure('ACCOUNT_LEVEL','ACCOUNT_RISK',gate='BLOCKED_RISK')
            return self.publish(job,context)
        coordinator = self.coordinator(publish=risk)
        self.assertEqual(coordinator.run_once()['state'],'WAITING_ACCOUNT_RECOVERY')
        self.assertEqual(coordinator.run_once()['state'],'SCHEDULED_QUEUED')
        self.assertEqual(self.control.row('RENDER','r1')['state'],'COMPLETED')

    def test_D_blocked_A_pauses_A_but_allows_C(self):
        self.control.set_account('A','BLOCKED_RISK','ONLINE',reason='ACCOUNT_RISK')
        self.enroll_render(1,'C')
        self.enroll_render(2,'A')
        coordinator = self.coordinator()
        self.assertEqual(coordinator.run_once()['state'],'COMPLETED')
        self.assertEqual(coordinator.run_once()['state'],'IDLE')

    def test_E_validation_failure_only_one_job(self):
        self.seed_output(1)
        self.seed_output(2)
        self.enroll_publish(1)
        self.enroll_publish(2)
        def bad(job,context):
            if job['job_id']=='p1':
                raise ExecutionFailure('JOB_LEVEL','PROVIDER_VALIDATION_FAILED')
            return self.publish(job,context)
        coordinator = self.coordinator(publish=bad)
        self.assertEqual(coordinator.run_once()['state'],'FAILED_JOB_LEVEL')
        self.assertEqual(coordinator.run_once()['state'],'SCHEDULED_QUEUED')
        self.assertEqual(self.control.snapshot(self.worker)['accounts'][0]['gate'],'OPEN')

    def test_F_publisher_infra_failure_render_continues(self):
        self.seed_output(1)
        self.enroll_publish(1)
        self.enroll_render(2,'B')
        def unavailable(job,context):
            raise ExecutionFailure('INFRA_LEVEL','YIXIAOER_UNREACHABLE')
        coordinator = self.coordinator(publish=unavailable)
        self.assertEqual(coordinator.run_once()['state'],'WAITING_PUBLISHER_INFRA')
        self.assertEqual(coordinator.run_once()['state'],'COMPLETED')

    def test_G_twenty_jobs_fifteen_progress_five_blocked(self):
        self.control.set_account('A','BLOCKED_MANUAL_ACTION','ONLINE',reason='SMS_REQUIRED')
        for number in range(10):
            account = 'A' if number<5 else 'B'
            self.enroll_render(number,account)
            self.enroll_publish(number,account)
        coordinator = self.coordinator()
        result = [coordinator.run_once() for _ in range(21)]
        self.assertEqual(sum(r['state']=='COMPLETED' for r in result),5)
        self.assertEqual(sum(r['state']=='SCHEDULED_QUEUED' for r in result),5)
        self.assertEqual(len(self.observed),10)
        self.assertEqual(self.maximum,1)
        self.assertEqual(len(set(self.observed)),10)
        self.assertTrue(all(self.control.row('PUBLISH','p'+str(i))['state']=='WAITING_FOR_RENDER' for i in range(5)))

    def test_H_recover_same_render_and_preintent_publish(self):
        self.enroll_render(1)
        job = self.control.claim(self.worker)
        self.now+=121
        self.assertIsNone(self.control.claim(self.worker))
        with self.assertRaisesRegex(PermissionError,'QUIESCENCE'):
            self.control.recovery(self.worker,executor_quiescent=False)
        recovered = self.control.recovery(self.worker,executor_quiescent=True,journal=job)
        self.assertEqual(recovered['job_id'],job['job_id'])
        self.assertNotEqual(recovered['lease_token'],job['lease_token'])
        with self.assertRaises(PermissionError):
            self.control.heartbeat(self.worker,job['lease_token'])
        self.control.stage(self.worker,recovered['lease_token'],'OUTPUT_VERIFYING')
        self.control.complete_render(self.worker,recovered['lease_token'],self.output(1))
        self.enroll_publish(1)
        self.control.claim(self.worker)
        recovered = self.control.recovery(self.worker,executor_quiescent=True)
        self.assertEqual(recovered['state'],'READY_TO_PUBLISH')
        self.assertEqual(self.coordinator().run_once()['state'],'SCHEDULED_QUEUED')
        self.assertEqual(self.control.row('PUBLISH','p1')['submit_attempt_count'],1)

    def test_I_intent_crash_reconciliation_only_no_repost(self):
        self.seed_output(1)
        self.enroll_publish(1)
        calls = []
        class SimulatedPowerLoss(BaseException):
            pass
        def crash(job,context):
            context.stage('PROVIDER_VALIDATED')
            context.reserve_submit(self.intent(job))
            calls.append('POST')
            raise SimulatedPowerLoss()
        with self.assertRaises(SimulatedPowerLoss):
            self.coordinator(publish=crash).run_once()
        recovered = self.coordinator(publish=crash).run_once()
        self.assertEqual(recovered['state'],'SUBMIT_RESULT_UNCERTAIN')
        self.assertEqual(self.coordinator(publish=crash).run_once()['state'],'IDLE')
        self.assertEqual(calls,['POST'])
        self.enroll_render(2,'B')
        # 提交未知只读核对；同账号与其他账号的未来独立任务仍可执行。
        self.assertEqual(self.coordinator().run_once()['state'],'COMPLETED')
        lease=self.control.claim_reconciliation(self.worker)
        self.control.record_reconciliation(self.worker,lease['lease_token'],{'state':'FAILED_JOB_LEVEL',
            'provider_task_id':'task-1','provider_response':{'errorMessage':'账号存在风险'}})
        self.assertEqual(self.control.snapshot(self.worker)['accounts'][0]['gate'],'BLOCKED_RISK')
        self.assertEqual(self.coordinator().run_once()['state'],'IDLE')

    def test_account_recovery_waits_for_planner_not_burst(self):
        self.seed_output(1)
        self.enroll_publish(1)
        self.control.set_account('A','BLOCKED_RISK','ONLINE')
        self.assertIsNone(self.control.claim(self.worker))
        self.control.set_account('A','OPEN','ONLINE')
        self.assertEqual(self.control.row('PUBLISH','p1')['state'],'WAITING_FOR_RENDER')
        self.assertIsNone(self.control.claim(self.worker))

    def test_backlog_limit_configurable_and_only_blocked_account(self):
        self.control.policy = Policy(ready_backlog_limit_per_account=1)
        self.seed_output(1)
        self.control.set_account('A','BLOCKED_AUTH','OFFLINE')
        self.enroll_render(2)
        self.enroll_render(3,'B')
        self.assertEqual(self.coordinator().run_once()['job_id'],'r3')
        self.assertEqual(self.control.row('RENDER','r2')['state'],'WAITING')

    def test_stale_first_skipped_and_no_automatic_schedule_change(self):
        self.seed_output(1)
        self.enroll_publish(1)
        scheduled = self.control.row('PUBLISH','p1')['scheduled_at']
        self.now+=3000
        self.enroll_render(2,'B')
        self.assertEqual(self.coordinator().run_once()['job_id'],'r2')
        job = self.control.row('PUBLISH','p1')
        self.assertEqual(job['state'],'STALE_SCHEDULE')
        self.assertEqual(job['scheduled_at'],scheduled)

    def test_archive_failed_does_not_block_publish_or_delete(self):
        self.seed_output(1)
        self.control.archive_result('c1',error='SMB_OFFLINE')
        self.enroll_publish(1)
        self.assertEqual(self.coordinator().run_once()['state'],'SCHEDULED_QUEUED')
        self.assertFalse(self.control.cleanup_eligible('c1'))
        self.assertEqual(self.control.row('RENDER','r1')['state'],'COMPLETED')

    def test_archive_pauses_under_media_lock_without_taking_it(self):
        source = self.root/'source.mp4'
        source.write_bytes(b'archive-test')
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        with media_lock():
            with self.assertRaises(ArchivePaused):
                archive_file(source,self.root/'copy.mp4',digest,runtime=self.root,production_busy=lambda:True)
            self.assertFalse((self.root/'copy.mp4').exists())
            receipt = archive_file(source,self.root/'copy.mp4',digest,runtime=self.root,production_busy=lambda:False)
        self.assertEqual(receipt['sha256'],digest)
        self.assertTrue(source.exists())

    def test_proxy_and_unknown_vpn_fail_closed_render_still_runs(self):
        self.assertEqual(inspect_publish_network(environ={'HTTPS_PROXY':'http://secret'},proxies={},vpn_status='DIRECT_CONFIRMED')['state'],'PUBLISH_NETWORK_ATTENTION')
        self.assertEqual(inspect_publish_network(environ={},proxies={},vpn_status='UNKNOWN')['state'],'PUBLISH_NETWORK_ATTENTION')
        self.assertEqual(inspect_publish_network(environ={},proxies={},vpn_status='DIRECT_CONFIRMED')['state'],'ONLINE')
        self.control.set_infrastructure(self.worker,'PUBLISH_NETWORK_ATTENTION')
        self.enroll_render(1)
        self.assertEqual(self.coordinator().run_once()['state'],'COMPLETED')

    def test_server_claim_atomic_between_separate_connections(self):
        for i in range(10):
            self.enroll_render(i,'A')
        def claim(_):
            other = ControlPlane(self.control.path,clock=lambda:self.now,authorize=lambda db,job:True)
            return other.claim(self.worker)
        with ThreadPoolExecutor(8) as pool:
            result = list(pool.map(claim,range(16)))
        self.assertEqual(sum(r is not None for r in result),1)

    def test_migration_preserves_legacy_rows_and_audit(self):
        with self.control.connect(write=True) as db:
            db.execute('CREATE TABLE historical_provider_jobs(job_id TEXT PRIMARY KEY,state TEXT,attempt INTEGER,task TEXT)')
            db.executemany('INSERT INTO historical_provider_jobs VALUES(?,?,?,?)',[(str(i),'SCHEDULED_QUEUED',1,'task'+str(i)) for i in range(22)]+[('failed','FAILED',1,'f'),('uncertain','SUBMIT_RESULT_UNCERTAIN',1,None)])
            before = list(map(tuple,db.execute('SELECT * FROM historical_provider_jobs ORDER BY job_id')))
        self.control.migrate()
        self.enroll_render(1)
        self.coordinator().run_once()
        with self.control.connect() as db:
            self.assertEqual(list(map(tuple,db.execute('SELECT * FROM historical_provider_jobs ORDER BY job_id'))),before)

    def test_authorization_and_worker_api_do_not_allow_self_enrollment(self):
        self.enroll_render(1)
        closed = ControlPlane(self.control.path)
        self.assertIsNone(closed.claim(self.worker))
        api = ExecutionAPI(self.control,[self.worker])
        with self.assertRaises(PermissionError):
            api.dispatch('enroll',{'worker_id':self.worker})
        with self.assertRaises(PermissionError):
            api.dispatch('claim',{'worker_id':'UNKNOWN'})

    def test_submit_intent_transport_never_retries(self):
        class Transport:
            def call(inner, route, value, **kwargs):
                self.assertEqual(kwargs,{'attempts':1})
                self.assertEqual(route,'/media-execution/submit-intent')
                raise ConnectionError('LOST_REPLY')
        with self.assertRaises(ConnectionError):
            RemoteControlPlane(Transport()).reserve_submit(self.worker,'token',{})

    def test_fencing_and_submit_latch_constraints(self):
        self.seed_output(1)
        self.enroll_publish(1)
        job = self.control.claim(self.worker)
        with self.assertRaises(PermissionError):
            self.control.reserve_submit(self.worker,'wrong',self.intent(job))
        self.control.stage(self.worker,job['lease_token'],'PROVIDER_VALIDATED')
        self.control.reserve_submit(self.worker,job['lease_token'],self.intent(job))
        with self.assertRaises(PermissionError):
            self.control.reserve_submit(self.worker,job['lease_token'],self.intent(job))
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError), self.control.connect(write=True) as db:
            db.execute("UPDATE media_execution_jobs SET submit_attempt_count=0 WHERE job_type='PUBLISH'")

    def test_global_mutex_in_another_process_and_after_forced_exit(self):
        signal = self.root/'locked'
        code = 'from media_execution.locking import media_lock; from pathlib import Path; import time\nwith media_lock():\n Path('+repr(str(signal))+').write_text("locked")\n time.sleep(30)'
        child = subprocess.Popen([sys.executable,'-c',code],cwd=Path(__file__).resolve().parents[2],
                                 stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic()+10
            while not signal.exists() and child.poll() is None and time.monotonic()<deadline:
                time.sleep(.025)
            self.assertTrue(signal.exists())
            with self.assertRaises(LaneBusy), media_lock():
                pass
        finally:
            child.kill()
            child.communicate(timeout=5)
        with media_lock():
            pass

    def test_error_classification_uses_provider_body(self):
        from yixiaoer_adapter.publisher import ProviderError
        failure = classify_failure(ProviderError('YIXIAOER_CLI_REJECTED',{'response':{'error':'需要短信验证'}}))
        self.assertEqual((failure.domain,failure.gate),('ACCOUNT_LEVEL','BLOCKED_MANUAL_ACTION'))

    def test_cancelled_and_retry_not_before_do_not_take_lane(self):
        self.enroll_render(1)
        self.control.cancel('RENDER','r1')
        self.enroll_render(2)
        with self.control.connect(write=True) as db:
            db.execute('UPDATE media_execution_jobs SET retry_not_before=? WHERE job_id=?', (self.now+60,'r2'))
        self.assertIsNone(self.control.claim(self.worker))
        self.assertIsNone(self.control.snapshot(self.worker)['active'])
        self.now+=61
        self.assertEqual(self.coordinator().run_once()['job_id'],'r2')

    def test_planner_approval_cannot_override_no_catch_up(self):
        self.seed_output(1)
        self.enroll_publish(1)
        self.now+=3000
        self.assertIsNone(self.control.claim(self.worker))
        with self.assertRaises(PermissionError):
            self.control.accept_replan('p1',self.now+10000,planner_approve=None)
        with self.assertRaisesRegex(PermissionError,'SLOT_CATCH_UP_FORBIDDEN'):
            self.control.accept_replan('p1',self.now+10000,planner_approve=lambda db,job,at:True)
        self.assertEqual(self.control.row('PUBLISH','p1')['state'],'STALE_SCHEDULE')
        self.assertIsNone(self.control.claim(self.worker))

    def test_cannot_accept_output_without_decode_and_cannot_preempt(self):
        self.enroll_render(1)
        job = self.control.claim(self.worker)
        with self.assertRaises(PermissionError):
            self.control.cancel('RENDER','r1')
        self.control.stage(self.worker,job['lease_token'],'OUTPUT_VERIFYING')
        output = self.output(1)
        output['media']['full_decode_verified'] = False
        with self.assertRaises(ValueError):
            self.control.complete_render(self.worker,job['lease_token'],output)
        self.assertIsNotNone(self.control.snapshot(self.worker)['active'])

    def test_journal_mismatch_cannot_recover_lease(self):
        self.enroll_render(1)
        job = self.control.claim(self.worker)
        with self.assertRaises(PermissionError):
            self.control.recovery(self.worker,executor_quiescent=True,journal=dict(job,job_id='another-job'))

    def test_recovery_reply_loss_keeps_rotated_token_recoverable(self):
        self.enroll_render(1)
        job=self.control.claim(self.worker)
        first=self.control.recovery(self.worker,executor_quiescent=True,journal=job)
        second=self.control.recovery(self.worker,executor_quiescent=True,journal=job)
        self.assertNotEqual(first['lease_token'],job['lease_token'])
        self.assertEqual(first['lease_token'],second['lease_token'])
        with self.assertRaises(PermissionError):self.control.heartbeat(self.worker,job['lease_token'])
        self.assertIsNone(self.control.claim(self.worker))


if __name__=='__main__':
    unittest.main()
