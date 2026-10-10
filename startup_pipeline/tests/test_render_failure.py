"""真实SQLite隔离夹具；失败回执不能使内容READY或触发发布。"""
from copy import deepcopy
from pathlib import Path
import sqlite3
import unittest
from . import test_pipeline as pipeline_fixture
from startup_pipeline.render_failure import migrate, register_failed


class RenderFailureTests(unittest.TestCase):
    def setUp(self):
        self.fixture = pipeline_fixture.PipelineTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.temp.cleanup)
        self.path = self.fixture.store.path
        row = self.fixture.pipeline.contents(self.fixture.token)[0]
        self.key = row['content_id']
        # 原Pipeline夹具预置READY；本测试显式构造未导出的隔离内容，不改生产数据库。
        with self.fixture.store.connect(write=True) as db:
            db.execute("UPDATE startup_contents SET production_status='GENERATING',video_path=NULL,error='WAITING_EXPORTED_MP4' WHERE content_id=?", (self.key,))
        self.identity = {k: row[k] for k in ('content_id','employee_id','batch_id','video_index','composition_signature','business_type')}
        self.identity['job_id'] = self.key
        self.identity['target_account_id'] = row.get('target_account_id')
        self.receipt = {'status': 'NEEDS_MANUAL', 'render_job_id': self.key, 'failed_step': 'JIANYING_DRAFT_NOT_VISIBLE', 'error': 'RuntimeError:JIANYING_DRAFT_NOT_VISIBLE', 'real_publish_attempts': 0, 'events': [{'status': 'RENDER_FAILED', 'at': '2026-10-03T21:38:06+00:00'}]}

    def apply(self): return register_failed({'operations_db': str(self.path)}, self.identity, self.receipt)
    def row(self): return self.fixture.pipeline.contents(self.fixture.token)[0]
    def test_real_failed_status_and_detail(self):
        self.apply(); row = self.row()
        self.assertEqual(row['production_status'], 'RENDER_FAILED'); self.assertEqual(row['failure_code'], 'JIANYING_DRAFT_NOT_VISIBLE')
        self.assertEqual(row['failed_at'], '2026-10-03T21:38:06+00:00'); self.assertEqual(row['render_job_id'], self.key)
    def test_repeat_idempotent(self):
        self.apply(); before = self.row(); self.assertTrue(self.apply()['idempotent']); self.assertEqual(self.row(), before)
    def test_failure_immutable(self):
        self.apply(); self.receipt['error'] = 'another'
        with self.assertRaisesRegex(ValueError, 'IMMUTABLE'): self.apply()
    def test_other_employee_denied(self):
        self.identity['employee_id'] = self.fixture.other
        with self.assertRaises(PermissionError): self.apply()
    def test_other_signature_denied(self):
        self.identity['composition_signature'] = 'changed'
        with self.assertRaises(PermissionError): self.apply()
    def test_other_bound_account_denied(self):
        self.identity['target_account_id'] = 'B1'
        with self.assertRaises(PermissionError): self.apply()
    def test_wrong_job_denied(self):
        self.receipt['render_job_id'] = 'other'
        with self.assertRaises(ValueError): self.apply()
    def test_ready_cannot_be_downgraded(self):
        with self.fixture.store.connect(write=True) as db: db.execute("UPDATE startup_contents SET production_status='READY' WHERE content_id=?", (self.key,))
        with self.assertRaises(PermissionError): self.apply()
    def test_scheduled_cannot_be_downgraded(self):
        with self.fixture.store.connect(write=True) as db: db.execute("UPDATE startup_contents SET publish_status='SCHEDULED' WHERE content_id=?", (self.key,))
        with self.assertRaises(PermissionError): self.apply()
    def test_success_not_failure(self):
        self.receipt['status'] = 'COMPLETED'
        with self.assertRaises(ValueError): self.apply()
    def test_migration_repeat_and_foreign_keys(self):
        self.assertTrue(migrate(self.path)['already_applied'])
        with self.fixture.store.connect() as db: self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())
    def test_other_content_unchanged_no_publish_jobs(self):
        before = self.fixture.pipeline.contents(self.fixture.token)[1:]; self.apply()
        self.assertEqual(self.fixture.pipeline.contents(self.fixture.token)[1:], before)
        with self.fixture.store.connect() as db: self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0], 0)
    def test_failed_not_ready_pool(self):
        self.apply(); self.assertIsNone(self.row()['video_path']); self.assertEqual(self.row()['publish_status'], 'NOT_SCHEDULED')
    def test_late_success_must_not_clear_failure(self):
        self.apply()
        from startup_render.completion import register_completed
        # 完成回执不能没有文件而使失败内容READY。
        with self.assertRaises(Exception): register_completed({'result_root': str(self.fixture.root), 'operations_db': str(self.path)}, self.fixture.root, self.identity, {'export_status': 'VALIDATED'})
        self.assertEqual(self.row()['production_status'], 'RENDER_FAILED')
    def test_no_time_repeat_keeps_first_time(self):
        self.receipt['events'] = []; self.apply(); first = self.row()['failed_at']; self.apply(); self.assertEqual(self.row()['failed_at'], first)
    def broker_receipt(self):
        import json
        from startup_render.server import Broker
        broker = Broker({'state_root': str(self.fixture.root / 'server'), 'batch_root': str(self.fixture.batch_root), 'operations_db': str(self.path)})
        identity = dict(self.identity, origin='GENERATION_COMPLETED_EVENT')
        with broker.connect() as db:
            db.execute("INSERT INTO jobs(job_id,batch_id,video_index,status,payload,claim) VALUES(?,?,?,'CLAIMED',?,'fixture-claim')", (self.key, identity['batch_id'], identity['video_index'], json.dumps(identity)))
        self.receipt['claim'] = 'fixture-claim'
        return broker
    def test_broker_failure_arrival_updates_business_once(self):
        broker = self.broker_receipt(); broker.receipt(self.key, self.receipt)
        first = self.row(); broker.receipt(self.key, self.receipt)
        self.assertEqual(self.row(), first); self.assertEqual(first['production_status'], 'RENDER_FAILED')
        self.assertEqual(broker.status()['jobs'][0]['status'], 'NEEDS_MANUAL')
    def test_broker_late_success_rejected_before_business_write(self):
        broker = self.broker_receipt(); broker.receipt(self.key, self.receipt)
        late = dict(self.receipt, status='COMPLETED')
        with self.assertRaisesRegex(ValueError, 'RESULT_IMMUTABLE'): broker.receipt(self.key, late)
        self.assertEqual(self.row()['production_status'], 'RENDER_FAILED')
