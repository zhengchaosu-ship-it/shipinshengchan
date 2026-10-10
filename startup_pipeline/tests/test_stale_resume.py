"""提交前stale恢复：只测隔离业务库，不连接桌面或真实发布。"""
from datetime import datetime, timedelta
import json
import unittest
from unittest.mock import patch
import test_production_dispatch as fixtures
from startup_pipeline.runtime.batch3_publish_final import resume_navigation_job as recovery
from startup_pipeline.production_dispatch import ProductionScope
from xiaovcat_adapter.storage import OperationsStore
from xiaovcat_adapter.desktop_worker.v04_submit import reserve_once


class StaleRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ProductionDispatchTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.f=self.fixture.f
        self.d=self.fixture.d
        self.job=self.fixture.jobs[0]
        self.nonce=self.fixture.claim()
        self.d.block(self.job,'控件已消失，必须重新观察')
        self.addCleanup(patch.stopall)
        patch.object(recovery,'PLAN',self.fixture.plan_id).start()
        patch.object(recovery,'JOBS',[(self.job,)]).start()
        with self.f.store.connect() as db:
            self.original=dict(db.execute('SELECT * FROM startup_production_dispatch WHERE job_id=?',(self.job,)).fetchone())
        policy=json.loads(self.original['context_json'])
        self.evidence=dict(job_id=self.job,plan_id=self.fixture.plan_id,state='CURRENT_FORM_IDENTITY_VERIFIED',
            checked_at=datetime.now().astimezone().isoformat(),final_submit_invocations=0,
            skip_video_write=True,skip_account_write=True,account_id=policy['account_id'],video_path=policy['video_path'])

    def resume(self):
        return recovery.resume_stale_claim(self.d,self.f.token,self.evidence)

    def test_original_identity_and_claim_preserved(self):
        self.assertEqual(self.resume(),self.nonce)
        scope=ProductionScope(self.d,self.job,self.nonce,self.f.root/'scope')
        scope.check(scope.policy)
        with self.f.store.connect() as db:
            current=dict(db.execute('SELECT * FROM startup_production_dispatch WHERE job_id=?',(self.job,)).fetchone())
            for key in ('claim_token','context_json','claimed_at','worker_id'):
                self.assertEqual(current[key],self.original[key])
            self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0],3)

    def test_repeat_recovery_same_claim_single_audit(self):
        self.assertEqual(self.resume(),self.resume())
        with self.f.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM state_events WHERE step='PRE_SUBMIT_STALE_READBACK_RESUMED'").fetchone()[0],1)

    def test_stale_evidence_denied(self):
        self.evidence['checked_at']=(datetime.now().astimezone()-timedelta(minutes=6)).isoformat()
        with self.assertRaisesRegex(PermissionError,'FRESH_READONLY'):
            self.resume()

    def test_identity_mismatch_denied(self):
        self.evidence['account_id']='OTHER'
        with self.assertRaisesRegex(PermissionError,'RECONSTRUCTION_IDENTITY_MISMATCH'):
            self.resume()

    def test_other_employee_denied(self):
        with self.assertRaisesRegex(PermissionError,'PLAN_PERMISSION_DENIED'):
            recovery.resume_stale_claim(self.d,self.f.other_token,self.evidence)

    def test_reserved_never_resumed(self):
        self.resume()
        scope=ProductionScope(self.d,self.job,self.nonce,self.f.root/'scope')
        reserve_once(OperationsStore(self.f.store.path),self.job,scope)
        self.d.block(self.job,'unknown')
        with self.assertRaisesRegex(PermissionError,'ALREADY_RESERVED_NO_RECOVERY'):
            self.resume()

    def test_other_failure_denied(self):
        self.d.block(self.job,'OTHER_ERROR')
        with self.assertRaisesRegex(PermissionError,'ONLY_ORIGINAL_ZERO_SUBMIT'):
            self.resume()

    def test_reupload_or_reselect_not_allowed(self):
        self.evidence['skip_video_write']=False
        with self.assertRaisesRegex(PermissionError,'FRESH_READONLY'):
            self.resume()
