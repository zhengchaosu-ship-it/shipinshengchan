"""服务器接线隔离测试：不操作真实Task、桌面或业务库。"""
import json
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import test_production_dispatch as fixtures
from xiaovcat_adapter import server_resident as resident


class ServerResidentTests(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.ProductionDispatchTests()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.f = self.base.f
        self.patch_plan = patch.object(resident, 'PLAN_ID', self.base.plan_id)
        self.patch_job = patch.object(resident, 'JOB_ID', self.base.jobs[0])
        for patched in (self.patch_plan, self.patch_job):
            patched.start()
            self.addCleanup(patched.stop)
        self.config = dict(execution_site='SERVER_ONLY', worker_id=resident.WORKER_ID,
            worker_enabled=False, dry_run_mode=True, real_submit_armed=False,
            confirmed_plan_executor=True, allow_all_confirmed_plans=False,
            hostname='PC-20260617GEOP', windows_user_sid='fixture-sid',
            operations_db=str(self.f.store.path), runtime_dir=str(self.f.root/'server_worker'),
            xiaovcat_executable='fixture.exe', allowed_plan_ids=[self.base.plan_id],
            allowed_job_ids=[self.base.jobs[0]])

    def test_server_identity_and_unarmed_config(self):
        self.assertIs(resident.validate_server_config(self.config), self.config)
        for field, value in (('worker_id', 'foreign-worker'), ('execution_site', 'LAN'),
                             ('hostname', '2060S'), ('dry_run_mode', False),
                             ('real_submit_armed', True), ('confirmed_plan_executor', False)):
            with self.subTest(field=field), self.assertRaises(PermissionError):
                resident.validate_server_config(dict(self.config, **{field:value}))

    def test_acceptance_scope_cannot_include_job1_job2(self):
        with self.assertRaisesRegex(PermissionError, 'JOB3_ONLY'):
            resident.validate_server_config(dict(self.config, allowed_job_ids=self.base.jobs))
        queue = resident.ServerWorkerQueue(self.base.d, self.config, Mock())
        self.assertEqual([r['job_id'] for r in queue.discover()], [self.base.jobs[0]])

    def test_notify_no_claim_or_business_write(self):
        result = resident.notify_confirmed_queue(self.f.store, self.f.token, self.base.plan_id, self.config)
        self.assertEqual(result['queued_jobs'], 1)
        self.assertFalse(result['executor_enabled'])
        self.assertEqual(result['status'], 'RESIDENT_DISABLED_PENDING_ACCEPTANCE')
        with self.f.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0], 3)
            self.assertEqual(db.execute('SELECT count(*) FROM state_events').fetchone()[0], 0)

    def test_preview_never_dispatchable(self):
        with self.f.store.connect(write=True) as db:
            db.execute("UPDATE publish_plans SET status='PREVIEWED' WHERE plan_id=?", (self.base.plan_id,))
        with self.assertRaisesRegex(PermissionError, 'CONFIRMED_STARTUP_PLAN_REQUIRED'):
            resident.notify_confirmed_queue(self.f.store, self.f.token, self.base.plan_id, self.config)

    def test_foreign_employee_cannot_notify(self):
        with self.assertRaises(PermissionError):
            resident.notify_confirmed_queue(self.f.store, 'invalid-token', self.base.plan_id, self.config)

    def test_all_confirmed_mode_requires_real_batch_acceptance(self):
        with self.assertRaisesRegex(PermissionError, 'ACCEPTANCE_REQUIRED'):
            resident.notify_confirmed_queue(self.f.store, self.f.token, self.base.plan_id,
                dict(self.config, allow_all_confirmed_plans=True,
                     production_authorized_after=datetime.now(timezone.utc).isoformat()))

    def test_general_production_never_sweeps_old_queued_jobs(self):
        config = dict(self.config, allow_all_confirmed_plans=True,
                      production_authorized_after=datetime.now(timezone.utc).isoformat())
        with patch.object(resident, 'require_batch_acceptance'):
            result = resident.notify_confirmed_queue(self.f.store, self.f.token, self.base.plan_id, config)
        self.assertEqual(result['queued_jobs'], 0)

    def test_general_mode_without_cutoff_is_rejected(self):
        with self.assertRaisesRegex(PermissionError, 'CUTOFF_REQUIRED'):
            resident.validate_server_config(dict(self.config, allow_all_confirmed_plans=True))

    def test_service_does_not_spawn_another_executor(self):
        config_dir = self.f.root/'xiaovcat_adapter'
        config_dir.mkdir(exist_ok=True)
        (config_dir/'server_ui_worker.config.json').write_text(json.dumps(self.config), 'utf-8')
        with patch('startup_pipeline.service.ROOT', self.f.root), patch('startup_pipeline.service.subprocess.Popen') as spawn:
            result = self.f.pipeline.start_confirmed_dispatch(self.f.token, self.base.plan_id)
        spawn.assert_not_called()
        self.assertEqual(result['transport'], 'SERVER_RESIDENT_QUEUE')

    def test_unc_file_is_not_local_publish_input(self):
        queue = resident.ServerWorkerQueue(self.base.d, self.config, Mock())
        with patch.object(queue, 'context_preview', return_value={'video_path':r'\\server\share\test.mp4'}):
            with self.assertRaisesRegex(PermissionError, 'LOCAL_READY_VIDEO_REQUIRED'):
                queue.claim(queue.discover()[0])

    def run_cycle(self, *, enabled=False, publisher_factory=None, user_once=False):
        from xiaovcat_publish_worker import PublishWorker
        path = self.f.root/'server.json'
        path.write_text(json.dumps(dict(self.config, worker_enabled=enabled)), 'utf-8')
        factory = Mock()
        def worker_factory(config, queue, **kwargs):
            return PublishWorker(config, queue, publisher_factory=publisher_factory or factory, **kwargs)
        with patch('xiaovcat_publish_worker.single_instance', return_value=nullcontext()), \
             patch.object(resident, 'ProductionDispatcher', return_value=self.base.d), \
             patch('xiaovcat_adapter.server_job3_real_once.precheck'), \
             patch('xiaovcat_adapter.server_job3_real_once.locked_precheck'), \
             patch('xiaovcat_adapter.job3_first_acceptance.validate_policy', return_value=True):
            result = resident.run_server(path, once=True, worker_factory=worker_factory,
                user_job3_once=user_once,
                session_check=Mock(return_value={'session_id':1, 'interactive_session_present':True,
                                                 'xiaovcat_process_present':True}))
        self.assertFalse(json.loads(path.read_text('utf-8'))['real_submit_armed'])
        return result, factory

    def test_disabled_resident_has_zero_ui_and_claim(self):
        result, factory = self.run_cycle()
        self.assertEqual(result['status'], 'DISABLED')
        factory.assert_not_called()
        with self.f.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM state_events').fetchone()[0], 0)

    def test_user_entry_cannot_take_over_claimed_job(self):
        self.base.claim()
        with self.assertRaisesRegex(PermissionError, 'ALREADY_CLAIMED_OR_ATTEMPTED'):
            self.run_cycle(user_once=True)

    def test_enabled_cycle_uses_original_once_latch_and_disarms_before_lookup(self):
        from xiaovcat_adapter.desktop_worker.v04_submit import reserve_once
        from xiaovcat_adapter.storage import OperationsStore
        calls = []
        outer = self
        class Publisher:
            def __init__(self, scope, armed_check):
                self.scope, self.armed_check = scope, armed_check
            def prepare_job(self): calls.append('prepare')
            def verify_form(self): calls.append('verify')
            def submit_once(self):
                self.armed_check()
                reserve_once(OperationsStore(outer.f.store.path), self.scope.job_id, self.scope)
                calls.append('submit')
                self.scope.on_submit_permission_revoked()
                return dict(invoke_returned=True, final_submit_invocations=1)
            def reconcile_result(self, submitted):
                calls.append('reconcile')
                beat = json.loads((Path(outer.config['runtime_dir'])/'heartbeat.json').read_text('utf-8'))
                outer.assertFalse(beat['real_submit_armed'])
                outer.assertFalse(beat['real_publish_enabled'])
                return dict(verified=True, status='SCHEDULED_QUEUED', job_id=self.scope.job_id,
                    content_id=self.scope.policy['content_id'], account_id=self.scope.policy['account_id'],
                    scheduled_at=self.scope.policy['scheduled_at'], task_status='已同步',
                    final_submit_invocations=1)
        result, _ = self.run_cycle(enabled=True, publisher_factory=Publisher)
        self.assertTrue(result['verified'])
        self.run_cycle(enabled=True, publisher_factory=Publisher)
        self.assertEqual(calls, ['prepare', 'verify', 'submit', 'reconcile'])
        with self.f.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0], 3)
            self.assertEqual(db.execute("SELECT count(*) FROM state_events WHERE step='V04_FINAL_SUBMIT_RESERVED'").fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
