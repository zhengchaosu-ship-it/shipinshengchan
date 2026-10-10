"""隔离导航测试：没有真实窗口、没有表单填写和最终提交。"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from xiaovcat_adapter.desktop_worker.v04_prepare import PrepareUI


def row(rid, aid='', name='', kind=50033, parent='root', **kwargs):
    return dict(runtime_id=rid, automation_id=aid, name=name, control_type=kind,
                parent_id=parent, offscreen=False, password=False, enabled=True,
                class_name=kwargs.pop('class_name',''), **kwargs)


HISTORY = [row('pub','rc-tabs-1-panel-publish','Tab 3 of 10 send 一键发布'),
           row('hist','rc-tabs-8-panel-history',parent='pub'),
           row('post-tab','rc-tabs-8-tab-post','play-square 发单条视频',50019,'post-wrap'),
           row('history-tab','rc-tabs-8-tab-history','file-done 任务记录',50019,'hist-wrap'),
           row('post-wrap',kind=50026,parent='tabs',class_name='ant-tabs-tab'),
           row('hist-wrap',kind=50026,parent='tabs',class_name='ant-tabs-tab ant-tabs-tab-active'),
           row('tabs',kind=50018,parent='pub',class_name='ant-tabs-nav')]
READY = [HISTORY[0],row('post','rc-tabs-8-panel-post',parent='pub'),
         row('config',name='平台和账号配置'),
         row('upload',name='play-square 点击上传文件',kind=50000)]


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(dir=Path(__file__).resolve().parents[2])
        self.addCleanup(self.tmp.cleanup)
        self.ui = object.__new__(PrepareUI)
        self.ui.results = Path(self.tmp.name)
        self.ui.hwnd = 1
        self.ui.uia = Mock()
        self.ui.uia.descendants.side_effect = lambda rows, root: rows[1:]
        self.pattern = Mock(CurrentIsSelected=False)
        self.ui.element = Mock()
        self.ui.element.return_value.GetCurrentPattern.return_value.QueryInterface.return_value = self.pattern
        self.wait = patch('xiaovcat_adapter.desktop_worker.state_detector.wait_for').start()
        self.addCleanup(patch.stopall)

    def check(self, rows, later=READY):
        self.ui.rows = Mock(side_effect=[rows,later])
        return self.ui.ensure_single_video_page()

    def test_task_record_selects_unique_tab_once(self):
        result = self.check(HISTORY)
        self.assertEqual(result['states'],['XIAOVCAT_TASK_RECORD','XIAOVCAT_SINGLE_VIDEO_PUBLISH','XIAOVCAT_PUBLISH_FORM_READY'])
        self.assertEqual(result['navigation_invocations'],1)
        self.pattern.Select.assert_called_once()
        self.assertEqual(result['final_submit_invocations'],0)
        self.assertFalse(result['real_publish_enabled'])

    def test_ready_does_not_select_or_wait(self):
        self.assertEqual(self.check(READY)['navigation_invocations'],0)
        self.pattern.Select.assert_not_called()
        self.wait.assert_not_called()

    def test_post_loading_only_waits(self):
        result = self.check(READY[:2])
        self.assertEqual(result['navigation_invocations'],0)
        self.pattern.Select.assert_not_called()
        self.wait.assert_called_once()

    def test_selected_tab_not_reselected(self):
        self.pattern.CurrentIsSelected = True
        self.assertEqual(self.check(HISTORY)['navigation_invocations'],0)
        self.pattern.Select.assert_not_called()

    def test_multiple_tabs_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'SINGLE_VIDEO_TAB_NOT_UNIQUE'):
            self.check(HISTORY+[dict(HISTORY[2],runtime_id='duplicate')])
        self.pattern.Select.assert_not_called()

    def test_wrong_hierarchy_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'HIERARCHY_MISMATCH'):
            self.check(HISTORY[:3]+[dict(HISTORY[3],parent_id='other')]+HISTORY[4:])
        self.pattern.Select.assert_not_called()

    def test_wrong_name_id_type_or_hidden_rejected(self):
        for change in ({'name':'发单条视频假冒'},{'automation_id':'wrong'},
                       {'control_type':50000},{'offscreen':True},{'enabled':False}):
            with self.subTest(change=change):
                with self.assertRaisesRegex(RuntimeError,'XIAOVCAT_SINGLE_VIDEO_PAGE_NOT_REACHED'):
                    self.check(HISTORY[:2]+[dict(HISTORY[2],**change)]+HISTORY[3:])
        self.pattern.Select.assert_not_called()

    def test_timeout_is_specific_and_zero_submit(self):
        self.wait.side_effect = RuntimeError('WAIT_FOR_STATE_TIMEOUT')
        with self.assertRaisesRegex(RuntimeError,'XIAOVCAT_SINGLE_VIDEO_PAGE_NOT_REACHED'):
            self.check(HISTORY)
        saved=json.loads((self.ui.results/'SINGLE_VIDEO_NAVIGATION.json').read_text('utf-8'))
        self.assertEqual(saved['final_submit_invocations'],0)
        self.assertEqual(saved['states'][-1],'XIAOVCAT_SINGLE_VIDEO_PAGE_NOT_REACHED')

    def test_readback_not_ready_cannot_proceed(self):
        with self.assertRaisesRegex(RuntimeError,'FORM_READBACK_NOT_READY'):
            self.check(HISTORY,HISTORY)

    def test_missing_task_record_cannot_blind_select(self):
        with self.assertRaisesRegex(RuntimeError,'CURRENT_SUBPAGE_NOT_TASK_RECORD'):
            self.check(HISTORY[:1]+HISTORY[2:])
        self.pattern.Select.assert_not_called()


if __name__ == '__main__':
    unittest.main()
