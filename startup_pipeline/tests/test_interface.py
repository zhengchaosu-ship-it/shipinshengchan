"""真实Streamlit组件接线测试，账号/内容/媒体探测均为隔离夹具。"""
from unittest.mock import patch
import json
from datetime import datetime, timezone
import unittest
import test_pipeline
from streamlit.testing.v1 import AppTest


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_pipeline.PipelineTests()
        self.fixture.setUp()
        f=self.fixture
        # 页面现在要求保留ffprobe视频流证据；仍为隔离媒体夹具，不探测生产文件。
        with f.store.connect(write=True) as db:
            db.execute('UPDATE startup_contents SET media_json=?', (json.dumps({
                'streams': [{'codec_type':'video','width':1080,'height':1920}],
                'format': {'format_name':'mp4','duration':'1.0'}}),))
        self.patch=patch('startup_pipeline.ui.StartupPipeline', lambda store=None: f.pipeline)
        self.patch.start()

    def tearDown(self):
        self.patch.stop();self.fixture.tearDown()

    def app(self, selected=False):
        f=self.fixture
        script="import streamlit as st\nfrom publish_planner.storage import PlannerStore\nfrom publish_planner.ui import render\nrender(st,PlannerStore("+repr(str(f.store.path))+"))"
        app=AppTest.from_string(script,default_timeout=30)
        app.session_state['planner_session']=f.token
        app.session_state['startup_pipeline_enabled']=True
        if selected:
            app.session_state['startup_content_ids']=f.ids
            app.session_state['planner_business_context']='STARTUP'
        app.run();self.assertEqual(len(app.exception),0)
        return app

    def find(self, elements, label):
        return next(x for x in elements if x.label==label)

    def test_pool_and_batch_all_direct_entry(self):
        app=self.app()
        self.assertIn('起号待发布池',[t.label for t in app.tabs])
        self.assertEqual(len(self.find(app.multiselect,'选择起号成片（可多选）').options),3)
        self.find(app.button,'本批次全部加入发布').click().run()
        self.assertEqual(len(app.exception),0)
        self.assertEqual(app.session_state['startup_content_ids'],self.fixture.ids)
        self.assertEqual(app.session_state['workspace_mode'],'发布管理')
        self.assertEqual(app.session_state['planner_business_context'],'STARTUP')

    def test_preselected_mp4_no_directory_hunting_and_correct_account_scope(self):
        app=self.app(selected=True)
        self.assertFalse(any(x.label=='本地成片目录' for x in app.text_input))
        self.assertEqual(self.find(app.multiselect,'选择MP4/已有成片').value,self.fixture.paths)
        self.assertTrue(self.find(app.multiselect,'选择MP4/已有成片').disabled)
        self.assertEqual(set(self.find(app.multiselect,'选择账号（稳定ID）').options),
                         {'A1 | 抖音 | 绑定锁定 · A1'})
        self.assertTrue(self.find(app.multiselect,'选择账号（稳定ID）').disabled)
        self.assertEqual(self.find(app.multiselect,'选择账号（稳定ID）').value, ['A1'])
        self.assertFalse(any(x.label=='计划业务类型' for x in app.selectbox))

    def test_preview_then_confirm_preserves_single_schedule_implementation(self):
        app=self.app(selected=True)
        self.assertTrue(self.find(app.multiselect,'选择账号（稳定ID）').disabled)
        self.find(app.number_input,'每天数量 daily_count').set_value(3)
        self.find(app.selectbox,'发布间隔').select('1小时').run()
        self.assertEqual(len(app.exception),0)
        self.assertTrue(any('预计生成任务：3条' in x.value for x in app.info))
        self.assertEqual(self.fixture.store.jobs(self.fixture.token),[])
        self.find(app.button,'确认发布计划').click().run()
        self.assertEqual(len(app.exception),0)
        self.assertEqual(len(self.fixture.store.jobs(self.fixture.token)),3)
        self.assertTrue(self.find(app.button,'确认发布计划').disabled)

    def test_one_and_multiple_content_entry_buttons(self):
        app=self.app()
        self.find(app.multiselect,'选择起号成片（可多选）').set_value(self.fixture.ids[:1]).run()
        self.assertFalse(self.find(app.button,'加入发布').disabled)
        self.find(app.button,'加入发布').click().run()
        self.assertEqual(app.session_state['startup_content_ids'],self.fixture.ids[:1])

    def test_forged_content_selection_stops_page(self):
        app=self.app(selected=True)
        app.session_state['startup_content_ids']=['unknown-content'];app.run()
        self.assertTrue(any('CONTENT_PERMISSION_DENIED' in x.value for x in app.error))
        self.assertFalse(any(x.label=='确认发布计划' for x in app.button))

    def expire(self):
        with self.fixture.store.connect(write=True) as db:
            db.execute("UPDATE xiaovcat_accounts SET last_synced_at='2020-01-01T00:00:00+00:00'")

    def test_bound_identity_survives_expired_snapshot_without_invalid_accounts(self):
        self.expire()
        app=self.app(selected=True)
        account=self.find(app.multiselect,'选择账号（稳定ID）')
        self.assertEqual(account.value,['A1'])
        self.assertEqual(account.options,['A1 | 抖音 | 绑定锁定 · A1'])
        self.assertTrue(account.disabled)
        self.assertTrue(any('PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED' in w.value for w in app.warning))
        self.assertFalse(any('INVALID_ACCOUNTS' in w.value for w in app.warning))
        self.assertTrue(self.find(app.button,'确认发布计划').disabled)
        self.assertFalse(self.find(app.button,'刷新发布账号').disabled)
        self.assertEqual(self.fixture.store.jobs(self.fixture.token),[])

    def test_planner_refresh_reuses_service_and_preserves_three_content_paths(self):
        self.expire()
        def refresh(store,token):
            self.assertEqual(token,self.fixture.token)
            with store.connect(write=True) as db:
                db.execute('UPDATE xiaovcat_accounts SET last_synced_at=?',(datetime.now(timezone.utc).isoformat(),))
        with patch('startup_pipeline.selector_refresh.refresh_startup_accounts',side_effect=refresh) as sync:
            app=self.app(selected=True)
            self.find(app.button,'刷新发布账号').click().run()
        self.assertEqual(len(app.exception),0)
        self.assertEqual(sync.call_count,1)
        self.assertEqual(app.session_state['startup_content_ids'],self.fixture.ids)
        self.assertEqual(self.find(app.multiselect,'选择MP4/已有成片').value,self.fixture.paths)
        self.assertFalse(self.find(app.button,'预览计划').disabled)
        self.assertEqual(self.find(app.number_input,'每天数量 daily_count').value,3)
        self.assertEqual(self.fixture.store.jobs(self.fixture.token),[])

    def test_failed_refresh_keeps_selection_and_reports_error(self):
        self.expire()
        with patch('startup_pipeline.selector_refresh.refresh_startup_accounts',side_effect=RuntimeError('ACCOUNT_SYNC_FAILED')):
            app=self.app(selected=True)
            self.find(app.button,'刷新发布账号').click().run()
        self.assertEqual(len(app.exception),0)
        self.assertEqual(app.session_state['startup_content_ids'],self.fixture.ids)
        self.assertTrue(any('ACCOUNT_SYNC_FAILED' in e.value for e in app.error))
        self.assertTrue(self.find(app.button,'确认发布计划').disabled)
        self.assertEqual(self.find(app.multiselect,'选择账号（稳定ID）').value,['A1'])

    def test_mixed_bound_accounts_report_specific_error(self):
        rows=self.fixture.pipeline.contents(self.fixture.token)
        rows[1]['target_account_id']='A2'
        with patch.object(self.fixture.pipeline,'contents',return_value=rows):
            app=self.app(selected=True)
        self.assertTrue(any('MULTIPLE_BOUND_ACCOUNTS' in e.value for e in app.error))
        self.assertFalse(any(b.label=='预览计划' for b in app.button))
        self.assertEqual(self.fixture.store.jobs(self.fixture.token),[])

    def test_saved_simulation_resumes_and_confirms_same_plan(self):
        self.fixture.confirm()
        with self.fixture.store.connect() as db:
            before = [r[0] for r in db.execute('SELECT job_id FROM publish_plan_items ORDER BY job_id')]
        app=self.app(selected=True)
        self.assertEqual(app.session_state['planner_draft_id'],self.fixture.plan.plan_id)
        self.assertTrue(any('预览 / 未确认' in x.value for x in app.info))
        self.assertFalse(any('CONTENT_ALREADY_SCHEDULED' in w.value for w in app.warning))
        self.assertTrue(self.find(app.date_input,'开始日期').disabled)
        self.assertFalse(self.find(app.button,'确认发布计划').disabled)
        self.find(app.button,'确认发布计划').click().run()
        self.assertEqual(len(app.exception),0)
        self.assertTrue(any('已确认，3个发布任务已创建' in s.value for s in app.success))
        self.assertTrue(self.find(app.button,'确认发布计划').disabled)
        with self.fixture.store.connect() as db:
            self.assertEqual(before,[r[0] for r in db.execute('SELECT job_id FROM publish_plan_items ORDER BY job_id')])
            self.assertEqual(db.execute('SELECT status FROM publish_plans').fetchone()[0],'CONFIRMED')

    def test_saved_simulation_reopens_after_session_selection_lost(self):
        self.fixture.confirm()
        app=self.app()
        self.assertEqual(self.find(app.selectbox,'已保存起号计划').value,self.fixture.plan.plan_id)
        self.find(app.button,'查看 / 继续当前起号计划').click().run()
        self.assertEqual(len(app.exception),0)
        self.assertEqual(set(app.session_state['startup_content_ids']),set(self.fixture.ids))
        self.assertEqual(app.session_state['planner_draft_id'],self.fixture.plan.plan_id)
        self.assertFalse(self.find(app.button,'确认发布计划').disabled)
        self.assertEqual(len(self.fixture.store.jobs(self.fixture.token)),3)


if __name__=='__main__':unittest.main()
