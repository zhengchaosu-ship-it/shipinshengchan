"""正式派发隔离回归；绝不连接真实GUI/账号/视频。"""
from concurrent.futures import ThreadPoolExecutor
import json
import unittest
from unittest.mock import patch
import test_pipeline
from startup_pipeline.production_dispatch import ProductionDispatcher, ProductionScope, migrate
from xiaovcat_adapter.desktop_worker.v04_submit import reserve_once
from xiaovcat_adapter.storage import OperationsStore


class ProductionDispatchTests(unittest.TestCase):
    def setUp(self):
        self.f = test_pipeline.PipelineTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        f = self.f
        _, receipt = f.pipeline.preview_receipt(f.token, f.plan, f.ids, f.profile)
        f.pipeline.confirm_plan(f.token, f.plan, f.ids, f.profile, expected_preview=receipt)
        self.d = ProductionDispatcher(f.store, probe=f.fake_probe)
        self.plan_id = f.plan.plan_id
        with f.store.connect() as db:
            self.jobs = [r[0] for r in db.execute('SELECT job_id FROM publish_plan_items ORDER BY scheduled_at')]

    def dry(self):
        return self.d.dry_dispatch(self.f.token, self.plan_id)

    def claim(self, job=None):
        return self.d.claim(self.f.token, self.plan_id, job or self.jobs[0], 'fixture-worker')

    def test_confirm_auto_enqueues_same_jobs_not_acceptance_scope(self):
        with self.f.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM startup_production_dispatch').fetchone()[0], 3)
            self.assertEqual(db.execute('SELECT count(*) FROM startup_real_acceptance_jobs').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0], 3)

    def test_dry_three_complete_no_submit_or_claim(self):
        result = self.dry()
        self.assertEqual(len(result['jobs']), 3)
        self.assertTrue(all(r['dispatchable'] for r in result['jobs']))
        for row in result['jobs']:
            self.assertEqual(row['policy']['account_id'], 'A1')
            self.assertEqual(row['policy']['execution_mode'], 'PRODUCTION')
            for field in ('video_path','scheduled_at','title','description','topics','content_id','business_type'):
                self.assertIn(field, row['policy'])
        self.assertEqual(result['final_submit_invocations'], 0)
        with self.f.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM state_events').fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM startup_production_dispatch WHERE state='QUEUED'").fetchone()[0], 3)

    def test_config_audit_preserves_ids_time_and_shared_template(self):
        before = self.dry()
        self.d.update_publish_config(self.f.token, self.plan_id, self.jobs, title='', description='陶老师小妙招', topics=['健康','健康科普','养生'])
        after = self.dry()
        self.assertEqual([(r['policy']['job_id'],r['policy']['scheduled_at']) for r in before['jobs']], [(r['policy']['job_id'],r['policy']['scheduled_at']) for r in after['jobs']])
        self.assertTrue(all(r['policy']['description']=='陶老师小妙招' for r in after['jobs']))
        with self.f.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM startup_publish_config_audit').fetchone()[0], 3)
            self.assertEqual(db.execute('SELECT description_template FROM startup_publish_profiles').fetchone()[0], '')

    def test_atomic_parallel_claim_only_one(self):
        def attempt(_):
            try:return self.claim()
            except PermissionError:return None
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sum(bool(n) for n in executor.map(attempt, range(2))), 1)
        with self.f.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM state_events WHERE step='PRODUCTION_ATOMIC_CLAIM'").fetchone()[0], 1)

    def test_repeated_claim_rejected_after_restart(self):
        self.claim()
        with self.assertRaisesRegex(PermissionError, 'ALREADY_CLAIMED'):
            ProductionDispatcher(self.f.store, probe=self.f.fake_probe).claim(self.f.token, self.plan_id, self.jobs[0], 'new-worker')

    def test_production_scope_independent_of_acceptance(self):
        token = self.claim()
        scope = ProductionScope(self.d, self.jobs[0], token, self.f.root/'results')
        self.assertEqual(scope.check(scope.policy), scope.policy)
        with self.assertRaisesRegex(PermissionError, 'PRODUCTION_CONTEXT_CHANGED'):
            scope.check(dict(scope.policy, account_id='A2'))

    def test_claim_nonce_cannot_be_forged(self):
        self.claim()
        with self.assertRaisesRegex(PermissionError, 'PRODUCTION_CLAIM_REQUIRED'):
            ProductionScope(self.d, self.jobs[0], 'wrong', self.f.root/'results')

    def test_repeat_confirm_after_config_and_claim_stays_idempotent(self):
        with self.f.store.connect() as db:
            receipt=db.execute('SELECT preview_receipt FROM startup_plan_confirmations WHERE plan_id=?',(self.plan_id,)).fetchone()[0]
        self.d.update_publish_config(self.f.token,self.plan_id,self.jobs,title='',description='陶老师小妙招',topics=['健康'])
        self.claim()
        result=self.f.pipeline.confirm_plan(self.f.token,self.f.plan,self.f.ids,self.f.profile,expected_preview=receipt)
        self.assertEqual(result['created'],0)
        self.assertTrue(result['idempotent'])
        with self.f.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0],3)
            self.assertEqual(db.execute("SELECT count(*) FROM startup_production_dispatch WHERE state='CLAIMED'").fetchone()[0],1)

    def test_existing_submit_ledger_still_at_most_once(self):
        token = self.claim()
        scope = ProductionScope(self.d, self.jobs[0], token, self.f.root/'results')
        reserve_once(OperationsStore(self.f.store.path), self.jobs[0], scope)
        with self.assertRaises(PermissionError):
            reserve_once(OperationsStore(self.f.store.path), self.jobs[0], scope)
        self.assertEqual(self.d.block(self.jobs[0], 'unknown-after-submit'), 'SUBMIT_RESULT_UNCERTAIN')
        with self.assertRaises(PermissionError):self.claim()

    def test_config_locked_after_claim(self):
        self.claim()
        with self.assertRaisesRegex(PermissionError, 'JOB_CONFIG_LOCKED'):
            self.d.update_publish_config(self.f.token, self.plan_id, self.jobs, title='', description='new', topics=[])

    def test_other_employee_denied(self):
        with self.assertRaisesRegex(PermissionError, 'PLAN_PERMISSION_DENIED'):
            self.d.dry_dispatch(self.f.other_token, self.plan_id)

    def test_expired_snapshot_stays_strict(self):
        with self.f.store.connect(write=True) as db:
            db.execute("UPDATE xiaovcat_accounts SET last_synced_at='2020-01-01T00:00:00+00:00' WHERE account_id='A1'")
        with self.assertRaisesRegex(PermissionError, 'PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED'):self.dry()

    def test_media_changed_denied(self):
        from pathlib import Path
        Path(self.f.paths[0]).write_bytes(b'changed-isolated-fixture-only')
        with self.assertRaisesRegex(PermissionError, 'REGISTERED_VIDEO_CHANGED'):self.dry()

    def test_not_confirmed_cannot_enqueue(self):
        with self.f.store.connect(write=True) as db:
            db.execute("UPDATE publish_plans SET status='TEST_ONLY' WHERE plan_id=?", (self.plan_id,))
        with self.assertRaisesRegex(PermissionError, 'CONFIRMED_STARTUP_PLAN_REQUIRED'):self.dry()

    def test_migration_repeat_no_job_creation(self):
        self.assertTrue(migrate(self.f.store)['already_applied'])
        with self.f.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0], 3)
            self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())

    def test_confirmed_schedule_remains_readable_after_claim_or_stale_snapshot(self):
        before = self.d.confirmed_schedule(self.f.token,self.plan_id)
        self.claim()
        with self.f.store.connect(write=True) as db:
            db.execute("UPDATE xiaovcat_accounts SET last_synced_at='2020-01-01T00:00:00+00:00' WHERE account_id='A1'")
        self.assertEqual(before,self.d.confirmed_schedule(self.f.token,self.plan_id))

    def test_prepare_failure_stops_without_claiming_other_jobs(self):
        from contextlib import nullcontext
        from xiaovcat_adapter.desktop_worker.production_worker import run_plan
        with patch('xiaovcat_adapter.desktop_worker.production_worker.settings',return_value={}), patch('xiaovcat_adapter.desktop_worker.production_worker.worker_lock',return_value=nullcontext()), patch('xiaovcat_adapter.desktop_worker.production_worker.existing_worker_supports',return_value=True):
            result=run_plan(self.d,self.f.token,self.plan_id,executor=lambda scope: (_ for _ in ()).throw(RuntimeError('fixture-pre-submit-failure')),results=self.f.root/'run')
        self.assertEqual(result['status'],'BLOCKED')
        with self.f.store.connect() as db:
            states=[r[0] for r in db.execute('SELECT state FROM startup_production_dispatch')]
            self.assertEqual(states.count('BLOCKED'),1)
            self.assertEqual(states.count('QUEUED'),2)
            self.assertEqual(db.execute("SELECT count(*) FROM state_events WHERE step='V04_FINAL_SUBMIT_RESERVED'").fetchone()[0],0)

    def test_unverified_worker_account_capability_does_not_claim(self):
        from contextlib import nullcontext
        from xiaovcat_adapter.desktop_worker.production_worker import run_plan
        with patch('xiaovcat_adapter.desktop_worker.production_worker.settings',return_value={}), patch('xiaovcat_adapter.desktop_worker.production_worker.worker_lock',return_value=nullcontext()):
            result=run_plan(self.d,self.f.token,self.plan_id,executor=lambda scope:self.fail('MUST_NOT_EXECUTE_UNSUPPORTED_ACCOUNT'),results=self.f.root/'unsupported')
        self.assertEqual(result['failure_code'],'EXISTING_WORKER_ACCOUNT_CAPABILITY_UNAVAILABLE')
        with self.f.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM startup_production_dispatch WHERE state='QUEUED'").fetchone()[0],3)

    def test_verified_result_three_jobs_serial_same_ids_and_times(self):
        def fake_executor(scope):
            reserve_once(OperationsStore(self.f.store.path),scope.job_id,scope)
            return dict(verified=True,job_id=scope.job_id,content_id=scope.policy['content_id'],account_id='A1',scheduled_at=scope.policy['scheduled_at'],task_status='已同步',final_submit_invocations=1)
        # 仅隔离库注入结果；不调用真实控件，不冒称实际发布。
        # 用仓库层逐条模拟可靠回执，保持真实runner账号能力检查不放宽。
        for job_id in self.jobs:
            nonce=self.claim(job_id)
            scope=ProductionScope(self.d,job_id,nonce,self.f.root/'result')
            proof=fake_executor(scope)
            self.assertEqual(self.d.record_scheduled_success(job_id,nonce,proof)['job_status'],'SCHEDULED_QUEUED')
            self.assertTrue(self.d.record_scheduled_success(job_id,nonce,proof)['idempotent'])
        with self.f.store.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM publish_jobs WHERE status='SCHEDULED_QUEUED'").fetchone()[0],3)
            self.assertEqual(db.execute("SELECT count(*) FROM startup_contents WHERE publish_status='SUBMITTED'").fetchone()[0],3)
            self.assertEqual(db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0],3)

    def test_unverified_result_cannot_mark_success(self):
        nonce=self.claim()
        with self.assertRaisesRegex(PermissionError,'RESULT_NOT_VERIFIED'):
            self.d.record_scheduled_success(self.jobs[0],nonce,{'verified':False})

    def test_existing_ready_action_control_calls_unchanged(self):
        import ast
        from pathlib import Path
        root=Path(__file__).resolve().parents[2]
        old=(root/'startup_render/runtime/closed_loop_20261004_post_login_01/publish_one.py.production-dispatch-20261004.bak').read_text('utf-8')
        new=(root/'xiaovcat_adapter/desktop_worker/ready_actions.py').read_text('utf-8')
        # 唯一授权增量为page子页导航；其它既有控件调用仍逐句比较。
        controls={'Invoke','Toggle','Select','SetValue','SetFocus','invoke','choose_original','fill_bound_profile','select_bound_account','confirm_exact_account','confirm_sync','set_schedule_preview','confirm_date_picker'}
        def calls(text):
            return sorted(ast.unparse(n) for n in ast.walk(ast.parse(text)) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in controls)
        self.assertEqual(calls(old),calls(new))

    def test_service_launch_passes_session_via_stdin_not_command_line(self):
        from unittest.mock import Mock
        child=Mock(pid=123)
        (self.f.root/'config.json').write_text(json.dumps({'paths':{'python_executable':'fixture-python'}}),'utf-8')
        dry=self.dry()
        with patch('startup_pipeline.service.ROOT',self.f.root), patch.object(self.f.pipeline,'dispatch_confirmed_publish_jobs',return_value=dry), patch('startup_pipeline.service.subprocess.Popen',return_value=child) as start:
            result=self.f.pipeline.start_confirmed_dispatch(self.f.token,self.plan_id)
        self.assertEqual(result['worker_pid'],123)
        command=start.call_args.args[0]
        self.assertIn('xiaovcat_adapter.desktop_worker.production_worker',command)
        self.assertNotIn(self.f.token,command)
        self.assertEqual(command[-3:],['--plan-id',self.plan_id,'--execute-confirmed'])
        child.stdin.write.assert_called_once_with((self.f.token+'\n').encode('utf-8'))
        child.stdin.close.assert_called_once()

    def test_control_automation_logic_unchanged(self):
        # 仅允许将验收验证调用替换为正式上下文验证；不改变任何UI控制语句。
        import ast
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        old = (root/'xiaovcat_adapter/desktop_worker/v04_prepare.py.production-dispatch-20261004.bak').read_text('utf-8')
        new = (root/'xiaovcat_adapter/desktop_worker/v04_prepare.py').read_text('utf-8')
        # normalize仅去除上下文加载和check调用，比较全部既有控件方法AST。
        def methods(text):
            tree = ast.parse(text)
            result = {}
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    for method in node.body:
                        # 20261005明确授权仅修这些动作后的只读回读/skip-write；其余原方法仍严格AST比较。
                        allowed={'__init__','require_bound_scope','single_video_form_ready','ensure_single_video_page',
                            'observe','_observe_once','readback_audit','reobserve','current_value','sync_item_state','general_topic_input_value','general_topics',
                            'general_scheduled','set_schedule_preview','choose_original','select_bound_account',
                            'fill_bound_profile','confirm_exact_account','disable_sync_item','confirm_sync','enable_default_cover_sync'}
                        if not isinstance(method, ast.FunctionDef) or method.name in allowed:continue
                        class Normalize(ast.NodeTransformer):
                            def visit_ImportFrom(self, n):
                                if n.module in {'startup_pipeline.single_acceptance','storage'}:return None
                                return n
                            def visit_Expr(self, n):
                                value = n.value
                                if isinstance(value, ast.Call):
                                    call = ast.unparse(value)
                                    if call.startswith('ReadyScope(') or call.startswith('self.require_bound_scope('):return None
                                return self.generic_visit(n)
                        result[method.name] = ast.dump(Normalize().visit(method), include_attributes=False)
            return result
        self.assertEqual(methods(old), methods(new))
