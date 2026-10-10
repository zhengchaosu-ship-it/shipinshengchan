"""隔离库Promote/正式确认测试；不调用Worker。"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from unittest.mock import patch
import unittest

import test_pipeline
from startup_pipeline.plan_confirmation import migrate, resume_plan
from xiaovcat_adapter.models import PublishStatus
from xiaovcat_adapter.storage import OperationsStore


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.f = test_pipeline.PipelineTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)

    def promote(self, receipt=None):
        f = self.f
        if receipt is None:
            _, receipt = f.pipeline.preview_receipt(f.token, f.plan, f.ids, f.profile)
        return f.pipeline.confirm_plan(f.token, f.plan, f.ids, f.profile, expected_preview=receipt)

    def rows(self):
        with self.f.store.connect() as db:
            return [dict(r) for r in db.execute('SELECT i.*,j.status,j.current_step,m.dispatch_mode FROM publish_plan_items i JOIN publish_jobs j USING(job_id) JOIN startup_job_metadata m USING(job_id) ORDER BY scheduled_at')]

    def test_preview_read_only(self):
        self.f.pipeline.preview_receipt(self.f.token, self.f.plan, self.f.ids, self.f.profile)
        self.assertEqual(self.rows(), [])
        self.assertTrue(all(r['publish_status']=='NOT_SCHEDULED' for r in self.f.pipeline.contents(self.f.token)))

    def test_existing_simulation_promotes_same_jobs_and_times_without_scheduler(self):
        f = self.f
        f.confirm()
        before = self.rows()
        with patch('publish_planner.storage.preview', side_effect=AssertionError('MUST_NOT_RECALCULATE')):
            result = self.promote()
        after = self.rows()
        self.assertFalse(result['simulation_only'])
        self.assertTrue(result['promoted'])
        self.assertEqual([(r['plan_id'],r['job_id'],r['content_id'],r['scheduled_at']) for r in before], [(r['plan_id'],r['job_id'],r['content_id'],r['scheduled_at']) for r in after])
        self.assertTrue(all(r['test_only']==0 and r['dispatch_mode']=='CONFIRMED_NOT_DISPATCHED' for r in after))
        self.assertEqual(OperationsStore(f.store.path).list_jobs([PublishStatus.PENDING]), [])
        self.assertEqual(result['worker_dispatches'], 0)

    def test_fresh_confirmation_is_one_atomic_official_plan(self):
        result = self.promote()
        self.assertFalse(result['simulation_only'])
        self.assertFalse(result['promoted'])
        with self.f.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM publish_plans').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT status FROM publish_plans').fetchone()[0], 'CONFIRMED')

    def test_repeat_and_parallel_confirmation_no_duplicates(self):
        f = self.f
        f.confirm()
        migrate(f.store)
        _, receipt = f.pipeline.preview_receipt(f.token, f.plan, f.ids, f.profile)
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: self.promote(receipt), range(2)))
        self.assertEqual(sum(r['created'] for r in results), 3)
        self.assertEqual(len(self.rows()), 3)
        self.assertTrue(self.promote(receipt)['idempotent'])

    def test_changed_preview_does_not_promote(self):
        self.f.confirm()
        with self.assertRaisesRegex(PermissionError, 'PREVIEW_CHANGED'):
            self.promote('bad-receipt')
        self.assertTrue(all(r['test_only']==1 for r in self.rows()))
        with self.assertRaisesRegex(PermissionError, 'PREVIEW_CHANGED'):
            self.f.pipeline.preview(self.f.token, replace(self.f.plan, interval_minutes=180), self.f.ids, self.f.profile)

    def test_other_employee_cannot_promote(self):
        f = self.f
        f.confirm()
        with self.assertRaisesRegex(PermissionError, 'PLAN_PERMISSION_DENIED'):
            f.pipeline.preview(f.other_token, f.plan, f.ids, f.profile)

    def test_expired_snapshot_still_rejected(self):
        f = self.f
        f.confirm()
        with f.store.connect(write=True) as db:
            db.execute("UPDATE xiaovcat_accounts SET last_synced_at='2020-01-01T00:00:00+00:00' WHERE account_id='A1'")
        with self.assertRaisesRegex(PermissionError, 'PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED'):
            self.promote()
        self.assertTrue(all(r['test_only']==1 for r in self.rows()))

    def test_offline_still_rejected(self):
        f = self.f
        f.confirm()
        with f.store.connect(write=True) as db:
            db.execute("UPDATE xiaovcat_accounts SET online_status='OFFLINE' WHERE account_id='A1'")
        with self.assertRaisesRegex(PermissionError, 'ACCOUNT_PERMISSION_DENIED'):
            self.promote()

    def test_binding_mismatch_still_rejected(self):
        f = self.f
        f.confirm()
        with f.store.connect(write=True) as db:
            # 永久content绑定有不可变触发器；模拟错误Plan映射，不绕过该约束。
            db.execute("UPDATE publish_plan_items SET account_id='A2' WHERE content_id=?", (f.ids[0],))
        with self.assertRaisesRegex(PermissionError, 'ACCOUNT_BINDING_MISMATCH'):
            self.promote()

    def test_changed_media_keeps_simulation(self):
        f = self.f
        f.confirm()
        from pathlib import Path
        Path(f.paths[0]).write_bytes(b'changed-media')
        with self.assertRaisesRegex(ValueError, 'REGISTERED_VIDEO_CHANGED'):
            self.promote()

    def test_existing_formal_job_rejected_even_if_pool_status_reset(self):
        f = self.f
        self.promote()
        with f.store.connect(write=True) as db:
            db.execute("UPDATE startup_contents SET publish_status='NOT_SCHEDULED'")
        new = replace(f.plan, plan_id='other-plan', interval_minutes=180)
        with self.assertRaisesRegex(PermissionError, 'CONTENT_ALREADY_SCHEDULED'):
            f.pipeline.confirm_plan(f.token, new, f.ids, f.profile, expected_preview='forged-pool-reset')
        self.assertEqual(len(self.rows()), 3)

    def test_active_or_successful_job_blocks_promote(self):
        f = self.f
        f.confirm()
        with f.store.connect(write=True) as db:
            db.execute("UPDATE publish_jobs SET status='SUBMITTING' WHERE content_id=?", (f.ids[0],))
        with self.assertRaisesRegex(PermissionError, 'ACTIVE_OR_SUBMITTED'):
            self.promote()

    def test_foreign_plan_and_resume_current_simulation(self):
        f = self.f
        f.confirm()
        saved = resume_plan(f.pipeline, f.token, f.ids)
        self.assertEqual(saved['plan_id'], f.plan.plan_id)
        with self.assertRaisesRegex(PermissionError, 'CONTENT_ALREADY_SCHEDULED'):
            f.pipeline.preview(f.token, replace(f.plan, plan_id='different-plan'), f.ids, f.profile)

    def test_atomic_rollback_keeps_simulation_on_write_failure(self):
        f = self.f
        f.confirm()
        migrate(f.store)
        _, receipt = f.pipeline.preview_receipt(f.token, f.plan, f.ids, f.profile)
        with f.store.connect(write=True) as db:
            db.execute("CREATE TRIGGER fail_confirmation BEFORE INSERT ON startup_plan_confirmations BEGIN SELECT RAISE(ABORT, 'fixture-failure'); END")
        with self.assertRaisesRegex(Exception, 'fixture-failure'):
            self.promote(receipt)
        self.assertTrue(all(r['test_only']==1 and r['dispatch_mode']=='SIMULATION_ONLY' for r in self.rows()))
        with f.store.connect() as db:
            self.assertEqual(db.execute('SELECT status FROM publish_plans').fetchone()[0], 'TEST_ONLY')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])


if __name__ == '__main__':
    unittest.main()
