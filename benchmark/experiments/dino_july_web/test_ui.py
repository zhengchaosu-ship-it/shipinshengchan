"""UI 回归测试：模拟搜索引擎，只用合成图片，不读索引、模型或原视频。"""
from io import BytesIO
from pathlib import Path
import shutil
import tempfile
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

from PIL import Image
import streamlit as st

# Streamlit AppTest 会创建临时媒体目录。固定在测试目录内，以继承工作区权限。
APPTEST_TEMP = Path(__file__).resolve().parent / ('.ui-apptest-' + uuid4().hex)
APPTEST_TEMP.mkdir(mode=0o777)
ORIGINAL_MKDTEMP = tempfile.mkdtemp


def workspace_mkdtemp(suffix=None, prefix=None, dir=None):
    path = APPTEST_TEMP / ((prefix or 'tmp') + uuid4().hex + (suffix or ''))
    path.mkdir(mode=0o777)
    return str(path)


tempfile.mkdtemp = workspace_mkdtemp
from streamlit.testing.v1 import AppTest
import search
import search_adapter
import text_adapter
import jianying_adapter
from benchmark.feedback import store as feedback_store

HERE = Path(__file__).resolve().parent


def tearDownModule():
    tempfile.mkdtemp = ORIGINAL_MKDTEMP
    shutil.rmtree(APPTEST_TEMP)


