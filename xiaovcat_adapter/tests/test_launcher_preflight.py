"""启动器隔离回归；只读夹具和Mock，绝不实例化桌面Worker。"""
from contextlib import closing, redirect_stderr
import io
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from xiaovcat_adapter.deployment import launcher_preflight as probe
from xiaovcat_adapter import server_resident


class LauncherPreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.adapter = self.root/'xiaovcat_adapter'
        self.adapter.mkdir()
        self.target = self.adapter/'server_resident.py'
        self.target.write_text('# fixture only', 'utf-8')
        self.video = self.root/'fixture.mp4'
        self.video.write_bytes(b'fixture-not-rendered')
        (self.root/'config.json').write_text(json.dumps({'paths':{'python_executable':sys.executable}}), 'utf-8')
        (self.adapter/'config.json').write_text(json.dumps({'real_publish_enabled':False}), 'utf-8')
        (self.adapter/'server_ui_worker.config.json').write_text(json.dumps(
            {'real_submit_armed':False, 'dry_run_mode':True}), 'utf-8')
        self.db_path = self.root/'operations.db'
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.executescript('CREATE TABLE publish_jobs(job_id,content_id,status,current_step,video_path,scheduled_at);'
                'CREATE TABLE startup_production_dispatch(job_id,state,claimed_at,worker_id);'
                'CREATE TABLE state_events(job_id,step);')
            db.execute('INSERT INTO publish_jobs VALUES(?,?,?,?,?,?)',
                (probe.JOB_ID,'fixture-content','NEEDS_MANUAL','STARTUP_CONFIRMED_NOT_DISPATCHED',str(self.video),'2030-01-01'))
            db.execute('INSERT INTO startup_production_dispatch VALUES(?,?,?,?)',
                       (probe.JOB_ID,'QUEUED',None,None))

    def collect(self):
        return probe.collect(root=self.root, acceptance_script=self.target)

    def test_readonly_preflight_keeps_job_and_flags(self):
        result = self.collect()
        self.assertEqual(result['status'],'NO_SUBMIT_LAUNCHER_PREFLIGHT_PASS')
        self.assertEqual(result['before'],result['after'])
        self.assertEqual(result['after']['submit_attempt_count'],0)
        self.assertEqual(result['sqlite_total_changes'],0)
        self.assertFalse(result['real_publish_enabled'])
        self.assertFalse(result['worker_created'])

    def test_existing_attempt_stops(self):
        with closing(sqlite3.connect(self.db_path)) as db, db:
            db.execute('INSERT INTO state_events VALUES(?,?)',(probe.JOB_ID,probe.RESERVE))
        with self.assertRaisesRegex(PermissionError,'ALREADY_ATTEMPTED_STOP'):
            self.collect()

    def test_global_true_is_rejected_not_overwritten(self):
        path = self.adapter/'config.json'
        path.write_text(json.dumps({'real_publish_enabled':True}), 'utf-8')
        with self.assertRaisesRegex(PermissionError,'MUST_STAY_OFF'):
            self.collect()
        self.assertTrue(json.loads(path.read_text('utf-8'))['real_publish_enabled'])

    def test_missing_video_rejected(self):
        self.video.unlink()
        with self.assertRaisesRegex(RuntimeError,'PATH_CHECK_FAILED'):
            self.collect()

    def test_cli_preflight_returns_before_worker_execution(self):
        with patch.object(sys,'argv',['server_resident','--launcher-preflight-only']), \
             patch.object(probe,'main',return_value=0) as preflight, \
             patch.object(server_resident,'run_server') as run:
            self.assertEqual(server_resident.main(),0)
        preflight.assert_called_once()
        run.assert_not_called()

    def test_cli_cannot_combine_real_and_preflight_modes(self):
        with patch.object(sys,'argv',['server_resident','--launcher-preflight-only','--user-job3-once']), \
             patch.object(server_resident,'run_server') as run, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                server_resident.main()
        self.assertEqual(caught.exception.code,2)
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
