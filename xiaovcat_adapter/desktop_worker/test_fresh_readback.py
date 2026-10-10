"""纯Mock回读测试：不连接窗口；stale只重读，绝不重做写入。"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock,patch
from .fresh_readback import fresh_read,is_stale
from .v04_prepare import PrepareUI


class FreshReadTests(unittest.TestCase):
    def test_two_reobservations_then_success(self):
        reader=Mock(side_effect=[RuntimeError('STALE_ELEMENT'),RuntimeError('控件已消失，必须重新观察'),'ok'])
        events=[]
        with patch('xiaovcat_adapter.desktop_worker.fresh_readback.time.sleep'):
            self.assertEqual(fresh_read(reader,label='fixture',audit=events.append),'ok')
        self.assertEqual(reader.call_count,3)
        self.assertEqual(events[-1]['reobservations'],2)
        self.assertTrue(all(e['write_replays']==0 for e in events))

    def test_exhausted_stale_is_unstable(self):
        reader=Mock(side_effect=RuntimeError('stale element'))
        with patch('xiaovcat_adapter.desktop_worker.fresh_readback.time.sleep'):
            with self.assertRaisesRegex(RuntimeError,'UI_STATE_UNSTABLE'):
                fresh_read(reader,label='fixture')
        self.assertEqual(reader.call_count,3)

    def test_nonstale_dialog_permission_mismatch_not_retried(self):
        for error in (PermissionError('ACCOUNT_PERMISSION_DENIED'),RuntimeError('UNKNOWN_DIALOG'),RuntimeError('PROFILE_TEXT_READBACK_MISMATCH')):
            reader=Mock(side_effect=error)
            with self.assertRaises(type(error)):fresh_read(reader,label='fixture')
            self.assertEqual(reader.call_count,1)

    def test_hresult_stale(self):
        error=RuntimeError('opaque COM error');error.hresult=-2147220991
        self.assertTrue(is_stale(error))
        self.assertFalse(is_stale(RuntimeError('UIA_TREE_TRUNCATED')))

    def test_wrong_state_never_assumed_success(self):
        with self.assertRaisesRegex(RuntimeError,'UI_STATE_UNSTABLE'):
            fresh_read(lambda:'wrong',label='fixture',accept=lambda actual:actual=='expected')

    def test_state_polling_is_readonly(self):
        reader=Mock(side_effect=['loading','expected']);write=Mock()
        with patch('xiaovcat_adapter.desktop_worker.fresh_readback.time.sleep'):
            self.assertEqual(fresh_read(reader,label='fixture',accept=lambda v:v=='expected',timeout=5),'expected')
        write.assert_not_called()

    def test_field_write_once_then_fresh_read_even_if_old_pattern_dies(self):
        with TemporaryDirectory() as folder:
            ui=object.__new__(PrepareUI);ui.results=Path(folder);ui.uia=Mock()
            ui.require_bound_scope=Mock();ui.reveal=Mock();ui.find=Mock(return_value={})
            old=Mock(CurrentIsReadOnly=False,CurrentValue='old')
            ui.element=Mock();ui.element.return_value.GetCurrentPattern.return_value.QueryInterface.return_value=old
            ui.current_value=Mock(side_effect=[RuntimeError('STALE_ELEMENT'),'wanted','wanted','wanted','wanted'])
            with patch('xiaovcat_adapter.desktop_worker.fresh_readback.time.sleep'):
                ui.fill_bound_profile({'title':'wanted','description':'wanted'})
            self.assertEqual(old.SetValue.call_count,4) # 每个字段1次，无回放。
            self.assertEqual(ui.current_value.call_count,5)

    def test_already_correct_fields_skip_all_writes(self):
        with TemporaryDirectory() as folder:
            ui=object.__new__(PrepareUI);ui.results=Path(folder);ui.uia=Mock()
            ui.require_bound_scope=Mock();ui.reveal=Mock();ui.find=Mock(return_value={})
            old=Mock(CurrentIsReadOnly=False,CurrentValue='same')
            ui.element=Mock();ui.element.return_value.GetCurrentPattern.return_value.QueryInterface.return_value=old
            ui.current_value=Mock(return_value='same')
            ui.fill_bound_profile({'title':'same','description':'same'})
            old.SetValue.assert_not_called()

    def test_snapshot_discards_entire_stale_frame(self):
        with TemporaryDirectory() as folder:
            ui=object.__new__(PrepareUI);ui.results=Path(folder);ui.hwnd=1
            ui._observe_once=Mock(side_effect=[RuntimeError('控件已消失，必须重新观察'),{'nodes':[],'values':{'fresh':'correct'}}])
            with patch('xiaovcat_adapter.desktop_worker.v04_prepare.screenshot'),patch('xiaovcat_adapter.desktop_worker.fresh_readback.time.sleep'):
                result=ui.observe('fixture')
            self.assertEqual(result['values'],{'fresh':'correct'})
            self.assertEqual(ui._observe_once.call_count,2)

    def test_submit_reservation_and_invoke_logic_not_modified(self):
        import ast
        root=Path(__file__).parent
        old=ast.parse((root/'v04_submit.py.stale-readback-20261005.bak').read_text('utf-8'))
        new=ast.parse((root/'v04_submit.py').read_text('utf-8'))
        for name in ('reserve_once','execute_once','validate_and_prepare'):
            a=next(n for n in old.body if isinstance(n,ast.FunctionDef) and n.name==name)
            b=next(n for n in new.body if isinstance(n,ast.FunctionDef) and n.name==name)
            # 仅允许证据开关/返回时间/撤销内存授权；reserve与唯一Invoke仍逐句锁定。
            class EvidenceOnly(ast.NodeTransformer):
                def visit_If(self,node):
                    if ast.unparse(node.test)=="getattr(store, 'lan_repository', False)":
                        return [self.visit(item) for item in node.orelse]
                    if ast.unparse(node.test)=="getattr(ready_scope, 'capture_screenshots', True)":
                        return node.body
                    if ast.unparse(node.test)=="callable(getattr(ready_scope, 'on_submit_permission_revoked', None))":
                        return None
                    return self.generic_visit(node)
                def visit_Assign(self,node):
                    if len(node.targets)==1 and ast.unparse(node.targets[0])=="report['submit_returned_at']":
                        return None
                    return self.generic_visit(node)
            b=EvidenceOnly().visit(b)
            self.assertEqual(ast.dump(a,include_attributes=False),ast.dump(b,include_attributes=False))