def fixture_rows(folder):
    image = Path(folder) / 'sample.png'
    Image.new('RGB', (640, 360), '#cbd9ca').save(image)
    return [dict(video_id=7, index_id=i, timestamp=120.125 + i,
                 similarity=.912345 - i * .1,
                 file_name=f'七月直播素材_测试画面_{i + 1:02d}.ts',
                 file_path=f'example/七月直播素材/测试视频_{i + 1:02d}.ts',
                 image=str(image)) for i in range(3)]


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        st.cache_resource.clear()
        self.folder = HERE / ('.ui-test-' + uuid4().hex)
        self.folder.mkdir(mode=0o777)
        self.addCleanup(self.cleanup_folder)
        test_config = self.folder / 'search_config.json'
        test_config.write_text('{"search_index":"july_test"}', encoding='utf-8')
        config_patch = patch.object(search_adapter, 'CONFIG_FILE', test_config)
        config_patch.start()
        self.addCleanup(config_patch.stop)
        db_patch = patch.object(feedback_store, 'DEFAULT_DB', self.folder / 'search_feedback.db')
        db_patch.start()
        self.addCleanup(db_patch.stop)
        self.rows = fixture_rows(self.folder)
        self.addCleanup((self.folder / 'sample.png').unlink)
        self.catalog = SimpleNamespace(videos={7: {}}, ids=range(3))
        self.dino = Mock(encoder=SimpleNamespace(device='mock'))
        self.dino.search.return_value = self.rows
        self.text = Mock(encoder=SimpleNamespace(device='mock'))
        self.text.search.return_value = (self.rows, 'A treatment scene.', ['词表提示'])
        self.text_backend = Mock(key='clip_formal_v1')
        self.text_backend.summary.return_value = search_adapter.CatalogSummary(
            'clip_formal_v1', '正式文字素材库', 319, 362752, True,
            duration_hours=506.85, index_label='CLIP formal_v1', item_label='个素材')
        self.text_backend.text_engine.return_value = search_adapter.TextEngineAdapter(self.text)
        text_patch = patch.object(text_adapter, 'load_text_adapter', return_value=self.text_backend)
        text_patch.start()
        self.addCleanup(text_patch.stop)
        self.generate_draft = Mock(return_value={
            'draft_name': '组合9-自动合成',
            'draft_path': r'C:\Jianying\组合9-自动合成',
            'duration_seconds': 12.5,
            'elapsed_seconds': 3.2,
            'mode': '引流 → 手法 → 手法 → 坐诊 → 收尾',
            'log': '模拟生成完成',
            'selected_materials': [
                {'index': i, 'category': category, 'file_name': f'素材{i}.mp4',
                 'path': rf'E:\素材\素材{i}.mp4'}
                for i, category in enumerate(['引流', '手法', '手法', '坐诊', '收尾'], 1)
            ],
            'selection_warnings': [],
        })
        generation_patch = patch.object(jianying_adapter, 'generate_draft', self.generate_draft)
        generation_patch.start()
        self.addCleanup(generation_patch.stop)
        def generate_batch(sequence, count, progress_callback=None, generation_context=None):
            videos = []
            for video_index in range(1, count + 1):
                if progress_callback:
                    progress_callback(video_index, count, 'running')
                materials = [
                    {'index': i, 'category': category,
                     'file_name': f'素材{video_index}-{i}.mp4',
                     'path': rf'E:\素材\素材{video_index}-{i}.mp4'}
                    for i, category in enumerate(sequence, 1)
                ]
                videos.append({
                    'video_index': video_index, 'status': 'success',
                    'slot_sequence': list(sequence),
                    'composition_signature': f'signature-{video_index}',
                    'selected_materials': materials, 'selection_warnings': [],
                    'draft_name': f'组合{video_index}-自动合成',
                    'draft_path': rf'C:\Jianying\组合{video_index}-自动合成',
                    'duration_seconds': 12.5, 'elapsed_seconds': 3.2, 'error': '',
                })
                if progress_callback:
                    progress_callback(video_index, count, 'complete')
            return {
                'batch_id': '20260930_154500',
                'requested_count': count, 'success_count': count, 'failed_count': 0,
                'slot_sequence': list(sequence), 'warnings': [], 'videos': videos,
                'manifest_path': r'D:\video_search_tool\jianying_auto\runtime\batches\batch_manifest.json',
            }

        self.generate_batch = Mock(side_effect=generate_batch)
        # 页面布局测试只模拟已认证的交接边界；真实鉴权和幂等在registration测试覆盖。
        self.registration_begin = patch('startup_pipeline.ui.begin_generation', return_value={'generation_id':'fixture-run','employee_id':'fixture-employee','draft_names':['fixture-draft']})
        for target, value in [('render_session', {'employee_id': 'fixture-employee', 'role': 'EMPLOYEE'}), ('target_selector', 'fixture-account')]:
            shared = patch('startup_pipeline.workbench_session.' + target, return_value=value)
            shared.start(); self.addCleanup(shared.stop)
        self.registration_finish = patch('startup_pipeline.ui.finish_generation', return_value=[{'content_id':'fixture-content','render_job_id':'fixture-render','status':'RENDER_PENDING'}])
        self.begin_callback = self.registration_begin.start(); self.addCleanup(self.registration_begin.stop)
        self.finish_callback = self.registration_finish.start(); self.addCleanup(self.registration_finish.stop)
        batch_patch = patch.object(jianying_adapter, 'generate_batch', self.generate_batch)
        batch_patch.start()
        self.addCleanup(batch_patch.stop)
        summary_patch = patch.object(jianying_adapter, 'source_summary', return_value={
            '引流': {'count': 10, 'folder': r'E:\引流'},
            '手法': {'count': 44, 'folder': r'E:\手法'},
            '坐诊': {'count': 30, 'folder': r'E:\坐诊'},
            '收尾': {'count': 2, 'folder': r'E:\收尾'},
        })
        summary_patch.start()
        self.addCleanup(summary_patch.stop)
        for name, value in [('JulyCatalog', self.catalog), ('DinoSearch', self.dino), ('TextSearch', self.text)]:
            mock = patch.object(search, name, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)
        self.app = AppTest.from_file(str(HERE / 'app.py'), default_timeout=15).run()
        self.assertFalse(self.app.exception)

    def cleanup_folder(self):
        self.assertEqual(self.folder.resolve().parent, HERE)
        self.assertTrue(self.folder.name.startswith('.ui-test-'))
        shutil.rmtree(self.folder)

    def store(self):
        return feedback_store.FeedbackStore(self.folder / 'search_feedback.db')

    def click_label(self, label):
        next(button for button in self.app.button if button.label == label).click().run()
        self.assertFalse(self.app.exception)

    def submit_text(self, text='治疗肩颈的视频'):
        self.app.radio(key='search_mode').set_value('文字搜索').run()
        self.app.text_input(key='query_text').set_value(text)
        next(button for button in self.app.button if button.label == '搜索相关画面').click().run()
        self.assertFalse(self.app.exception)

    def test_initial_and_empty_input_do_not_load_engines(self):
        self.assertTrue(any('结果会显示在这里' in item.value for item in self.app.markdown))
        self.app.button(key='image_submit').click().run()
        self.assertEqual(len(self.app.warning), 1)
        self.submit_text(' ')
        self.assertEqual(len(self.app.warning), 1)
        search.DinoSearch.assert_not_called()
        search.TextSearch.assert_not_called()

    def test_unauthenticated_workbench_stops_before_workspace_and_search(self):
        st.cache_resource.clear()
        search.JulyCatalog.reset_mock()
        with patch('startup_pipeline.workbench_session.render_session', return_value=None):
            app = AppTest.from_file(str(HERE / 'app.py'), default_timeout=15).run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.radio), 0)
        self.assertEqual(len(app.file_uploader), 0)
        self.assertTrue(any('请先登录工作台' in item.value for item in app.info))
        search.JulyCatalog.assert_not_called()

    def test_jianying_mode_generates_draft_without_loading_search_engines(self):
        self.app.radio(key='search_mode').set_value('自动合成').run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any('草稿结果会显示在这里' in item.value for item in self.app.markdown))
        self.assertEqual(self.app.selectbox(key='jianying_generation_count').value, 1)
        self.assertEqual(list(self.app.selectbox(key='jianying_generation_count').options),
                         [str(value) for value in range(1, 11)])
        next(button for button in self.app.button if button.label == '生成剪映草稿').click().run()
        self.assertFalse(self.app.exception)
        call = self.generate_batch.call_args
        self.assertEqual(call.args, (['引流'], 1))
        self.assertTrue(call.kwargs['progress_callback'])
        self.assertTrue(any('成功1条，失败0条' in item.value for item in self.app.success))
        self.assertTrue(any('C:\\Jianying' in item.value for item in self.app.code))
        search.DinoSearch.assert_not_called()
        search.TextSearch.assert_not_called()

    def test_jianying_batch_count_changes_button_and_generates_each_video(self):
        self.app.radio(key='search_mode').set_value('自动合成').run()
        self.app.selectbox(key='jianying_segment_2').set_value('手法').run()
        self.app.selectbox(key='jianying_generation_count').set_value(3).run()
        self.assertTrue(any(button.label == '批量生成剪映草稿' for button in self.app.button))
        self.assertTrue(any('预计生成：3个剪映草稿' in item.value
                            for item in self.app.markdown))
        next(button for button in self.app.button if button.label == '批量生成剪映草稿').click().run()
        self.assertFalse(self.app.exception)
        call = self.generate_batch.call_args
        self.assertEqual(call.args, (['引流', '手法'], 3))
        self.assertTrue(any('成功3条，失败0条' in item.value for item in self.app.success))
        self.assertEqual(sum(item.value.startswith('### 视频') for item in self.app.markdown), 3)

    def test_jianying_slots_stop_after_first_empty(self):
        self.app.radio(key='search_mode').set_value('自动合成').run()
        self.assertEqual(list(self.app.selectbox(key='jianying_segment_1').options),
                         ['引流（10）', '手法（44）', '坐诊（30）', '收尾（2）'])
        self.assertEqual(list(self.app.selectbox(key='jianying_segment_2').options),
                         ['无', '引流（10）', '手法（44）', '坐诊（30）', '收尾（2）'])
        for index in range(3, 6):
            self.assertTrue(self.app.selectbox(key=f'jianying_segment_{index}').disabled)

        self.app.selectbox(key='jianying_segment_2').set_value('手法').run()
        self.assertFalse(self.app.selectbox(key='jianying_segment_3').disabled)
        self.app.selectbox(key='jianying_segment_3').set_value('坐诊').run()
        self.app.selectbox(key='jianying_segment_2').set_value('无').run()
        for index in range(3, 6):
            slot = self.app.selectbox(key=f'jianying_segment_{index}')
            self.assertEqual(slot.value, '无')
            self.assertTrue(slot.disabled)
        self.assertTrue(any('共1个片段' in item.value for item in self.app.caption))

    def test_jianying_custom_mode_requires_value(self):
        self.app.radio(key='search_mode').set_value('自动合成').run()
        next(button for button in self.app.button if button.label == '使用兼容字符串生成草稿').click().run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any('请输入自定义组合' in item.value for item in self.app.warning))
        self.generate_draft.assert_not_called()

    def test_registration_login_failure_never_starts_generation(self):
        self.begin_callback.side_effect = RuntimeError('STARTUP_LOGIN_OR_CONTEXT_REQUIRED')
        self.app.radio(key='search_mode').set_value('自动合成').run()
        self.click_label('生成剪映草稿')
        self.generate_batch.assert_not_called()
        self.generate_draft.assert_not_called()
        self.assertTrue(any('STARTUP_LOGIN_OR_CONTEXT_REQUIRED' in item.value for item in self.app.error))

    def test_registration_failure_is_not_all_complete(self):
        self.finish_callback.side_effect = RuntimeError('RENDER_JOB_CREATE_FAILED')
        self.app.radio(key='search_mode').set_value('自动合成').run()
        self.click_label('生成剪映草稿')
        self.generate_batch.assert_called_once()
        self.assertTrue(any('草稿已生成，但交接未完成' in item.value and 'RENDER_JOB_CREATE_FAILED' in item.value for item in self.app.error))
        self.assertFalse(self.app.success)

    def test_text_results_preserve_order_scores_paths_and_prompt(self):
        self.submit_text()
        self.text.search.assert_called_once_with('治疗肩颈的视频', k=20)
        normalized = self.app.session_state['search_result']['rows']
        self.assertEqual([row['file_path'] for row in normalized],
                         [row['file_path'] for row in self.rows])
        self.assertTrue(all(set(('asset_id', 'video_id', 'file_name', 'file_path',
                                'timestamp', 'similarity', 'thumbnail')) <= set(row)
                            for row in normalized))
        self.assertTrue(all(row['thumbnail'] for row in normalized))
        self.assertEqual([code.value for code in self.app.code], [r['file_path'] for r in self.rows])
        markup = '\n'.join(item.value for item in self.app.markdown)
        self.assertIn('00:02:00.125', markup)
        self.assertIn('0.912345', markup)
        self.assertEqual(len(self.app.image), 3)
        self.assertTrue(any('A treatment scene.' in item.value for item in self.app.text))
        self.assertEqual(self.store().records()[0]['index_version'], 'clip_formal_v1')
        self.assertEqual(self.store().records()[0]['query_type'], 'text')

    def test_unknown_chinese_fallback_hint_is_visible(self):
        self.text.search.return_value = (
            self.rows,
            'A photo of a product package visible in a livestream.',
            ['实体元数据：前列腺大力丸',
             '如果你想找视频里说到“前列腺大力丸”的位置，请使用【话术找原片】。'])
        self.submit_text('前列腺大力丸')
        captions = '\n'.join(item.value for item in self.app.caption)
        self.assertIn('话术找原片', captions)
        self.assertFalse(any('暂不支持未知表达' in item.value for item in self.app.caption))

    def test_text_unavailable_keeps_image_entry_working(self):
        self.text_backend.summary.side_effect = RuntimeError('CLIP不是READY')
        self.app.radio(key='search_mode').set_value('文字搜索').run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any('CLIP不是READY' in item.value for item in self.app.warning))
        self.assertTrue(next(button for button in self.app.button if button.label == '搜索相关画面').disabled)
        self.app.radio(key='search_mode').set_value('图片搜索').run()
        self.assertFalse(self.app.exception)
        self.assertFalse(self.app.button(key='image_submit').disabled)
        self.text.search.assert_not_called()

    def test_mode_switch_and_clear_results_do_not_search_again(self):
        self.submit_text()
        self.app.radio(key='search_mode').set_value('图片搜索').run()
        self.assertNotIn('search_result', self.app.session_state)
        self.submit_text()
        # 提交后的下一次渲染显示清空按钮。
        self.app.run()
        next(button for button in self.app.button if button.label == '清空结果').click().run()
        self.assertNotIn('search_result', self.app.session_state)
        self.assertEqual(self.text.search.call_count, 2)

    def test_empty_results_and_errors_replace_previous_results(self):
        self.text.search.return_value = ([], '', [])
        self.submit_text()
        self.assertTrue(any('暂时没有找到相关画面' in item.value for item in self.app.markdown))
        self.text.search.side_effect = ValueError('中文词表未覆盖')
        self.submit_text()
        self.assertIn('中文词表未覆盖', self.app.error[0].value)
        self.assertNotIn('search_result', self.app.session_state)

    def test_missing_thumbnail_and_html_filename(self):
        self.rows[0]['image'] = str(self.folder / 'missing.png')
        self.rows[0]['file_name'] = '<img src=x onerror=alert(1)>.ts'
        self.submit_text()
        markup = '\n'.join(item.value for item in self.app.markdown)
        self.assertIn('缩略图暂不可用', markup)
        self.assertIn('&lt;img', markup)
        self.assertNotIn('<img src=x', markup)
        self.assertEqual(len(self.app.code), 3)

    def test_image_submission_and_preview_do_not_repeat_search(self):
        image_bytes = BytesIO()
        Image.new('RGB', (16, 16), 'green').save(image_bytes, format='PNG')
        upload = SimpleNamespace(name='query.png', getvalue=lambda: image_bytes.getvalue())
        with patch.object(st, 'file_uploader', return_value=upload):
            self.app.run()
            self.app.button(key='image_submit').click().run()
            self.assertFalse(self.app.exception)
            self.dino.search.assert_called_once()
            self.app.button(key='preview_1').click().run()
            self.assertFalse(self.app.exception)
            self.assertTrue(any('本机播放器' in item.value for item in self.app.info))
            self.dino.search.assert_called_once()
            self.text.search.assert_not_called()
            record = self.store().records()[0]
            self.assertEqual(record['query_image'], image_bytes.getvalue())
            self.assertEqual(record['query_type'], 'image')
            self.assertEqual(record['query_name'], 'query.png')
            self.store().save_feedback(record['search_id'], 1, 120.125)
            from benchmark.run import load_cases
            cases = load_cases(self.store().export_cases())
            self.assertEqual(cases[0]['acceptable_video_ids'], [7])
            self.assertEqual(cases[0]['expected_timestamp'], 120.125)
            with Image.open(cases[0]['image']) as original:
                self.assertEqual(original.size, (16, 16))

    def test_feedback_survives_reruns_and_new_search_has_new_id(self):
        self.submit_text()
        search_id = self.app.session_state['search_result']['search_id']
        prefix = f'feedback_{search_id}_2'
        self.app.text_input(key=prefix + '_time').set_value('00:02:03.5')
        self.app.text_input(key=prefix + '_note').set_value('第二个素材正确')
        self.app.button(key=f'FormSubmitter:{prefix}-这是正确素材').click().run()
        self.assertFalse(self.app.exception)
        row = self.store().get_feedback(search_id)
        self.assertEqual((row['selected_rank'], row['video_id'], row['corrected_timestamp']), (2, 7, 123.5))
        self.assertEqual(row['note'], '第二个素材正确')
        self.app.run()
        self.assertEqual(len(self.store().records()), 1)
        self.text.search.assert_called_once()
        self.click_label('没有正确结果')
        row = self.store().get_feedback(search_id)
        self.assertEqual(row['feedback_status'], 'no_correct')
        self.assertIsNone(row['video_id'])
        self.assertIsNone(row['corrected_timestamp'])
        self.submit_text()
        self.assertNotEqual(self.app.session_state['search_result']['search_id'], search_id)
        self.assertEqual(len(self.store().records()), 2)
        self.assertIsNone(self.store().get_feedback(self.app.session_state['search_result']['search_id']))

    def test_invalid_feedback_then_blank_timestamp_and_csv(self):
        self.submit_text()
        search_id = self.app.session_state['search_result']['search_id']
        prefix = f'feedback_{search_id}_1'
        self.app.text_input(key=prefix + '_time').set_value('-1')
        self.app.button(key=f'FormSubmitter:{prefix}-这是正确素材').click().run()
        self.assertTrue(any('反馈未保存' in item.value for item in self.app.error))
        self.assertIsNone(self.store().get_feedback(search_id))
        self.app.text_input(key=prefix + '_time').set_value('')
        self.app.button(key=f'FormSubmitter:{prefix}-这是正确素材').click().run()
        self.assertIsNone(self.store().get_feedback(search_id)['corrected_timestamp'])
        self.click_label('导出反馈 CSV')
        exported = Path(self.app.session_state['feedback_export'])
        self.assertEqual(exported.parent, self.folder / 'exports')
        self.assertIn(search_id, exported.read_text(encoding='utf-8-sig'))
        self.text.search.assert_called_once()

    def test_empty_and_failed_searches_are_not_false_labels(self):
        self.text.search.return_value = ([], '', [])
        self.submit_text()
        self.click_label('没有正确结果')
        self.assertEqual(self.store().records()[0]['feedback_status'], 'no_correct')
        self.text.search.side_effect = ValueError('模拟搜索失败')
        self.submit_text()
        rows = self.store().records()
        self.assertEqual(rows[1]['search_status'], 'error')
        self.assertEqual(rows[1]['feedback_status'], 'unreviewed')

    def test_storage_failure_keeps_results_and_warns(self):
        with patch.object(feedback_store.FeedbackStore, 'finish_search', side_effect=OSError('模拟磁盘错误')):
            self.submit_text()
        self.assertEqual(len(self.app.session_state['search_result']['rows']), 3)
        self.assertTrue(any('记录未保存' in item.value for item in self.app.warning))
        self.assertFalse(any(button.label == '这是正确素材' for button in self.app.button))


if __name__ == '__main__':
    unittest.main()
