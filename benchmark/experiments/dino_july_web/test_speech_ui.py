"""话术 Beta 界面与故障隔离验证；不加载任何真实模型。"""
from unittest.mock import Mock, patch
import test_ui
from search_adapter import CatalogSummary
import speech_adapter


class SpeechUiTests(test_ui.WorkspaceTests):
    def test_speech_failure_isolated_from_image_and_clip(self):
        adapter=Mock()
        adapter.summary.side_effect=RuntimeError('话术搜索已单独关闭')
        with patch.object(speech_adapter,'load_speech_adapter',return_value=adapter):
            self.app.radio(key='search_mode').set_value('话术搜索').run()
            self.assertFalse(self.app.exception)
            self.assertTrue(next(b for b in self.app.button if b.label=='搜索原话').disabled)
            self.assertTrue(any('话术搜索暂不可用' in x.value for x in self.app.warning))
            self.app.radio(key='search_mode').set_value('图片搜索').run()
            self.assertFalse(self.app.exception)
            self.assertFalse(self.app.button(key='image_submit').disabled)
            self.submit_text()
            self.assertFalse(self.app.exception)
            self.assertEqual(len(self.app.session_state['search_result']['rows']),3)
            adapter.speech_engine.assert_not_called()

    def test_speech_top10_context_warning_feedback(self):
        adapter=Mock(key='speech_formal_v1')
        adapter.summary.return_value=CatalogSummary('speech_formal_v1','话术搜索 Beta',318,3099048,True)
        rows=[dict(asset_id='AST-T',video_id=7,source_video_id=7,file_name='测试.ts',file_path='测试.ts',
              start_time=12+i,end_time=14+i,timestamp=12+i,similarity=.9-i*.01,semantic_score=.9-i*.01,
              semantic_rank=i+1,matched_text='匹配原话',context_before='前一句',context_after='后一句',
              timestamp_warning=i==0,query_type='speech') for i in range(10)]
        adapter.speech_engine.return_value=Mock(device='cpu',search_with_timings=Mock(return_value=(rows,dict(total_ms=300))))
        with patch.object(speech_adapter,'load_speech_adapter',return_value=adapter):
            self.app.radio(key='search_mode').set_value('话术搜索').run()
            self.app.text_area(key='query_speech').input('测试原话')
            self.click_label('搜索原话')
            self.assertEqual(len(self.app.session_state['search_result']['rows']),10)
            self.assertEqual(sum(b.label=='预览原话 ↗' for b in self.app.button),10)
            self.assertTrue(any('原字幕时间偏差' in x.value for x in self.app.warning))
            self.assertTrue(any('前一句' in x.value for x in self.app.caption))
            self.click_label('这条是正确话术')
            sid=self.app.session_state['search_result']['search_id']
            self.assertEqual(self.store().get_feedback(sid)['asset_id'],'AST-T')
            self.click_label('Top10没有找到')
            self.assertEqual(self.store().get_feedback(sid)['feedback_status'],'no_correct')
