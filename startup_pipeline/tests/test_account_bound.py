"""账号绑定业务测试；仅临时库/Mock，无桌面输入、生产生成或发布。"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch, Mock
import test_pipeline
import test_registration
from startup_pipeline.account_binding import reserve, draft_name, guard_publish_job, require_account
from startup_pipeline.registration import StartupContentRegistration
from startup_render.common import output_relative, read


class BoundTests(unittest.TestCase):
    def setUp(self):
        self.f = test_pipeline.PipelineTests()
        self.f.setUp(); self.addCleanup(self.f.tearDown)

    def allocate(self, account='A1', day='2026-10-04'):
        return reserve(self.f.store, self.f.token, account, now=datetime.fromisoformat(day))

    def workbench_app(self, logged=True):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_string('import streamlit as st\nfrom publish_planner.storage import PlannerStore\n'
            'from startup_pipeline.workbench_session import render_session,target_selector\n'
            'store=PlannerStore(' + repr(str(self.f.store.path)) + ')\n'
            'render_session(st,store)\ntarget_selector(st,store)', default_timeout=30)
        if logged:
            app.session_state['planner_session'] = self.f.token
        app.run()
        self.assertEqual(len(app.exception), 0)
        return app

    def test_31_workbench_shared_session_and_authorized_selector(self):
        app = self.workbench_app()
        self.assertEqual(app.session_state['workbench_session']['employee_id'], self.f.employee)
        selector = next(x for x in app.selectbox if x.label == '目标STARTUP账号')
        self.assertEqual(selector.options, ['请选择目标账号', 'A1 · A1', 'A2 · A2'])
        self.assertIsNone(selector.value)
        self.assertFalse(any('MP4' in x.label for x in app.text_input))

    def test_32_workbench_not_logged_no_account_selector(self):
        app = self.workbench_app(False)
        self.assertFalse(any(x.label == '目标STARTUP账号' for x in app.selectbox))
        self.assertTrue(any('请先登录' in x.value for x in app.warning))

    def test_33_workbench_logout_clears_shared_session(self):
        app = self.workbench_app()
        next(x for x in app.button if x.label == '退出工作台登录').click().run()
        self.assertEqual(len(app.exception), 0)
        with self.assertRaises(PermissionError):
            self.f.store.principal(self.f.token)

    def test_01_first_name(self):
        self.assertEqual(draft_name('丙曜','STARTUP','2026-10-04',1), '丙曜起号10月4日-1')

    def test_02_second_sequence(self):
        a=self.allocate(day='2027-02-01'); b=self.allocate(day='2027-02-01')
        self.assertTrue(a['draft_names'][0].endswith('-1'))
        self.assertTrue(b['draft_names'][0].endswith('-2'))

    def test_03_independent_accounts(self):
        self.allocate(day='2027-02-01')
        self.assertTrue(self.allocate('A2','2027-02-01')['draft_names'][0].endswith('-1'))

    def test_04_next_day(self):
        self.allocate(day='2027-02-01')
        self.assertTrue(self.allocate(day='2027-02-02')['draft_names'][0].endswith('-1'))

    def test_05_concurrency(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            values=list(pool.map(lambda _:self.allocate(day='2027-02-03')['draft_names'][0],range(8)))
        self.assertEqual(len(set(values)),8)

    def test_06_missing_account(self):
        with self.assertRaisesRegex(PermissionError,'TARGET_ACCOUNT_REQUIRED'): self.allocate(None)

    def test_07_missing_login(self):
        with self.assertRaises(PermissionError): reserve(self.f.store,'','A1')

    def test_08_other_employee_account(self):
        with self.assertRaisesRegex(PermissionError,'ACCOUNT_PERMISSION_DENIED'): self.allocate('B1')

    def test_09_content_id_binding(self):
        self.assertEqual(self.f.pipeline.contents(self.f.token)[0]['target_account_id'],'A1')

    def test_10_snapshot_preserved_on_rename(self):
        with self.f.store.connect(write=True) as db:
            db.execute("UPDATE xiaovcat_accounts SET display_name='changed' WHERE account_id='A1'")
        self.assertEqual(self.f.pipeline.contents(self.f.token)[0]['target_account_name_snapshot'],'A1')

    def test_11_immutable_even_admin_sql(self):
        with self.assertRaisesRegex(sqlite3.IntegrityError,'IMMUTABLE'):
            with self.f.store.connect(write=True) as db:
                db.execute("UPDATE startup_content_bindings SET target_account_id='A2'")

    def test_12_mp4_inherits_draft_name(self):
        self.assertEqual(output_relative({'batch_id':'new','video_index':1,'target_account_id':'A1',
            'draft_name':'丙曜起号10月4日-1'}),'new/丙曜起号10月4日-1.mp4')

    def test_13_ready_pool_binding(self):
        self.assertTrue(all(r['production_status']=='READY' and r['target_account_id']=='A1'
                            for r in self.f.pipeline.contents(self.f.token)))

    def test_14_plan_cannot_retarget(self):
        with self.assertRaisesRegex(PermissionError,'ACCOUNT_BINDING_MISMATCH'):
            self.f.confirm(replace(self.f.plan,account_ids=('A2',)))
        self.assertEqual(self.f.store.jobs(self.f.token),[])

    def test_15_manual_mode_cannot_bypass(self):
        with self.assertRaisesRegex(PermissionError,'ACCOUNT_BINDING_MISMATCH'):
            self.f.store.create_plan(self.f.token,self.f.plan)

    def test_16_job_metadata_matches(self):
        self.f.confirm()
        with self.f.store.connect() as db:
            for job in self.f.store.jobs(self.f.token): guard_publish_job(db,job['job_id'])

    def test_17_worker_final_guard_mismatch(self):
        self.f.confirm()
        with self.f.store.connect(write=True) as db:
            db.execute("UPDATE publish_plan_items SET account_id='A2'")
        with self.f.store.connect() as db:
            with self.assertRaisesRegex(PermissionError,'ACCOUNT_BINDING_MISMATCH'):
                guard_publish_job(db,self.f.store.jobs(self.f.token)[0]['job_id'])

    def test_36_worker_mismatch_never_obtains_submit_control(self):
        from types import SimpleNamespace
        from xiaovcat_adapter.ui_driver import PywinautoDriver
        self.f.confirm()
        with self.f.store.connect(write=True) as db:
            db.execute("UPDATE publish_plan_items SET account_id='A2'")
        driver = object.__new__(PywinautoDriver)
        driver.config = {'real_publish_enabled':True, 'operations_db':str(self.f.store.path)}
        driver._control = Mock(side_effect=AssertionError('must never access desktop'))
        job = SimpleNamespace(job_id=self.f.store.jobs(self.f.token)[0]['job_id'])
        with self.assertRaisesRegex(PermissionError,'ACCOUNT_BINDING_MISMATCH'):
            driver._submit(job,1)
        driver._control.assert_not_called()

    def test_18_draft_snapshot_not_renamed(self):
        before=self.f.pipeline.contents(self.f.token)[0]['draft_name']
        with self.f.store.connect(write=True) as db:
            db.execute("UPDATE xiaovcat_accounts SET display_name='改昵称' WHERE account_id='A1'")
        self.assertEqual(self.f.pipeline.contents(self.f.token)[0]['draft_name'],before)

    def test_19_windows_filename(self):
        name=draft_name('a\\/:*?"<>|','STARTUP','2026-10-04',1)
        self.assertFalse(any(c in name for c in '\\/:*?"<>|'))

    def test_20_commerce_naming(self):
        self.assertEqual(draft_name('xxx','COMMERCE','2026-10-04',1),'xxx带货10月4日-1')

    def test_21_mixed_plan_blocked(self):
        with self.assertRaisesRegex(PermissionError,'ACCOUNT_BINDING_MISMATCH'):
            self.f.confirm(replace(self.f.plan,account_ids=('A1','A2')))

    def test_22_old_failed_batch_blocked(self):
        data=json.loads(self.f.manifest.read_text(encoding='utf-8')); data['batch_id']='20261004_003025'
        with self.f.store.connect(write=True) as db:
            with self.assertRaisesRegex(PermissionError,'FAILED_EVIDENCE'):
                self.f.pipeline._ingest(db,self.f.manifest,data,self.f.employee)

    def test_23_generation_reservation_no_jobs(self):
        self.allocate(day='2027-03-01')
        self.assertEqual(self.f.store.jobs(self.f.token),[])

    def test_24_real_publish_stays_false(self):
        from publish_planner.storage import ROOT
        self.assertFalse(read(ROOT/'xiaovcat_adapter/config.json')['real_publish_enabled'])

    def test_25_bound_content_cannot_manual_export(self):
        with self.assertRaisesRegex(PermissionError,'AUTOMATIC_RENDER_RECEIPT'):
            self.f.pipeline.register_export(self.f.token,self.f.ids[0],self.f.paths[0])

    def test_26_offline_production_allowed_publish_denied(self):
        with self.f.store.connect(write=True) as db: db.execute("UPDATE xiaovcat_accounts SET online_status='OFFLINE' WHERE account_id='A2'")
        self.assertEqual(self.allocate('A2')['target_account_id'],'A2')
        self.assertNotIn('A2',{a['account_id'] for a in self.f.pipeline.accounts(self.f.token)})

    def test_27_no_mp4_required_to_begin(self):
        value=self.allocate(day='2027-04-01')
        self.assertNotIn('video_path',value)
        self.assertEqual(value['business_type'],'STARTUP')


class RegisteredBindingTests(unittest.TestCase):
    def setUp(self):
        self.f=test_registration.RegistrationTests();self.f.setUp();self.addCleanup(self.f.doCleanups)

    def test_28_render_payload_binding(self):
        self.f.complete();payload=json.loads(self.f.jobs()[0][2])
        self.assertEqual(payload['target_account_id'],'A')
        self.assertEqual(payload['target_account_name_snapshot'],'丙曜')
        self.assertEqual(payload['draft_name'],self.f.context['draft_names'][0])

    def test_29_context_forgery_rejected(self):
        self.f.context['target_account_id']='other'
        with self.assertRaisesRegex(RuntimeError,'ACCOUNT_BINDING_MISMATCH'):self.f.complete()
        self.assertEqual(self.f.jobs(),[])

    def test_30_unbound_no_account_registration(self):
        with self.assertRaisesRegex(PermissionError,'TARGET_ACCOUNT_REQUIRED'):self.f.service.begin(self.f.token)

    def test_34_bound_host_receipt_enters_ready_without_publish(self):
        from startup_render.completion import register_completed
        from startup_render.common import digest
        self.f.complete()
        identity = json.loads(self.f.jobs()[0][2])
        target = self.f.root / 'received' / output_relative(identity)
        target.parent.mkdir(parents=True)
        target.write_bytes(b'isolated-fixture-not-a-real-video')
        media = {'video_path':str(target), 'duration_seconds':1, 'size_bytes':target.stat().st_size,
                 'mtime_ns':target.stat().st_mtime_ns, 'media':{'fixture':True}}
        receipt = {'export_status':'VALIDATED', 'media':{'sha256':digest(target),'size':target.stat().st_size}}
        config = {'result_root':str(self.f.root/'received'), 'operations_db':str(self.f.store.path)}
        with patch('startup_pipeline.service.probe_video', return_value=media):
            with self.assertRaisesRegex(PermissionError,'ACCOUNT_BINDING_MISMATCH'):
                register_completed(config, self.f.root, dict(identity,target_account_id='other'),receipt)
            result = register_completed(config,self.f.root,identity,receipt)
        self.assertEqual(result['content_status'],'READY_TO_PUBLISH')
        row = self.f.pipeline.contents(self.f.token)[0]
        self.assertEqual((row['production_status'],row['target_account_id']),('READY','A'))
        self.assertEqual(Path(row['video_path']).name,identity['draft_name']+'.mp4')
        self.assertEqual(self.f.store.jobs(self.f.token),[])

    def test_35_render_pool_reads_real_queue_state(self):
        from startup_pipeline.account_binding import render_states
        self.f.complete()
        key = self.f.jobs()[0][0]
        self.assertEqual(render_states(self.f.store,[key],self.f.queue.path)[key],'PENDING')
        with sqlite3.connect(self.f.queue.path) as db:
            db.execute("UPDATE jobs SET status='VERSION_DRIFT'")
        db.close()
        self.assertEqual(render_states(self.f.store,[key],self.f.queue.path)[key],'VERSION_DRIFT')


if __name__=='__main__':unittest.main()
