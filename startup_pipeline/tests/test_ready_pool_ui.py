"""待发布池页面隔离回归；不读取生产队列、不生成草稿或提交任务。"""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from streamlit.testing.v1 import AppTest
import test_pipeline
from startup_pipeline.ui import ready_candidates


class ReadyPoolUiTests(unittest.TestCase):
    def setUp(self):
        self.f = test_pipeline.PipelineTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.media = {'streams': [{'codec_type': 'video', 'codec_name': 'h264', 'width': 1080, 'height': 1920}],
                      'format': {'format_name': 'mov,mp4', 'duration': '1.0'}}
        with self.f.store.connect(write=True) as db:
            db.execute('UPDATE startup_contents SET media_json=?', (json.dumps(self.media),))
            db.execute('INSERT INTO startup_batches VALUES(?,?,?,?,?)',
                       ('zzz-latest-pending', self.f.employee, str(self.f.root / 'pending_manifest.json'), '2026-10-04T20:00:00+08:00', '[]'))
            self.pending = 'STARTUP-' + str(uuid4())
            db.execute("INSERT INTO startup_contents(content_id,batch_id,video_index,composition_signature,created_at,business_type,production_status,publish_status,materials_json) VALUES(?, 'zzz-latest-pending',1,'pending-signature','2026-10-04T20:00:00+08:00','STARTUP','GENERATING','NOT_SCHEDULED','[]')", (self.pending,))
            generation = db.execute('SELECT generation_id FROM startup_content_bindings LIMIT 1').fetchone()[0]
            db.execute('INSERT INTO startup_content_bindings VALUES(?,?,?,?,?,NULL)',
                       (self.pending, generation, 'A1', 'A1', '丙曜起号10月4日-28'))
        for name, kwargs in [
            ('startup_pipeline.account_binding.render_states', {'return_value': {}}),
            ('startup_pipeline.service.probe_video', {'side_effect': self.f.fake_probe}),
        ]:
            mocked = patch(name, **kwargs)
            mocked.start()
            self.addCleanup(mocked.stop)

    def app(self):
        app = AppTest.from_string(
            'import streamlit as st\n'
            'from publish_planner.storage import PlannerStore\n'
            'from startup_pipeline.ui import pool,render_plan\n'
            f'store=PlannerStore({str(self.f.store.path)!r})\n'
            "st.radio('工作区',['素材工作台','发布管理'],key='workspace_mode')\n"
            'pool(st,store)\n'
            "if st.session_state.get('startup_content_ids'):\n"
            "    render_plan(st,store,st.session_state.planner_session,store.principal(st.session_state.planner_session))\n",
            default_timeout=30)
        app.session_state['planner_session'] = self.f.token
        app.run()
        self.assertFalse(app.exception, [e.message for e in app.exception])
        return app

    def assert_no_jobs(self):
        self.assertEqual(self.f.store.jobs(self.f.token), [])

    def test_latest_nonready_does_not_hide_three_historical_ready(self):
        app = self.app()
        self.assertEqual(next(s for s in app.selectbox if s.label == '起号批次').value, 'zzz-latest-pending')
        options = next(m for m in app.multiselect if m.label == '选择起号成片（可多选）')
        self.assertEqual(len(options.options), 3)
        self.assertTrue(next(b for b in app.button if b.label == '本批次全部加入发布').disabled)
        self.assert_no_jobs()

    def test_no_ready_disables_all_actions_and_explains(self):
        with self.f.store.connect(write=True) as db:
            db.execute("UPDATE startup_contents SET production_status='GENERATING'")
        app = self.app()
        for label in ['加入发布', '本批次全部加入发布', '批量安排发布']:
            self.assertTrue(next(b for b in app.button if b.label == label).disabled)
        self.assertTrue(any('当前没有可发布的READY成片' in i.value for i in app.info))
        self.assert_no_jobs()

    def select_three(self, app):
        next(m for m in app.multiselect if m.label == '选择起号成片（可多选）').set_value(self.f.ids).run()
        self.assertFalse(app.exception, [e.message for e in app.exception])

    def test_add_three_enters_original_planner_without_job(self):
        app = self.app()
        self.select_three(app)
        next(b for b in app.button if b.label == '加入发布').click().run()
        self.assertFalse(app.exception, [e.message for e in app.exception])
        self.assertEqual(app.session_state['startup_content_ids'], self.f.ids)
        self.assertEqual(app.session_state['workspace_mode'], '发布管理')
        self.assertEqual(next(m for m in app.multiselect if m.label == '选择MP4/已有成片').value, self.f.paths)
        self.assertTrue(any('已带入3条成片' in x.value for x in app.success))
        self.assert_no_jobs()

    def test_batch_schedule_three_enters_planner_without_job(self):
        app = self.app()
        self.select_three(app)
        next(b for b in app.button if b.label == '批量安排发布').click().run()
        self.assertFalse(app.exception, [e.message for e in app.exception])
        self.assertEqual(app.session_state['startup_content_ids'], self.f.ids)
        self.assert_no_jobs()

    def test_all_batch_uses_callback_before_workspace_widget(self):
        app = self.app()
        next(s for s in app.selectbox if s.label == '起号批次').set_value('fixture-batch').run()
        next(b for b in app.button if b.label == '本批次全部加入发布').click().run()
        self.assertFalse(app.exception, [e.message for e in app.exception])
        self.assertEqual(app.session_state['startup_content_ids'], self.f.ids)
        self.assertEqual(app.session_state['workspace_mode'], '发布管理')
        self.assert_no_jobs()

    def test_expired_snapshot_keeps_ready_and_blocks_plan_confirmation(self):
        with self.f.store.connect(write=True) as db:
            db.execute("UPDATE xiaovcat_accounts SET last_synced_at='2020-01-01T00:00:00+00:00'")
        app = self.app()
        self.assertTrue(any('视频已READY，但发布账号快照已过期' in w.value for w in app.warning))
        self.select_three(app)
        next(b for b in app.button if b.label == '批量安排发布').click().run()
        self.assertFalse(app.exception, [e.message for e in app.exception])
        self.assertTrue(next(b for b in app.button if b.label == '确认发布计划').disabled)
        self.assert_no_jobs()

    def test_submitted_and_failed_and_missing_files_not_options(self):
        with self.f.store.connect(write=True) as db:
            db.execute("UPDATE startup_contents SET publish_status='SUBMITTED' WHERE content_id=?", (self.f.ids[0],))
            db.execute("UPDATE startup_contents SET production_status='RENDER_FAILED' WHERE content_id=?", (self.f.ids[1],))
        Path(self.f.paths[2]).unlink()
        self.assertEqual(ready_candidates({r['content_id']: r for r in self.f.pipeline.contents(self.f.token)}), {})

    def test_invalid_probe_or_changed_file_not_options(self):
        with self.f.store.connect(write=True) as db:
            db.execute("UPDATE startup_contents SET media_json='{}' WHERE content_id=?", (self.f.ids[0],))
            db.execute("UPDATE startup_contents SET mtime_ns=0 WHERE content_id=?", (self.f.ids[1],))
        rows = ready_candidates({r['content_id']: r for r in self.f.pipeline.contents(self.f.token)})
        self.assertEqual(list(rows), [self.f.ids[2]])

    def test_other_employee_has_no_candidates(self):
        self.assertEqual(ready_candidates({r['content_id']: r for r in self.f.pipeline.contents(self.f.other_token)}), {})

    def test_refresh_reloads_ready_after_completion(self):
        app = self.app()
        with self.f.store.connect(write=True) as db:
            db.execute("UPDATE startup_contents SET production_status='GENERATING' WHERE content_id=?", (self.f.ids[2],))
        next(b for b in app.button if b.label == '刷新待发布池状态').click().run()
        self.assertEqual(len(next(m for m in app.multiselect if m.label == '选择起号成片（可多选）').options), 2)
        self.assert_no_jobs()


if __name__ == '__main__':
    unittest.main()
