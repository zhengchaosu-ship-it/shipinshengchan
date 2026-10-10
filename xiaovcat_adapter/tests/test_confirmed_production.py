"""正式Confirm→常驻执行→单次闩锁→核验；隔离DB及Mock UI，无真实发布。"""
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from xiaovcat_adapter.tests import test_server_resident as server_fixtures
from xiaovcat_adapter import server_resident as resident
from xiaovcat_adapter.desktop_worker.v04_submit import reserve_once
from xiaovcat_adapter.storage import OperationsStore
from xiaovcat_publish_worker import PublishWorker


class ConfirmedProductionTests(unittest.TestCase):
    def setUp(self):
        server_fixtures.ServerResidentTests.setUp(self)
        self.config.update(worker_enabled=True, authorization_mode=resident.PRODUCTION_MODE,
            allow_all_confirmed_plans=True, allowed_plan_ids=[], allowed_job_ids=[],
            production_authorized_after=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat())
        self.calls=[]

    def queue(self):
        return resident.ServerWorkerQueue(self.base.d,dict(self.config,production_execution_authorized=True),Mock())

    def cycle(self, publisher=None):
        path=self.f.root/'production.json'
        path.write_text(json.dumps(self.config),'utf-8')
        factory=Mock()
        def worker_factory(config,queue,**kwargs):
            return PublishWorker(config,queue,publisher_factory=publisher or factory,**kwargs)
        with patch('xiaovcat_publish_worker.single_instance',return_value=nullcontext()), \
             patch.object(resident,'ProductionDispatcher',return_value=self.base.d), \
             patch.object(resident,'require_batch_acceptance',side_effect=AssertionError('LEGACY_GATE_FORBIDDEN')):
            result=resident.run_server(path,once=True,worker_factory=worker_factory,
                session_check=Mock(return_value=dict(session_id=1,interactive_session_present=True,xiaovcat_process_present=True)))
        return result,factory

    def beat(self):
        return json.loads((Path(self.config['runtime_dir'])/'heartbeat.json').read_text('utf-8'))

    def publisher(self, scope, armed_check):
        outer=self
        class FixturePublisher:
            def prepare_job(self):
                armed_check();outer.assertFalse(outer.beat()['real_submit_armed']);outer.calls.append('prepare')
            def verify_form(self):
                outer.assertFalse(outer.beat()['real_submit_armed']);outer.calls.append('verify')
            def submit_once(self):
                armed_check()
                reserve_once(OperationsStore(outer.f.store.path),scope.job_id,scope)
                scope.on_reserved_submit_permission()
                outer.assertTrue(outer.beat()['real_submit_armed'])
                outer.calls.append('submit')
                scope.on_submit_permission_revoked()
                return dict(invoke_returned=True,final_submit_invocations=1)
            def reconcile_result(self,submitted):
                outer.assertFalse(outer.beat()['real_submit_armed']);outer.calls.append('reconcile')
                return dict(verified=True,status='SCHEDULED_QUEUED',job_id=scope.job_id,
                    content_id=scope.policy['content_id'],account_id=scope.policy['account_id'],
                    scheduled_at=scope.policy['scheduled_at'],task_status='已同步',final_submit_invocations=1)
        return FixturePublisher()

    def test_confirm_is_authority_not_retired_acceptance(self):
        result=resident.notify_confirmed_queue(self.f.store,self.f.token,self.base.plan_id,self.config)
        self.assertEqual(result['queued_jobs'],3)
        self.assertTrue(result['executor_enabled'])
        with self.f.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM startup_real_acceptance_jobs').fetchone()[0],0)

    def test_historical_confirmed_queue_is_excluded(self):
        self.config['production_authorized_after']=datetime.now(timezone.utc).isoformat()
        self.assertEqual(self.queue().discover(),[])
        result,factory=self.cycle();self.assertEqual(result['status'],'IDLE');factory.assert_not_called()
        self.assertFalse(self.beat()['real_submit_armed'])

    def test_preview_is_never_executable(self):
        with self.f.store.connect(write=True) as db:db.execute("UPDATE publish_plans SET status='TEST_ONLY'")
        self.assertEqual(self.queue().discover(),[])

    def test_terminal_jobs_are_never_consumed(self):
        with self.f.store.connect(write=True) as db:db.execute("UPDATE publish_jobs SET status='CANCELLED'")
        self.assertEqual(self.queue().discover(),[])

    def test_intent_without_attempt_cannot_claim(self):
        with self.f.store.connect(write=True) as db:
            db.execute("INSERT INTO state_events(job_id,step,attempt,outcome,started_at,duration_ms) VALUES(?,'SUBMIT_INTENT',1,'TEST',?,0)",
                (self.base.jobs[0],datetime.now(timezone.utc).isoformat()))
        with self.assertRaisesRegex(PermissionError,'RESERVED_NO_RETRY'):self.queue().claim(self.queue().discover()[0])

    def test_duplicate_content_plan_rejected_before_claim(self):
        with self.f.store.connect(write=True) as db:
            db.execute('UPDATE publish_plan_items SET content_id=? WHERE job_id=?',(self.f.ids[0],self.base.jobs[1]))
        with self.assertRaisesRegex(Exception,'DUPLICATE_CONTENT_SCHEDULE_BLOCKED'):self.queue().claim(self.queue().discover()[0])

    def test_same_account_time_collision_rejected_before_claim(self):
        with self.f.store.connect(write=True) as db:
            stamp=db.execute('SELECT scheduled_at FROM publish_plan_items WHERE job_id=?',(self.base.jobs[0],)).fetchone()[0]
            db.execute('UPDATE publish_plan_items SET scheduled_at=? WHERE job_id=?',(stamp,self.base.jobs[1]))
        with self.assertRaisesRegex(Exception,'ACCOUNT_TIME_COLLISION_BLOCKED'):self.queue().claim(self.queue().discover()[0])

    def test_three_serial_original_jobs_submit_once_and_idle_disarmed(self):
        for _ in range(3):
            result,_=self.cycle(self.publisher);self.assertTrue(result['verified'])
        result,factory=self.cycle();factory.assert_not_called();self.assertEqual(result['status'],'IDLE')
        self.assertEqual(self.calls,['prepare','verify','submit','reconcile']*3)
        self.assertFalse(self.beat()['real_submit_armed'])
        with self.f.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM publish_plans').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0],3)
            self.assertEqual(db.execute("SELECT count(*) FROM state_events WHERE step='V04_FINAL_SUBMIT_RESERVED'").fetchone()[0],3)
            self.assertEqual(db.execute("SELECT count(*) FROM publish_jobs WHERE status='SCHEDULED_QUEUED'").fetchone()[0],3)
            self.assertEqual(db.execute("SELECT count(*) FROM startup_contents WHERE publish_status='SUBMITTED'").fetchone()[0],3)

    def test_uncertain_result_halts_future_cycles_no_second_submit(self):
        def publisher(scope,armed_check):
            wrapped=self.publisher(scope,armed_check)
            wrapped.reconcile_result=lambda submitted:dict(verified=False,status='SUBMIT_RESULT_UNCERTAIN')
            return wrapped
        result,_=self.cycle(publisher);self.assertEqual(result['failure_code'],'SUBMIT_RESULT_UNCERTAIN')
        again,factory=self.cycle();factory.assert_not_called();self.assertEqual(again['status'],'HALTED_NEEDS_MANUAL')
        self.assertEqual(self.calls.count('submit'),1);self.assertFalse(self.beat()['real_submit_armed'])

    def test_disabled_production_never_calls_ui(self):
        self.config['worker_enabled']=False
        result,factory=self.cycle();factory.assert_not_called();self.assertEqual(result['status'],'DISABLED')

    def test_repeated_confirm_does_not_duplicate_or_recalculate(self):
        with self.f.store.connect() as db:
            receipt=db.execute('SELECT preview_receipt FROM startup_plan_confirmations').fetchone()[0]
        for _ in range(2):
            result=self.f.pipeline.confirm_plan(self.f.token,self.f.plan,self.f.ids,self.f.profile,expected_preview=receipt)
            self.assertTrue(result['idempotent']);self.assertEqual(result['created'],0)
        self.assertEqual(len(self.queue().discover()),3)

    def test_claimed_without_submit_never_replays_preparation(self):
        q=self.queue();q.claim(q.discover()[0])
        result,factory=self.cycle();factory.assert_not_called()
        self.assertEqual(result['failure_code'],'INTERRUPTED_PRE_SUBMIT_NO_WRITE_REPLAY')

    def test_existing_submit_implementation_grants_only_after_reserve(self):
        self.check_submit_hook()

    def test_submit_hook_failure_never_invokes_but_keeps_reservation(self):
        self.check_submit_hook(fail=True)

    def check_submit_hook(self,fail=False):
        from contextlib import redirect_stdout
        from io import StringIO
        from startup_pipeline.production_dispatch import ProductionScope
        from xiaovcat_adapter.desktop_worker import v04_submit as submit
        q=self.queue();row=q.discover()[0];nonce=q.claim(row)
        results=self.f.root/'hook-fixture';results.mkdir()
        scope=ProductionScope(self.base.d,row['job_id'],nonce,results);scope.capture_screenshots=False
        policy=scope.policy;stamp='fixture-confirmed-time'
        for name,value in {'LOCKED_REQUEST.json':policy,
            'ACCOUNT_RECHECK_FINAL.json':{'checked_at':datetime.now().astimezone().isoformat()},
            'SCHEDULE_PREVIEW.json':{'scheduled_at':policy['scheduled_at']},
            'ORIGINAL_FILE_SELECTION.json':{'size_bytes':Path(policy['video_path']).stat().st_size}}.items():
            (results/name).write_text(json.dumps(value),'utf-8')
        def grant():
            self.assertEqual(q.submission(scope.job_id)['submit_attempt_count'],1)
            self.calls.append('grant')
            if fail:raise PermissionError('FIXTURE_PERMISSION_REVOKED')
        scope.on_reserved_submit_permission=grant
        scope.on_submit_permission_revoked=lambda:self.calls.append('revoke')
        invoke=Mock();invoke.Invoke.side_effect=lambda:self.calls.append('invoke')
        ui=Mock();ui.element.return_value.GetCurrentPattern.return_value.QueryInterface.return_value=invoke
        ui.uia.tree.return_value={'nodes':[]}
        report=dict(status='READY_FOR_SINGLE_SUBMIT',all_checks_passed=True,job_id=scope.job_id,
            action_time_user_confirmation=scope.confirmation,scheduled_at=policy['scheduled_at'],ui_scheduled_at=stamp)
        with patch.object(submit,'live_snapshot',return_value={'nodes':[dict(control_type=50000,name='一键分发',enabled=True,offscreen=False,automation_id='submit')]}), \
             patch.object(submit,'settings'),patch.object(submit,'verify_evidence'), \
             patch.object(submit,'now_expected_ui_time',return_value=stamp),redirect_stdout(StringIO()):
            submit.execute_once(ui,OperationsStore(self.f.store.path),report,scope)
        self.assertEqual(self.calls,['grant','revoke'] if fail else ['grant','invoke','revoke'])
        self.assertEqual(invoke.Invoke.call_count,0 if fail else 1)
        self.assertEqual(q.submission(scope.job_id)['submit_attempt_count'],1)
        self.assertFalse(report['real_publish_enabled'])


if __name__=='__main__':unittest.main()
