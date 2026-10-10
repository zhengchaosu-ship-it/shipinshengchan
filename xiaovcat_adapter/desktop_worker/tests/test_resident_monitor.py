"""小型只读监督测试；不调用GUI，不读生产数据库或真实视频。"""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from xiaovcat_adapter.desktop_worker.resident_monitor import (
    ResidentMonitor, instance_lock, queue_eligible, read_queue, validate_config)


class ResidentMonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root/'operations.db'
        with closing(sqlite3.connect(self.database)) as db:
            db.executescript('''CREATE TABLE startup_production_dispatch(job_id TEXT,plan_id TEXT,state TEXT,claimed_at TEXT);
                CREATE TABLE publish_plans(plan_id TEXT,status TEXT);
                CREATE TABLE publish_jobs(job_id TEXT,status TEXT,current_step TEXT,scheduled_at TEXT);
                CREATE TABLE state_events(job_id TEXT,step TEXT);
                INSERT INTO publish_plans VALUES('p','CONFIRMED');
                INSERT INTO startup_production_dispatch VALUES('j','p','QUEUED',NULL);
                INSERT INTO publish_jobs VALUES('j','NEEDS_MANUAL','STARTUP_CONFIRMED_NOT_DISPATCHED','2030-01-01');
                INSERT INTO startup_production_dispatch VALUES('old','p','SCHEDULED_QUEUED','old');
                INSERT INTO publish_jobs VALUES('old','SCHEDULED_QUEUED','DONE','2020-01-01');
                INSERT INTO state_events VALUES('old','V04_FINAL_SUBMIT_RESERVED');''')
        self.switch = self.root/'adapter.json'
        self.switch.write_text('{"real_publish_enabled":false}', 'utf-8')
        self.config = dict(mode='MONITOR_ONLY',real_publish_enabled=False,worker_id='fixture',
                           allowed_job_ids=['j'],operations_db=str(self.database),
                           adapter_config=str(self.switch),xiaovcat_executable='fixture.exe')
        self.present = lambda _:dict(xiaovcat_process_present=True,interactive_session_present=True,process_ids=[10])

    def test_config_monitor_only(self):
        self.assertEqual(validate_config(self.config)['mode'],'MONITOR_ONLY')

    def test_cannot_enable_execution(self):
        with self.assertRaisesRegex(PermissionError,'MONITOR_ONLY'):
            validate_config(dict(self.config,mode='EXECUTE'))

    def test_cannot_enable_real_switch(self):
        with self.assertRaises(PermissionError):validate_config(dict(self.config,real_publish_enabled=True))

    def test_duplicate_allowlist_denied(self):
        with self.assertRaises(ValueError):validate_config(dict(self.config,allowed_job_ids=['j','j']))

    def test_only_configured_job_is_observed(self):
        self.assertEqual([r['job_id'] for r in read_queue(self.database,['j'])],['j'])

    def test_empty_allowlist_observes_none(self):
        self.assertEqual(read_queue(self.database,[]),[])

    def test_confirmed_unclaimed_job_is_queue_candidate_only(self):
        self.assertTrue(queue_eligible(read_queue(self.database,['j'])[0]))

    def test_reserved_or_claimed_job_never_eligible(self):
        row = read_queue(self.database,['j'])[0]
        for changes in ({'submit_reservations':1},{'claimed_at':'now'},{'state':'CLAIMED'},
                        {'state':'SUBMIT_RESULT_UNCERTAIN'},{'state':'SCHEDULED_QUEUED'},
                        {'plan_status':'TEST_ONLY'},{'current_step':'OTHER'}):
            with self.subTest(changes=changes):self.assertFalse(queue_eligible(dict(row,**changes)))

    def test_old_success_not_eligible(self):
        self.assertFalse(queue_eligible(read_queue(self.database,['old'])[0]))

    def test_queue_read_does_not_modify_database(self):
        before = self.database.read_bytes()
        read_queue(self.database,['j'])
        self.assertEqual(before,self.database.read_bytes())

    def test_missing_database_not_created(self):
        target = self.root/'missing.db'
        with self.assertRaises(sqlite3.OperationalError):read_queue(target,['j'])
        self.assertFalse(target.exists())

    def test_heartbeat_is_monitor_not_execution_success(self):
        heartbeat = ResidentMonitor(self.config,self.root/'runtime',presence=self.present).tick()
        self.assertEqual(heartbeat['status'],'IDLE')
        self.assertFalse(heartbeat['execution_capable'])
        self.assertFalse(heartbeat['production_execution_enabled'])
        self.assertIsNone(heartbeat['current_job_id'])
        self.assertEqual(heartbeat['claim_count'],0)
        self.assertEqual(heartbeat['final_submit_invocations'],0)
        for key in ('worker_id','hostname','last_heartbeat','xiaovcat_process_present','interactive_session_present'):
            self.assertIn(key,heartbeat)

    def test_noninteractive_session_halts_monitor(self):
        present = lambda _:dict(xiaovcat_process_present=True,interactive_session_present=False,process_ids=[10])
        heartbeat = ResidentMonitor(self.config,self.root/'runtime',presence=present).tick()
        self.assertEqual(heartbeat['failure_code'],'WINDOWS_INTERACTIVE_LOGIN_REQUIRED')
        self.assertEqual(heartbeat['claim_count'],0)

    def test_global_switch_true_never_reset_or_consumed(self):
        self.switch.write_text('{"real_publish_enabled":true}', 'utf-8')
        with self.assertRaises(PermissionError):ResidentMonitor(self.config,self.root/'runtime',presence=self.present).tick()
        self.assertTrue(json.loads(self.switch.read_text())['real_publish_enabled'])

    def test_second_instance_rejected(self):
        with instance_lock(self.root/'instance.lock'):
            with self.assertRaisesRegex(RuntimeError,'OTHER_RESIDENT_WORKER_ACTIVE'):
                with instance_lock(self.root/'instance.lock'):self.fail('duplicate lock')


if __name__ == '__main__':unittest.main()
