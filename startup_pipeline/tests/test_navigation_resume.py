"""一次性零提交恢复回归；隔离库，生产dispatcher源码不变。"""
import json
import unittest
from unittest.mock import patch
import test_production_dispatch as dispatch_tests
from startup_pipeline.runtime.batch3_publish_final import resume_navigation_job as recovery
from xiaovcat_adapter.storage import OperationsStore
from xiaovcat_adapter.desktop_worker.v04_submit import reserve_once
from startup_pipeline.production_dispatch import ProductionScope


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=dispatch_tests.ProductionDispatchTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.f=self.fixture.f
        self.d=self.fixture.d
        self.job=self.fixture.jobs[0]
        self.nonce=self.fixture.claim()
        self.d.block(self.job,'WAIT_FOR_STATE_TIMEOUT')
        evidence=self.f.root/'single_navigation_20261004'
        evidence.mkdir()
        (evidence/'RESULT.json').write_text(json.dumps(dict(status='JOB1_SINGLE_VIDEO_NAVIGATION_PASS',job_id=self.job,
            plan_id=self.fixture.plan_id,final_submit_invocations=0,navigation={'states':['XIAOVCAT_PUBLISH_FORM_READY']})),'utf-8')
        self.addCleanup(patch.stopall)
        patch.object(recovery,'OUT',self.f.root).start()
        patch.object(recovery,'PLAN',self.fixture.plan_id).start()
        patch.object(recovery,'JOBS',[(self.job,)]).start()

    def test_preserves_original_claim_and_no_new_job(self):
        with self.f.store.connect() as db:
            original=dict(db.execute('SELECT * FROM startup_production_dispatch WHERE job_id=?',(self.job,)).fetchone())
        self.assertEqual(recovery.resume_original_claim(self.d,self.f.token),self.nonce)
        scope=ProductionScope(self.d,self.job,self.nonce,self.f.root/'scope')
        scope.check(scope.policy)
        with self.f.store.connect() as db:
            current=dict(db.execute('SELECT * FROM startup_production_dispatch WHERE job_id=?',(self.job,)).fetchone())
            for key in ('claim_token','context_json','claimed_at','worker_id'):
                self.assertEqual(original[key],current[key])
            self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0],3)
            self.assertEqual(db.execute("SELECT count(*) FROM state_events WHERE step='V04_FINAL_SUBMIT_RESERVED'").fetchone()[0],0)

    def test_idempotent_same_claim(self):
        self.assertEqual(recovery.resume_original_claim(self.d,self.f.token),self.nonce)
        self.assertEqual(recovery.resume_original_claim(self.d,self.f.token),self.nonce)
        with self.f.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM state_events WHERE step='PRE_SUBMIT_NAVIGATION_RESUMED'").fetchone()[0],1)

    def test_other_employee_denied(self):
        with self.assertRaisesRegex(PermissionError,'PLAN_PERMISSION_DENIED'):
            recovery.resume_original_claim(self.d,self.f.other_token)

    def test_other_failure_never_resumed(self):
        self.d.block(self.job,'OTHER_ERROR')
        with self.assertRaisesRegex(PermissionError,'ONLY_ORIGINAL_ZERO_SUBMIT'):
            recovery.resume_original_claim(self.d,self.f.token)

    def test_reserved_never_resumed(self):
        recovery.resume_original_claim(self.d,self.f.token)
        scope=ProductionScope(self.d,self.job,self.nonce,self.f.root/'scope')
        reserve_once(OperationsStore(self.f.store.path),self.job,scope)
        self.d.block(self.job,'unknown')
        with self.assertRaisesRegex(PermissionError,'ALREADY_RESERVED_NO_RECOVERY'):
            recovery.resume_original_claim(self.d,self.f.token)

    def test_navigation_failure_never_resumed(self):
        path=self.f.root/'single_navigation_20261004/RESULT.json'
        evidence=json.loads(path.read_text('utf-8'))
        evidence['status']='FAIL'
        path.write_text(json.dumps(evidence),'utf-8')
        with self.assertRaisesRegex(PermissionError,'NAVIGATION_PASS_REQUIRED'):
            recovery.resume_original_claim(self.d,self.f.token)
