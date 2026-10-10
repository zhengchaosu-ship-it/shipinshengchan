"""固定真实入口的隔离保护测试；不运行入口、不调用真实UI、真实库或账号同步。"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from publish_planner.storage import PlannerStore
from xiaovcat_adapter import server_job3_real_once as entry
from xiaovcat_adapter import job3_first_acceptance as locked
from xiaovcat_adapter import server_resident as resident


class RealOnceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root/'xiaovcat_adapter').mkdir()
        (self.root/'xiaovcat_adapter/config.json').write_text('{"real_publish_enabled":false}', 'utf-8')
        self.video = self.root/locked.VIDEO_NAME
        self.video.write_bytes(b'fixture only, never uploaded')
        self.exe = self.root/'fixture.exe'
        self.exe.write_bytes(b'fixture')
        self.store = PlannerStore(self.root/'operations.db')
        with closing(sqlite3.connect(self.store.path)) as db:
            db.executescript('CREATE TABLE publish_jobs(job_id TEXT,status TEXT);'
                'CREATE TABLE publish_plans(plan_id TEXT,status TEXT);'
                'CREATE TABLE startup_production_dispatch(job_id TEXT,plan_id TEXT,state TEXT,claim_token TEXT,claimed_at TEXT);')
            db.execute('INSERT INTO publish_jobs VALUES(?,?)', (entry.JOB_ID, 'NEEDS_MANUAL'))
            db.execute('INSERT INTO publish_plans VALUES(?,?)', (entry.PLAN_ID, 'CONFIRMED'))
            db.execute('INSERT INTO startup_production_dispatch VALUES(?,?,?,?,?)',
                       (entry.JOB_ID, entry.PLAN_ID, 'QUEUED', None, None))
            db.commit()
        self.config = dict(execution_site='SERVER_ONLY', worker_id=resident.WORKER_ID,
            worker_enabled=False, dry_run_mode=True, real_submit_armed=False,
            confirmed_plan_executor=True, allow_all_confirmed_plans=False,
            hostname='PC-20260617GEOP', windows_user='PC-20260617GEOP\\Administrator',
            windows_user_sid='S-1-fixture-500', operations_db=str(self.store.path),
            runtime_dir=str(self.root/'xiaovcat_adapter/runtime/server_publish_worker'),
            xiaovcat_executable=str(self.exe), allowed_plan_ids=[entry.PLAN_ID], allowed_job_ids=[entry.JOB_ID])
        self.schedule = (datetime.now(timezone.utc)+timedelta(hours=5)).isoformat()
        self.policy = dict(plan_id=entry.PLAN_ID, job_id=entry.JOB_ID, content_id=locked.CONTENT_ID,
            account_id=locked.ACCOUNT_ID, account_name='丙曜', platform='抖音',
            video_path=str(self.video), video_sha256=hashlib.sha256(self.video.read_bytes()).hexdigest(),
            scheduled_at=self.schedule, title='', description='陶老师小妙招',
            topics=['#健康','#健康科普','#养生'], business_type='STARTUP')
        self.queue = Mock()
        self.queue.submission.return_value = {'submit_attempt_count':0}
        self.queue.context_preview.return_value = dict(self.policy)
        self.queue.dispatcher._context.return_value = dict(self.policy)
        self.session = Mock(return_value={'session_id':1})
        for mocked in (patch.object(resident, 'ROOT', self.root),
            patch.object(resident, 'ServerWorkerQueue', return_value=self.queue),
            patch.object(entry, 'EXE_PATH', self.exe), patch.object(entry, 'VIDEO_PATH', self.video),
            patch.object(entry, 'SCHEDULED_AT', self.schedule),
            patch.object(locked, 'VIDEO_PATH', self.video), patch.object(locked, 'SCHEDULED_AT', self.schedule),
            patch.object(locked, 'VIDEO_SHA256', self.policy['video_sha256'])):
            mocked.start()
            self.addCleanup(mocked.stop)

    def check(self):
        return entry.precheck(self.config, self.store, session_check=self.session)

    def test_full_readonly_precheck_without_claim_or_ui(self):
        self.assertFalse(self.check()['snapshot_refresh_required'])
        self.queue.claim.assert_not_called()
        self.queue.refresh_snapshot.assert_not_called()
        self.assertFalse(self.config['real_submit_armed'])

    def test_existing_attempt_refuses_before_session_or_ui(self):
        self.queue.submission.return_value = {'submit_attempt_count':1}
        with self.assertRaisesRegex(PermissionError, 'RECONCILIATION_REQUIRED_NO_RETRY'):
            self.check()
        self.session.assert_not_called()
        self.queue.context_preview.assert_not_called()

    def test_other_jobs_cannot_enter_scope(self):
        self.config['allowed_job_ids'].append(resident.BATCH_JOBS[0])
        with self.assertRaises(PermissionError): self.check()
        self.queue.submission.assert_not_called()

    def test_sha_changed_refuses_without_submit(self):
        self.video.write_bytes(b'changed fixture')
        with self.assertRaisesRegex(PermissionError, 'LOCKED_FIELD_MISMATCH'):
            self.check()
        self.session.assert_not_called()

    def test_account_content_schedule_text_topics_are_locked(self):
        for field,value in [('account_id','foreign'),('content_id','foreign'),
            ('plan_id','foreign'),('scheduled_at','2026-10-05T16:00:00+08:00'),
            ('title','not blank'),('description','changed'),('topics',['#other'])]:
            with self.subTest(field=field):
                self.queue.context_preview.return_value = dict(self.policy, **{field:value})
                with self.assertRaises(PermissionError): self.check()

    def test_already_queued_success_cannot_run(self):
        with self.store.connect(write=True) as db:
            db.execute("UPDATE publish_jobs SET status='SCHEDULED_QUEUED'")
        with self.assertRaisesRegex(PermissionError, 'NO_REPLAY'): self.check()

    def test_claimed_row_cannot_be_replayed(self):
        with self.store.connect(write=True) as db:
            db.execute("UPDATE startup_production_dispatch SET claim_token='existing'")
        with self.assertRaisesRegex(PermissionError, 'NO_REPLAY'): self.check()

    def test_expired_snapshot_refreshes_existing_service_once_under_lock(self):
        self.queue.dispatcher._context.side_effect = [
            PermissionError('PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED'), self.policy]
        result = entry.locked_precheck(self.config, self.store, session_check=self.session)
        self.assertFalse(result['snapshot_refresh_required'])
        self.queue.refresh_snapshot.assert_called_once()
        self.queue.claim.assert_not_called()

    def test_failed_refresh_cannot_arm_or_claim(self):
        self.queue.dispatcher._context.side_effect = PermissionError('PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED')
        with self.assertRaisesRegex(PermissionError, 'SNAPSHOT_EXPIRED'):
            entry.locked_precheck(self.config, self.store, session_check=self.session)
        self.queue.refresh_snapshot.assert_called_once()
        self.queue.claim.assert_not_called()
        self.assertFalse(self.config['real_submit_armed'])

    def test_offline_or_permission_error_does_not_refresh_or_bypass(self):
        self.queue.dispatcher._context.side_effect = PermissionError('PUBLISH_ACCOUNT_OFFLINE')
        with self.assertRaisesRegex(PermissionError, 'OFFLINE'):
            entry.locked_precheck(self.config, self.store, session_check=self.session)
        self.queue.refresh_snapshot.assert_not_called()

    def test_time_window_refuses_without_recalculation(self):
        with patch.object(entry, 'SCHEDULED_AT', (datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat()):
            with self.assertRaisesRegex(PermissionError, 'NO_RECALCULATION'): self.check()
        self.session.assert_not_called()

    def test_launcher_ascii_crlf_and_no_parameter_forwarding(self):
        root = Path(__file__).resolve().parents[2]
        data = (root/'START_SERVER_XIAOVCAT_JOB3_REAL_ONCE.cmd').read_bytes()
        data.decode('ascii')
        self.assertFalse(data.startswith(b'\xef\xbb\xbf'))
        self.assertNotIn(b'\n', data.replace(b'\r\n',b''))
        self.assertNotIn(b'%*',data)
        self.assertEqual(data.strip(),b'@echo off\r\necho JOB_CANCELLED\r\nexit /b 20')
        old = (root/'START_SERVER_XIAOVCAT_JOB3_ACCEPTANCE.cmd').read_bytes()
        self.assertEqual(old,data)

    def test_user_entry_is_permanently_retired_without_worker(self):
        with patch('sys.argv',['fixed-entry']),patch.object(resident,'run_server') as run:
            self.assertEqual(entry.main(),20)
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
