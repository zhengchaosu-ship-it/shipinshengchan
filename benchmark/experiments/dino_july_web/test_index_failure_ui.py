"""隔离搜索展示函数验收：不执行正式入口，不连接生产库或发起任务。"""
import ast
from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest

HERE = Path(__file__).parent


class SearchIsolationTests(unittest.TestCase):
    def test_one_catalog_failure_only_disables_its_own_search(self):
        source = (HERE / 'app.py').read_text('utf-8-sig')
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
                    and n.name == 'render_material_workspace')
        function = ast.get_source_segment(source, node)
        prefix = '''
import streamlit as st
from types import SimpleNamespace
from html import escape
from io import BytesIO
from PIL import Image
summary = SimpleNamespace(key='fixture',display_name='test',video_count=3,frame_count=10,
                         duration_hours=1,index_label='fixture',item_label='个素材')
def get_catalog(name):
    if name == FAILED: raise RuntimeError(name + ' missing index')
    return summary
catalog = lambda: get_catalog('图片搜索')
text_catalog = lambda: get_catalog('文字搜索')
speech_catalog = lambda state: get_catalog('话术搜索')
speech_config_state = 0
feedback_store = lambda: None
export_controls = lambda store: None
release_inactive_engines = lambda mode: None
index_startup_health = lambda: {}
clear_result = lambda: None
empty_state = lambda *a, **k: st.info(a[0])
jianying_adapter = SimpleNamespace(enabled=lambda:False)
'''
        labels = {'图片搜索':'搜索相似画面','文字搜索':'搜索相关画面','话术搜索':'搜索原话'}
        for failed in labels:
            for mode, label in labels.items():
                with self.subTest(failed=failed, mode=mode):
                    app = AppTest.from_string('FAILED='+repr(failed)+'\n'+prefix+'\n'+function+
                                              '\nrender_material_workspace('+repr(mode)+')').run()
                    self.assertFalse(app.exception)
                    button = next(b for b in app.button if b.label == label)
                    self.assertEqual(button.disabled, mode == failed)
                    self.assertEqual(bool(app.warning), mode == failed)


if __name__ == '__main__':
    unittest.main()
