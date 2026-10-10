"""正式数据库夹具与Mock执行器；不读生产库，不实例化真实UI。"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import unittest
from unittest.mock import Mock,patch
import test_production_dispatch as dispatch_fixtures
from startup_pipeline.production_dispatch import RESERVE_STEP
from xiaovcat_adapter.local_worker_queue import LocalWorkerQueue
from xiaovcat_adapter.storage import OperationsStore
from xiaovcat_adapter.desktop_worker.v04_submit import reserve_once
from xiaovcat_publish_worker import PublishWorker,validate_config,safe_code,single_instance


class LocalWorkerTests(unittest.TestCase):
    def setUp(self):
        self.base=dispatch_fixtures.ProductionDispatchTests();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.f=self.base.f
        self.config=dict(worker_id='fixture-local',worker_enabled=True,dry_run_mode=False,real_submit_armed=True,
                         allowed_plan_ids=[self.base.plan_id],allowed_job_ids=[self.base.jobs[0]],
                         windows_user_sid='fixture-sid',hostname='fixture-host',xiaovcat_executable='fixture.exe',
                         operations_db=str(self.f.store.path),runtime_dir=str(self.f.root/'local_worker'))
        self.auth=Mock()
        self.queue=LocalWorkerQueue(self.base.d,self.config,self.auth)
        self.factory=Mock(side_effect=self.publisher)
        self.calls=[]
        self.worker=self.make_worker()

    def make_worker(self):
        worker=PublishWorker(self.config,self.queue,publisher_factory=self.factory,
                             session_check=Mock(return_value={'session_id':1,'interactive_session_present':True,'xiaovcat_process_present':True}))
        return worker

    def publisher(self,scope,*,armed_check):
        outer=self
        class FakePublisher:
            def prepare_job(self):outer.calls.append('prepare')
            def verify_form(self):outer.calls.append('verify')
            def submit_once(self):
                outer.calls.append('submit');armed_check()
                reserve_once(OperationsStore(outer.f.store.path),scope.job_id,scope)
                return dict(invoke_returned=True,final_submit_invocations=1)
            def reconcile_result(self,submission):
                outer.calls.append('reconcile')
                return dict(verified=True,status='SCHEDULED_QUEUED',job_id=scope.job_id,
                            content_id=scope.policy['content_id'],account_id=scope.policy['account_id'],
                            scheduled_at=scope.policy['scheduled_at'],task_status='已同步',final_submit_invocations=1)
        return FakePublisher()

    def row(self):return self.queue.discover()[0]

    def test_discover_only_explicit_scope(self):
        self.assertEqual([r['job_id'] for r in self.queue.discover()],[self.base.jobs[0]])

    def test_scope_denied_no_claim(self):
        row=self.row();row['job_id']=self.base.jobs[1]
        with self.assertRaisesRegex(PermissionError,'SCOPE_DENIED'):self.queue.claim(row)

    def test_local_os_authority_required(self):
        self.auth.side_effect=PermissionError('WINDOWS_USER_MISMATCH')
        with self.assertRaisesRegex(PermissionError,'USER_MISMATCH'):self.queue.claim(self.row())

    def test_unarmed_dry_run_never_claims_or_instantiates_publisher(self):
        self.config.update(dry_run_mode=True,real_submit_armed=False)
        with self.f.store.connect() as db:before=[tuple(r) for r in db.execute('SELECT * FROM state_events')]
        result=self.worker.run_once()
        self.assertEqual(result['status'],'ARMED_REQUIRED');self.assertEqual(result['claim_count'],0)
        self.assertEqual(result['jobs'][0]['account_id'],'A1')
        self.factory.assert_not_called()
        with self.f.store.connect() as db:
            self.assertEqual(before,[tuple(r) for r in db.execute('SELECT * FROM state_events')])
            self.assertEqual(db.execute("SELECT count(*) FROM startup_production_dispatch WHERE state='QUEUED'").fetchone()[0],3)

    def test_dry_config_cannot_arm(self):
        with self.assertRaisesRegex(PermissionError,'DRY_RUN_CANNOT_ARM'):validate_config(dict(self.config,dry_run_mode=True))

    def test_non_bool_switch_rejected(self):
        with self.assertRaises(ValueError):validate_config(dict(self.config,real_submit_armed='false'))

    def test_empty_scope_rejected(self):
        with self.assertRaises(ValueError):validate_config(dict(self.config,allowed_job_ids=[]))

    def test_parallel_claim_one(self):
        row=self.row()
        def attempt(_):
            try:return self.queue.claim(row)
            except PermissionError:return None
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sum(bool(r) for r in executor.map(attempt,range(2))),1)

    def test_duplicate_claim_after_restart_rejected(self):
        row=self.row();self.queue.claim(row)
        with self.assertRaisesRegex(PermissionError,'ALREADY_CLAIMED'):self.queue.claim(row)

    def test_revoked_group_permission_denies_local_worker(self):
        with self.f.store.connect(write=True) as db:
            db.execute('UPDATE employee_group_bindings SET enabled=0 WHERE employee_id=?',(self.f.employee,))
        with self.assertRaises(PermissionError):self.queue.claim(self.row())

    def test_expired_snapshot_not_relaxed(self):
        with self.f.store.connect(write=True) as db:
            db.execute("UPDATE xiaovcat_accounts SET last_synced_at='2020-01-01T00:00:00+00:00'")
        with self.assertRaisesRegex(PermissionError,'SNAPSHOT_EXPIRED'):self.queue.claim(self.row())

    def test_success_original_job_only_and_idempotent_restart(self):
        result=self.worker.run_once();self.assertTrue(result['verified'])
        self.assertEqual(self.calls,['prepare','verify','submit','reconcile'])
        self.assertEqual(self.queue.submission(self.base.jobs[0])['submit_attempt_count'],1)
        self.make_worker().run_once()
        self.assertEqual(self.calls.count('submit'),1)
        with self.f.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0],3)
            self.assertEqual(db.execute("SELECT count(*) FROM startup_production_dispatch WHERE state='QUEUED'").fetchone()[0],2)

    def test_restart_reserved_unknown_only_reconcile(self):
        row=self.row();nonce=self.queue.claim(row);scope=self.queue.scope(row,nonce,self.f.root/'fixture')
        reserve_once(OperationsStore(self.f.store.path),row['job_id'],scope)
        self.base.d.block(row['job_id'],'fixture-crash')
        self.assertTrue(self.worker.run_once()['verified'])
        self.assertEqual(self.calls,['reconcile'])
        self.assertEqual(self.queue.submission(row['job_id'])['submit_attempt_count'],1)

    def test_restart_pre_submit_does_not_replay_writes(self):
        self.queue.claim(self.row())
        result=self.worker.run_once()
        self.assertEqual(result['failure_code'],'INTERRUPTED_PRE_SUBMIT_NO_WRITE_REPLAY')
        self.factory.assert_not_called()

    def test_foreign_worker_claim_never_taken_over(self):
        row=self.row();nonce=self.base.d.claim(self.f.token,row['plan_id'],row['job_id'],'other-worker')
        scope=self.queue.scope(row,nonce,self.f.root/'fixture')
        reserve_once(OperationsStore(self.f.store.path),row['job_id'],scope)
        result=self.worker.run_once()
        self.assertEqual(result['failure_code'],'OTHER_WORKER_CLAIM_NO_TAKEOVER')
        self.assertEqual(self.queue.row(row['job_id'])['state'],'CLAIMED')

    def test_unknown_result_stops_and_preserves_single_attempt(self):
        pub=self.publisher
        def unknown(scope,**kwargs):
            p=pub(scope,**kwargs);p.reconcile_result=lambda _:dict(status='SUBMIT_RESULT_UNCERTAIN',verified=False);return p
        self.factory.side_effect=unknown
        result=self.worker.run_once();self.assertEqual(result['failure_code'],'SUBMIT_RESULT_UNCERTAIN')
        self.assertTrue(self.worker.stop.is_set());self.assertEqual(self.queue.submission(self.base.jobs[0])['submit_attempt_count'],1)
        self.assertEqual(self.queue.row(self.base.jobs[0])['state'],'SUBMIT_RESULT_UNCERTAIN')

    def test_prepare_failure_no_submit(self):
        pub=self.publisher
        def fail(scope,**kwargs):
            p=pub(scope,**kwargs);p.prepare_job=Mock(side_effect=RuntimeError('FORM_FAILURE'));return p
        self.factory.side_effect=fail
        self.worker.run_once();self.assertNotIn('submit',self.calls)
        self.assertEqual(self.queue.submission(self.base.jobs[0])['submit_attempt_count'],0)

    def test_session_error_before_discovery_no_publish(self):
        self.worker.session_check.side_effect=RuntimeError('WINDOWS_INTERACTIVE_LOGIN_REQUIRED')
        with self.assertRaises(RuntimeError):self.worker.run_once()
        self.factory.assert_not_called()

    def test_heartbeat_no_secrets(self):
        self.worker.authority();self.worker.heartbeat()
        data=json.loads((self.worker.runtime/'heartbeat.json').read_text('utf-8'))
        self.assertEqual(data['session_id'],1);self.assertNotIn('token',data)
        self.assertFalse(data['real_publish_enabled'])

    def test_hot_arm_disabled_before_submit(self):
        self.config.update(real_submit_armed=False)
        with self.assertRaisesRegex(PermissionError,'ARMED_REQUIRED'):self.worker.armed()
        self.assertFalse(self.calls)

    def test_error_logging_does_not_echo_sensitive_exception(self):
        self.assertEqual(safe_code(RuntimeError('password=fixture-secret')),'LOCAL_WORKER_ERROR')

    def test_hot_scope_changes_require_restart(self):
        path=self.f.root/'worker.json';path.write_text(json.dumps(dict(self.config,allowed_job_ids=['other'])),'utf-8')
        self.worker.config_path=path
        with self.assertRaisesRegex(PermissionError,'SCOPE_CHANGED'):self.worker.refresh_config()

    def test_second_executor_instance_rejected(self):
        from contextlib import nullcontext
        with patch('xiaovcat_adapter.desktop_worker.production_worker.worker_lock',return_value=nullcontext()):
            with single_instance(self.f.root/'lock'):
                with self.assertRaisesRegex(RuntimeError,'WORKER_ALREADY_RUNNING'):
                    with single_instance(self.f.root/'lock'):self.fail('SECOND_EXECUTOR_STARTED')

    def one_shot_worker(self):
        return PublishWorker(self.config,self.queue,publisher_factory=self.factory,
                             session_check=self.worker.session_check,one_shot=True)

    def test_one_shot_disarmed_before_readonly_result_lookup(self):
        pub=self.publisher
        def read_after_disarm(scope,**kwargs):
            p=pub(scope,**kwargs);submit=p.submit_once;reconcile=p.reconcile_result
            def submit_with_callback():
                result=submit();scope.on_submit_permission_revoked();return result
            def verify_unarmed(result):
                self.assertFalse(self.config['real_submit_armed']);self.assertTrue(self.config['dry_run_mode'])
                return reconcile(result)
            p.submit_once=submit_with_callback;p.reconcile_result=verify_unarmed;return p
        self.factory.side_effect=read_after_disarm
        result=self.one_shot_worker().run_once()
        self.assertTrue(result['verified']);self.assertFalse(self.config['real_submit_armed'])
        self.assertEqual(self.queue.submission(self.base.jobs[0])['submit_attempt_count'],1)

    def test_one_shot_invoke_exception_revokes_permission_and_never_retries(self):
        pub=self.publisher
        def crashed(scope,**kwargs):
            p=pub(scope,**kwargs)
            def fail():
                reserve_once(OperationsStore(self.f.store.path),scope.job_id,scope)
                scope.on_submit_permission_revoked();raise RuntimeError('INVOKE_FAILED')
            p.submit_once=fail;return p
        self.factory.side_effect=crashed
        result=self.one_shot_worker().run_once()
        self.assertEqual(result['failure_code'],'INVOKE_FAILED');self.assertFalse(self.config['real_submit_armed'])
        self.assertEqual(self.queue.submission(self.base.jobs[0])['submit_attempt_count'],1)
        self.make_worker().run_once();self.assertEqual(self.queue.submission(self.base.jobs[0])['submit_attempt_count'],1)

    def test_one_shot_preparation_failure_also_disarms(self):
        pub=self.publisher
        def failed(scope,**kwargs):
            p=pub(scope,**kwargs);p.prepare_job=Mock(side_effect=RuntimeError('PREPARE_FAILED'));return p
        self.factory.side_effect=failed
        self.one_shot_worker().run_once()
        self.assertFalse(self.config['real_submit_armed']);self.assertTrue(self.config['dry_run_mode'])
        self.assertEqual(self.queue.submission(self.base.jobs[0])['submit_attempt_count'],0)

    def test_one_shot_never_hot_reloads_disk_arm(self):
        with self.assertRaisesRegex(PermissionError,'MEMORY_AUTHORITY_ONLY'):
            PublishWorker(self.config,self.queue,config_path='fixture.json',one_shot=True)


if __name__=='__main__':unittest.main()
