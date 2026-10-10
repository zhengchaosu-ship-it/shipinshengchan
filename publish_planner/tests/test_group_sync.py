"""只读同步安全闸门测试；不实例化COM，不触碰真实桌面。"""
from unittest.mock import Mock
import unittest
from xiaovcat_adapter.group_sync import GroupSyncUI


class SyncSafetyTests(unittest.TestCase):
    def reader(self, rows, truncated=False):
        reader = GroupSyncUI.__new__(GroupSyncUI)
        reader.ui = Mock()
        reader.ui.uia.tree.return_value = {"nodes": rows, "truncated": truncated, "read_errors": 0}
        return reader

    def test_final_submit_is_not_allowed(self):
        reader = self.reader([])
        with self.assertRaisesRegex(PermissionError, "READ_ONLY_NAVIGATION_ONLY"):
            reader.invoke({"name": "一键分发"})
        reader.ui.element.assert_not_called()

    def test_unknown_dialog_stops(self):
        reader = self.reader([{"control_type": 50032, "depth": 5, "offscreen": False, "name": "未知确认弹窗"}])
        with self.assertRaisesRegex(RuntimeError, "UNKNOWN_DIALOG"):
            reader.rows()

    def test_truncated_tree_stops(self):
        reader = self.reader([], truncated=True)
        with self.assertRaisesRegex(RuntimeError, "UIA_TREE_INCOMPLETE"):
            reader.rows()

    def test_non_unique_target_stops(self):
        row = {"password": False, "offscreen": False, "enabled": True, "name": "关闭"}
        reader = self.reader([row, row])
        with self.assertRaisesRegex(RuntimeError, "AMBIGUOUS_UI_TARGET"):
            reader.unique(lambda r: r["name"] == "关闭", [row, row])
