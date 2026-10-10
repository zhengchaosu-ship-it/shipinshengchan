"""纯模拟安全回归：不启动应用、不点击 UI、不访问业务数据库。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from xiaovcat_adapter.desktop_worker import cdp_probe, electron_probe
from xiaovcat_adapter.desktop_worker.state_detector import NeedsManual, guard_dialogs, wait_for
from xiaovcat_adapter.desktop_worker.uia_probe import LocalUIA
from xiaovcat_adapter.desktop_worker.worker import DesktopWorker


class SafetyTests(unittest.TestCase):
    def test_disabled_publish_flag_required(self):
        with patch.object(electron_probe.Path, "read_text", return_value='{"real_publish_enabled": true}'):
            with self.assertRaises(PermissionError):
                electron_probe.settings()

    def test_existing_process_never_restarted(self):
        with patch.object(electron_probe, "_windows_processes", return_value=[Mock(pid=42)]), \
                patch.object(electron_probe.subprocess, "Popen") as popen:
            self.assertEqual(electron_probe.launch_test({"process_name": "test.exe"})["reason"], "ALREADY_RUNNING_NO_RESTART")
            popen.assert_not_called()

    def test_final_button_never_invoked(self):
        uia = LocalUIA.__new__(LocalUIA)
        for name in ("一键分发", "发布", "提交", "确认", "确 定", "保存列表", "存为草稿"):
            element = Mock(CurrentName=name)
            uia.resolve = Mock(return_value=element)
            with self.assertRaises(PermissionError):
                uia.invoke(42, "id", name)
            element.GetCurrentPattern.assert_not_called()

    def test_account_confirm_not_generic_click(self):
        uia = LocalUIA.__new__(LocalUIA)
        uia.tree = Mock(return_value={"nodes": []})
        with self.assertRaises(RuntimeError):
            uia.confirm_account_dialog(42)

    def test_unknown_dialog_stops(self):
        dialog = dict(control_type=50032, depth=5, offscreen=False, name="新弹窗", class_name="other")
        with self.assertRaises(NeedsManual):
            guard_dialogs([dialog], allow_account=True)

    def test_known_account_dialog_only_in_expected_step(self):
        dialog = dict(control_type=50032, depth=5, offscreen=False,
                      name="选择账号 以下只列出已支持发视频的媒体平台账号", class_name="post-account-modal")
        with self.assertRaises(NeedsManual):
            guard_dialogs([dialog])
        guard_dialogs([dialog], allow_account=True)

    def test_no_sleep_click_chain_after_timeout(self):
        uia = Mock()
        uia.tree.return_value = {"nodes": [], "truncated": False}
        with self.assertRaises(NeedsManual):
            wait_for(uia, 42, lambda rows:False, timeout=0)
        uia.invoke.assert_not_called()

    def test_truncated_tree_not_accepted(self):
        uia = Mock()
        uia.tree.return_value = {"nodes": [], "truncated": True}
        with self.assertRaises(NeedsManual):
            wait_for(uia, 42, lambda rows:True, timeout=1)

    def test_other_video_refused_before_root_access(self):
        uia = LocalUIA.__new__(LocalUIA)
        with self.assertRaises(PermissionError):
            uia.choose_test_file(42, Path("some_other.mp4"))

    def test_production_text_refused(self):
        uia = LocalUIA.__new__(LocalUIA)
        with self.assertRaises(PermissionError):
            uia.fill_test_text(42, "id", "real content")

    def test_port_not_loopback_refused(self):
        with patch.object(cdp_probe, "listeners", return_value=[dict(address="0.0.0.0", pid=1)]):
            self.assertEqual(cdp_probe.safe_listener(9223, {})["reason"], "NOT_LOOPBACK_ONLY")

    def test_cdp_other_process_not_contacted(self):
        with patch.object(cdp_probe, "listeners", return_value=[dict(address="127.0.0.1", pid=1)]), \
                patch.object(cdp_probe, "session_info", return_value={"session_id": 1}), \
                patch.object(cdp_probe, "process_executable", return_value="C:/other.exe"), \
                patch.object(cdp_probe, "request") as request:
            result = cdp_probe.probe_cdp({"executable_path": "D:/test.exe"})
            self.assertEqual(result["reason"], "OWNER_MISMATCH")
            request.assert_not_called()

    def test_sensitive_paths_rejected(self):
        for port, path in ((9223, "/json/new"), (3101, "/api/accounts"), (3101, "/cookie")):
            with self.assertRaises(PermissionError):
                cdp_probe.request(port, path)

    def test_worker_failure_stops_and_records_partial(self):
        with tempfile.TemporaryDirectory() as temp, patch("xiaovcat_adapter.desktop_worker.worker.settings", return_value={}):
            worker = DesktopWorker(Path(temp) / "run")
            worker.connect = Mock(side_effect=NeedsManual("UNKNOWN_DIALOG"))
            worker.select_video = Mock()
            worker.run()
            self.assertEqual(worker.report["state"], "NEEDS_MANUAL")
            self.assertFalse(worker.report["dry_run_complete"])
            worker.select_video.assert_not_called()
            self.assertEqual(worker.report["final_submit_invocations"], 0)


if __name__ == "__main__":
    unittest.main()
