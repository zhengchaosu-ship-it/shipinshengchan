"""只使用隔离数据库/草稿JSON，不生产视频、不同步2060S、不触发发布。"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import sqlite3
import unittest
from unittest.mock import patch

from publish_planner.storage import PlannerStore, ROOT
from startup_pipeline.registration import StartupContentRegistration, RegistrationError
from startup_pipeline.service import StartupPipeline
from startup_render.common import read, save
from startup_render.queue import RenderQueue
from startup_render.server import Broker
from xiaovcat_adapter.models import utc_now_iso


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix='startup-registration-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = PlannerStore(self.root / 'operations.db')
        self.store.migrate()
        self.store.bootstrap_admin('a', 'registration-test-password')
        self.token = self.store.login('a', 'registration-test-password')
        self.employee = self.store.principal(self.token)['employee_id']
        self.other = self.store.save_employee(self.token, employee_name='other', login_name='b', password='registration-test-password', group_bindings=[])
        self.other_token = self.store.login('b', 'registration-test-password')
        self.pipeline = StartupPipeline(self.store, batch_root=self.root / 'batches')
        self.queue = RenderQueue(self.root / 'render/render_jobs.db')
        self.service = StartupContentRegistration(self.pipeline, self.queue)
        self.store.sync_snapshot({'run_id':'bound-fixture','complete':True,
            'groups':[{'group_id':'g','group_name':'g','identity_status':'SOURCE_ID'}],
            'accounts':[{'account_id':'A','group_id':'g','display_name':'丙曜','platform':'抖音',
                         'online_status':'ONLINE','is_available':True,'identity_evidence':'fixture'}]}, session_token=self.token)
        self.store.save_employee(self.token, employee_id=self.employee, employee_name='a', login_name='a', role='ADMIN',
            group_bindings=[{'group_id':'g','group_role':'STARTUP'}])
        self.token = self.store.login('a', 'registration-test-password')
        self.context = self.service.begin(self.token, 'A')
        self.draft = self.root / 'drafts/fixture'; self.draft.mkdir(parents=True)
        save(self.draft / 'draft_content.json', {'duration': 1000000, 'fps': 30, 'canvas_config': {'width': 1080, 'height': 1920}})
        self.result = self.manifest(self.context['batch_id'])

    def manifest(self, batch):
        path = self.pipeline.batch_root / batch / 'batch_manifest.json'
        value = {'batch_id': batch, 'created_at': utc_now_iso(), 'completed_at': utc_now_iso(),
                 'videos': [{'video_index': 1, 'status': 'success', 'composition_signature': 'fixture-signature',
                             'draft_name': self.context['draft_names'][0], 'draft_path': str(self.draft), 'selected_materials': []}]}
        save(path, value)
        return dict(value, manifest_path=str(path))

    def complete(self):
        return self.service.complete(self.token, self.context, self.result)

    def jobs(self):
        if not self.queue.path.exists(): return []
        with sqlite3.connect(self.queue.path) as db:
            rows = db.execute('SELECT job_id,status,payload FROM jobs').fetchall()
        db.close()
        return rows

    def registration(self):
        with self.store.connect() as db:
            return dict(db.execute('SELECT * FROM startup_content_registrations').fetchone())

    def test_01_normal_completion_registers_content(self):
        result = self.complete()
        self.assertTrue(result[0]['content_id'].startswith('STARTUP-'))
        self.assertEqual(len(self.pipeline.contents(self.token)), 1)

    def test_02_employee_from_authenticated_task(self):
        self.complete()
        self.assertEqual(self.registration()['employee_id'], self.employee)
        self.assertEqual(json.loads(self.jobs()[0][2])['employee_id'], self.employee)

    def test_03_startup_business_type(self):
        self.complete()
        self.assertEqual(self.registration()['business_type'], 'STARTUP')
        self.assertEqual(json.loads(self.jobs()[0][2])['business_type'], 'STARTUP')

    def test_04_one_pending_render_created_directly(self):
        self.complete()
        self.assertEqual(len(self.jobs()), 1)
        self.assertEqual(self.jobs()[0][1], 'PENDING')
        self.assertEqual(self.registration()['production_status'], 'RENDER_PENDING')

    def test_05_repeat_callback_preserves_content_id(self):
        one = self.complete(); two = self.complete()
        self.assertEqual(one, two)
        self.assertEqual(len(self.pipeline.contents(self.token)), 1)

    def test_06_repeat_and_concurrent_enqueue_no_duplicate_job(self):
        self.complete(); record = self.registration()
        record.update(target_account_id='A', target_account_name_snapshot='丙曜')
        with ThreadPoolExecutor(max_workers=2) as executor:
            values = list(executor.map(self.queue.enqueue, [record, record]))
        self.assertEqual(values[0], values[1])
        self.assertEqual(len(self.jobs()), 1)

    def test_07_content_registration_failure_never_creates_render(self):
        with self.store.connect(write=True) as db:
            db.execute("CREATE TRIGGER reject_registration BEFORE INSERT ON startup_content_registrations BEGIN SELECT RAISE(ABORT,'test registration failed'); END")
        with self.assertRaisesRegex(RegistrationError, 'CONTENT_REGISTRATION_FAILED'):
            self.complete()
        self.assertEqual(self.jobs(), [])
        self.assertEqual(self.pipeline.contents(self.token), [])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT status FROM startup_registration_events').fetchone()[0], 'CONTENT_REGISTRATION_FAILED')

    def test_08_other_employee_cannot_complete_or_read(self):
        with self.assertRaisesRegex(RegistrationError, 'CONTENT_PERMISSION_DENIED'):
            self.service.complete(self.other_token, self.context, self.result)
        result = self.complete()
        self.assertEqual(self.pipeline.contents(self.other_token), [])
        with self.assertRaises(PermissionError): self.service.enqueue(self.other_token, result[0]['content_id'])

    def test_09_failed_evidence_batch_never_registered(self):
        self.result = self.manifest('20261004_003025')
        with self.assertRaisesRegex(RegistrationError, 'FAILED_EVIDENCE_BATCH_IMMUTABLE'): self.complete()
        self.assertEqual(self.jobs(), [])
        self.assertEqual(self.pipeline.contents(self.token), [])

    def test_10_no_publish_job_created(self):
        self.complete()
        self.assertEqual(self.store.jobs(self.token), [])

    def test_11_publish_configuration_unchanged_false(self):
        path = ROOT / 'xiaovcat_adapter/config.json'
        before = path.read_bytes()
        self.complete()
        self.assertEqual(before, path.read_bytes())
        self.assertIs(read(path)['real_publish_enabled'], False)

    def test_12_unauthenticated_generation_fails_before_run(self):
        from startup_pipeline.ui import begin_generation
        with patch('startup_pipeline.registration.StartupContentRegistration', return_value=self.service):
            with self.assertRaisesRegex(RuntimeError, 'STARTUP_LOGIN_OR_CONTEXT_REQUIRED'):
                begin_generation(SimpleNamespace(session_state={}))
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM startup_generation_runs').fetchone()[0], 1)

    def test_13_render_failure_explicit_and_retry_idempotent(self):
        with patch.object(self.queue, 'enqueue', side_effect=OSError('fixture unavailable')):
            with self.assertRaisesRegex(RegistrationError, 'RENDER_JOB_CREATE_FAILED'): self.complete()
        content_id = self.registration()['content_id']
        self.assertEqual(self.registration()['production_status'], 'RENDER_JOB_CREATE_FAILED')
        self.assertEqual(self.jobs(), [])
        self.assertEqual(self.complete()[0]['content_id'], content_id)
        self.assertEqual(len(self.jobs()), 1)

    def test_14_forged_employee_context_rejected(self):
        self.context['employee_id'] = self.other
        with self.assertRaisesRegex(RegistrationError, 'CONTENT_PERMISSION_DENIED'): self.complete()
        self.assertEqual(self.jobs(), [])

    def test_15_custom_mode_receipt_uses_task_identity_without_scan(self):
        self.result = {'draft_name': self.context['draft_names'][0], 'draft_path': str(self.draft), 'selected_materials': [], 'mode': 'fixture'}
        result = self.complete()
        self.assertEqual(result[0]['batch_id'], 'STARTUP_' + self.context['generation_id'].replace('-', ''))
        self.assertEqual(self.complete(), result)

    def test_16_pending_job_consumed_without_folder_discovery(self):
        self.complete()
        broker = Broker({'state_root': str(self.queue.path.parent), 'operations_db': str(self.store.path),
                         'batch_root': str(self.root / 'empty-not-scanned'), 'event_only': True,
                         'allowed_draft_roots': [str(self.draft.parent)]})
        broker.discover()
        self.assertEqual(self.jobs()[0][1], 'QUEUED')
        self.assertEqual(broker.claim()['manifest']['employee_id'], self.employee)

    def test_17_migration_idempotent_and_preserves_owner(self):
        self.complete()
        original = self.registration()
        self.assertEqual(self.service.migrate(), {'already_applied': True})
        self.assertEqual(self.registration(), original)

    def test_18_changed_draft_identity_does_not_rebind(self):
        self.complete()
        value = read(self.result['manifest_path'])
        value['videos'][0]['draft_name'] = 'changed'
        save(self.result['manifest_path'], value)
        with self.assertRaisesRegex(RegistrationError, 'IDENTITY_IMMUTABLE'): self.complete()
        self.assertEqual(len(self.jobs()), 1)


if __name__ == '__main__': unittest.main()
