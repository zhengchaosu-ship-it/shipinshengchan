"""登录用户桌面的独立、安全、可验证小V猫 POC Worker（无真实提交代码）。"""
from __future__ import annotations

import argparse
import ctypes
import json
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from .cdp_probe import probe_3101, probe_cdp, process_executable
from .electron_probe import (ROOT, app_windows, launch_test, main_window, process_flags,
                             require_interactive_session, settings)
from .keyboard_driver import activate, fill_focused_test, native_user, screenshot
from .state_detector import NeedsManual, guard_dialogs, publish_page, video_loaded, wait_for
from .uia_probe import LocalUIA

TITLE = "XIAOVCAT_POC_TEST_DO_NOT_PUBLISH"
DESCRIPTION = "小V猫适配器UI控制测试，不发布。"
TEST_VIDEO = ROOT / "auto_remake/tests/test_videos/合成 参考视频.mp4"
RESULTS = ROOT / "xiaovcat_adapter/results/desktop_worker_v03"


class DesktopWorker:
    def __init__(self, output: Path):
        self.config = settings()
        self.output = output
        output.mkdir(parents=True, exist_ok=False)
        self.report = {"status": "XIAOVCAT_DESKTOP_WORKER_PARTIAL", "state": "INIT",
                       "real_publish_enabled": False, "final_submit_invocations": 0,
                       "dry_run_complete": False, "primary": "UIA", "fallback": "KEYBOARD_ASSISTED",
                       "events": [], "evidence": [], "worker_version": "0.3"}
        self.hwnd = None
        self.uia = None

    def save(self, name, value):
        path = self.output / name
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    def event(self, state, **details):
        self.report["state"] = state
        event = {"time": datetime.now().astimezone().isoformat(), "state": state, **details}
        self.report["events"].append(event)
        with (self.output / "worker.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps(event, ensure_ascii=False) + "\n")
        print(json.dumps(event, ensure_ascii=False), flush=True)

    def checkpoint(self, name, predicate, *, allow_account=False):
        tree = wait_for(self.uia, self.hwnd, predicate, allow_account=allow_account)
        self.save(name + ".json", tree)
        shot = screenshot(self.hwnd, self.output / (name + ".png"))
        self.report["evidence"].append(shot)
        self.event(name.upper(), node_count=tree["node_count"])
        return tree

    def before_action(self, *, allow_account=False):
        settings()  # 每次动作重新检查真实发布开关，改成 true 也拒绝。
        require_interactive_session()
        window = main_window(self.config)
        if (int(window["hwnd"], 0) != self.hwnd or not window["enabled"]
                or Path(process_executable(window["pid"])).resolve() != Path(self.config["executable_path"]).resolve()):
            raise NeedsManual("TARGET_WINDOW_CHANGED_OR_DISABLED")
        dialogs = [w for w in app_windows(self.config) if w["visible"] and w["class_name"] == "#32770"]
        if dialogs:
            raise NeedsManual("UNKNOWN_DIALOG：存在原生弹窗")
        activate(self.hwnd)
        wait_for(self.uia, self.hwnd, lambda rows:bool(rows), timeout=5, allow_account=allow_account)

    def wait_main(self):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                return main_window(self.config)
            except RuntimeError:
                time.sleep(.25)
        raise NeedsManual("MAIN_WINDOW_TIMEOUT")

    def connect(self, *, launch_only=False):
        self.report["session"] = require_interactive_session()
        launch = launch_test(self.config)
        self.report["launch"] = launch
        self.event("CONNECT", launch=launch)
        if launch_only:
            if not launch["launched"]:
                self.event("NEEDS_MANUAL", reason="请自行正常关闭已有小V猫，再运行测试启动器。Worker 不关闭进程。")
            else:
                self.event("LAUNCHED_FOR_PROBE", reason="测试参数启动，不进行页面操作；之后运行小V猫自动化测试.bat")
            return False
        window = self.wait_main()
        self.report["window"] = window
        self.hwnd = int(window["hwnd"], 0)
        if Path(process_executable(window["pid"])).resolve() != Path(self.config["executable_path"]).resolve():
            raise NeedsManual("EXECUTABLE_MISMATCH")
        activate(self.hwnd)
        flags = process_flags(self.config)
        self.report["process_flags"] = flags
        self.report["force_accessibility_test"] = "UNTESTED_NO_RESTART" if not any(
            p.get("force_accessibility") for p in flags) else "FLAG_PRESENT_EFFECT_ATTRIBUTION_UNPROVEN"
        snapshots = []
        for version in (2, 3):
            uia = LocalUIA(version)
            snapshots.extend(uia.tree(self.hwnd, view) for view in ("control", "raw"))
        self.save("uia_probe.json", snapshots)
        self.report["uia_counts"] = [{k: t[k] for k in ("uia_version", "view", "node_count", "truncated")}
                                      for t in snapshots]
        self.report["cdp"] = probe_cdp(self.config)
        self.report["port3101"] = probe_3101(self.config)
        self.uia = LocalUIA(3)
        self.checkpoint("01_main", lambda rows:any(r["automation_id"].endswith("-tab-publish") for r in rows))
        self.event("CHANNEL_SELECTED", primary="UIA", fallback="KEYBOARD_ASSISTED",
                   reason="直接 UIA 暴露 Chrome 控件，CDP 只诊断，不建立第二套控制实现")
        return True

    def blank_form(self):
        self.before_action()
        for aid in ("title", "desc"):
            row = self.uia.unique(self.hwnd, lambda r:r["control_type"] == 50004 and r["automation_id"] == aid)
            value = str(self.uia.resolve(self.hwnd, row["runtime_id"]).GetCurrentPattern(10002).QueryInterface(
                self.uia.types.IUIAutomationValuePattern).CurrentValue)
            if value:
                raise NeedsManual("EXISTING_DRAFT：不覆盖现有表单，包括前一次 POC")
        rows = self.uia.tree(self.hwnd)["nodes"]
        if video_loaded(rows) or not any(r["name"] == "未选择账号，请点击加号按钮选择账号" for r in rows):
            raise NeedsManual("EXISTING_DRAFT：先手工清理/保存已有表单，再测试")
        # 不自动切换“自动提取”或记住配置，拒绝启用的非默认行为。
        boxes = [r for r in rows if r["control_type"] == 50002 and r["name"].strip() == "自动提取"]
        if len(boxes) != 1:
            raise NeedsManual("AUTO_EXTRACT_STATE_UNKNOWN")
        toggle = self.uia.resolve(self.hwnd, boxes[0]["runtime_id"]).GetCurrentPattern(10015).QueryInterface(
            self.uia.types.IUIAutomationTogglePattern)
        if toggle.CurrentToggleState != 0:
            raise NeedsManual("AUTO_EXTRACT_ENABLED")

    def select_video(self):
        self.before_action()
        row = self.uia.unique(self.hwnd, lambda r:r["control_type"] == 50000
                              and r["name"].startswith("play-square 点击上传文件 本地视频支持MP4、"))
        self.uia.invoke(self.hwnd, row["runtime_id"], row["name"])
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            windows = app_windows(self.config)
            dialogs = [w for w in windows if w["visible"] and w["class_name"] == "#32770"]
            if dialogs:
                if (len(dialogs) != 1 or dialogs[0]["title"] not in {"打开", "Open"}
                        or int(dialogs[0]["parent_hwnd"] or "0", 0) != self.hwnd):
                    raise NeedsManual("UNKNOWN_DIALOG")
                dialog = dialogs[0]
                if Path(process_executable(dialog["pid"])).resolve() != Path(self.config["executable_path"]).resolve():
                    raise NeedsManual("FILE_DIALOG_OWNER_MISMATCH")
                dh = int(dialog["hwnd"], 0)
                activate(dh)
                self.uia.choose_test_file(dh, TEST_VIDEO)
                self.event("TEST_FILE_ACCEPTED", path=str(TEST_VIDEO), size=TEST_VIDEO.stat().st_size)
                closed_deadline = time.monotonic() + 12
                while time.monotonic() < closed_deadline:
                    current = app_windows(self.config)
                    remaining = [w for w in current if w["visible"] and w["class_name"] == "#32770"]
                    if any(int(w["hwnd"], 0) != dh for w in remaining):
                        raise NeedsManual("UNKNOWN_DIALOG：文件选择时出现其他弹窗")
                    if not remaining and main_window(self.config)["enabled"]:
                        self.event("FILE_DIALOG_CLOSED")
                        break
                    time.sleep(.15)
                else:
                    raise NeedsManual("FILE_DIALOG_CLOSE_TIMEOUT")
                break
            time.sleep(.25)
        else:
            raise NeedsManual("FILE_DIALOG_TIMEOUT")
        self.checkpoint("03_video_loaded", video_loaded)
        self.report["video_loaded"] = True

    def select_account(self):
        self.before_action()
        row = self.uia.unique(self.hwnd, lambda r:r["control_type"] == 50000 and r["name"] == "plus"
                              and "add-btn" in r["class_name"])
        self.uia.invoke(self.hwnd, row["runtime_id"], row["name"])
        self.checkpoint("account_dialog", lambda rows:any(r["name"] == "选择账号" for r in rows), allow_account=True)
        accounts = self.uia.account_rows(self.hwnd)
        self.report["accounts"] = accounts
        self.save("accounts.json", accounts)
        self.event("VISIBLE_ACCOUNTS", accounts=accounts)
        self.before_action(allow_account=True)
        chosen = self.uia.select_one_account(self.hwnd)
        self.event("CHECKBOX_VERIFIED", account=chosen)
        self.before_action(allow_account=True)
        self.uia.confirm_account_dialog(self.hwnd)
        self.checkpoint("04_account_selected", lambda rows:publish_page(rows)
                        and any(r["control_type"] == 50019 and r["name"] == chosen["account_name"] + " close" for r in rows)
                        and not any(r["control_type"] == 50032 and r["depth"] > 0
                                    and not r["offscreen"] for r in rows), allow_account=True)
        self.report["selected_account"] = chosen

    def fill_text(self):
        values = {}
        for aid, text in (("title", TITLE), ("desc", DESCRIPTION), ("item_title", TITLE), ("text", DESCRIPTION)):
            self.before_action()
            row = self.uia.unique(self.hwnd, lambda r:r["control_type"] == 50004 and r["automation_id"] == aid)
            try:
                values[aid] = self.uia.fill_test_text(self.hwnd, row["runtime_id"], text)
            except self.uia.com_error:
                # 仅 SetValue 调用失败时尝试空白字段键盘辅助；验证失败不盲目重试。
                self.before_action()
                fresh = self.uia.unique(self.hwnd, lambda r:r["control_type"] == 50004 and r["automation_id"] == aid)
                values[aid] = fill_focused_test(self.uia, self.hwnd, fresh["runtime_id"], text)
            self.event("TEXT_READBACK_VERIFIED", field=aid, value=values[aid])
        self.report["text_readback"] = values
        self.checkpoint("05_text_filled", publish_page)

    def stop_before_submit(self):
        self.before_action()
        rows = self.uia.tree(self.hwnd)["nodes"]
        if not video_loaded(rows):
            raise NeedsManual("VIDEO_DISAPPEARED")
        chosen = self.report["selected_account"]
        if len([r for r in rows if not r["offscreen"] and r["control_type"] == 50019
                and r["name"] == chosen["account_name"] + " close"]) != 1:
            raise NeedsManual("SELECTED_ACCOUNT_CHANGED")
        final_values = {}
        for aid, text in (("title", TITLE), ("desc", DESCRIPTION), ("item_title", TITLE), ("text", DESCRIPTION)):
            field = self.uia.unique(self.hwnd, lambda r:r["control_type"] == 50004 and r["automation_id"] == aid)
            value = str(self.uia.resolve(self.hwnd, field["runtime_id"]).GetCurrentPattern(10002).QueryInterface(
                self.uia.types.IUIAutomationValuePattern).CurrentValue)
            if value != text:
                raise NeedsManual("FINAL_TEXT_CHANGED：" + aid)
            final_values[aid] = value
        self.report["final_text_readback"] = final_values
        row = self.uia.unique(self.hwnd, lambda r:r["control_type"] == 50000 and r["name"] == "一键分发")
        self.report["final_button"] = {**row, "action": "IDENTIFY_ONLY_NEVER_INVOKE"}
        self.checkpoint("06_before_submit", publish_page)
        self.report.update(status="XIAOVCAT_DESKTOP_WORKER_PASS", dry_run_complete=True)
        self.event("STOP_BEFORE_SUBMIT", final_button="一键分发", real_publish_enabled=False,
                   final_submit_invocations=0)

    def run(self, *, launch_only=False, probe_only=False):
        try:
            if not self.connect(launch_only=launch_only):
                return
            if probe_only:
                self.event("PROBE_ONLY_STOP")
                return
            self.before_action()
            self.uia.select_publish_tab(self.hwnd)
            self.checkpoint("02_publish_page", publish_page)
            self.blank_form()
            self.select_video()
            self.select_account()
            self.fill_text()
            self.stop_before_submit()
        except Exception as exc:
            self.event("NEEDS_MANUAL", error=type(exc).__name__, reason=str(exc))
            if self.hwnd:
                try:
                    self.save("failed_state.json", self.uia.tree(self.hwnd))
                    self.report["evidence"].append(screenshot(self.hwnd, self.output / "needs_manual.png"))
                except Exception:
                    self.event("SCREENSHOT_UNAVAILABLE")
        finally:
            self.save("report.json", self.report)


def main():
    parser = argparse.ArgumentParser(description="本机小V猫 UIA Worker，只做到提交前 STOP")
    parser.add_argument("--launch-only", action="store_true")
    parser.add_argument("--probe-only", action="store_true")
    args = parser.parse_args()
    require_interactive_session()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    mutex = kernel.CreateMutexW(None, True, "Local\\XiaovcatDesktopWorkerV03")
    if not mutex or ctypes.get_last_error() == 183:
        if mutex:
            kernel.CloseHandle(mutex)
        raise SystemExit("已有 Worker 在运行，禁止并行操作")
    try:
        output = RESULTS / datetime.now().strftime("run_%Y%m%d_%H%M%S_%f")
        worker = DesktopWorker(output)
        worker.run(launch_only=args.launch_only, probe_only=args.probe_only)
        print("报告：" + str(output / "report.json"))
        raise SystemExit(0 if worker.report["dry_run_complete"] or args.launch_only or args.probe_only else 2)
    finally:
        kernel.CloseHandle(mutex)


if __name__ == "__main__":
    main()
