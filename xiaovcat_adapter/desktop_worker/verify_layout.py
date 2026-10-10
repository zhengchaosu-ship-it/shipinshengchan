"""只读检查 POC 表单在正常/移动/最大化后是否仍可定位；最终恢复窗口。"""
from __future__ import annotations

import ctypes
import json
from ctypes import wintypes
from pathlib import Path

from .electron_probe import app_windows, main_window, settings
from .keyboard_driver import native_user, screenshot
from .state_detector import publish_page, video_loaded, wait_for
from .uia_probe import LocalUIA
from .worker import TITLE, DESCRIPTION


def verify(output: Path):
    config = settings()
    window = main_window(config)
    hwnd = int(window["hwnd"], 0)
    user = native_user()
    user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, wintypes.UINT]
    left, top, right, bottom = window["rect"]
    uia = LocalUIA()
    records = []

    def check(label):
        wait_for(uia, hwnd, lambda rows:publish_page(rows) and video_loaded(rows))
        values = {}
        for aid, text in (("title", TITLE), ("desc", DESCRIPTION), ("item_title", TITLE), ("text", DESCRIPTION)):
            row = uia.unique(hwnd, lambda r:r["control_type"] == 50004 and r["automation_id"] == aid)
            value = str(uia.resolve(hwnd, row["runtime_id"]).GetCurrentPattern(10002).QueryInterface(
                uia.types.IUIAutomationValuePattern).CurrentValue)
            if value != text:
                raise RuntimeError("布局变化后文字字段不一致：" + aid)
            values[aid] = value
        button = uia.unique(hwnd, lambda r:r["control_type"] == 50000 and r["name"] == "一键分发")
        screenshot(hwnd, output / ("layout_" + label + ".png"))
        records.append({"layout": label, "verified": True, "window": main_window(config),
                        "text_readback": values, "final_button": button["name"], "actions": "READ_ONLY"})

    try:
        check("normal")
        if not user.SetWindowPos(hwnd, None, left + 48, top + 32, right-left, bottom-top, 0x0014):
            raise ctypes.WinError(ctypes.get_last_error())
        check("moved")
        user.ShowWindow(hwnd, 3)
        check("maximized")
    finally:
        user.ShowWindow(hwnd, 9)
        user.SetWindowPos(hwnd, None, left, top, right-left, bottom-top, 0x0014)
        if window["maximized"]:
            user.ShowWindow(hwnd, 3)
        output.joinpath("layout_report.json").write_text(json.dumps({"tests": records,
            "windows_scaling": "CURRENT_ONLY_NO_GLOBAL_SETTING_CHANGE",
            "restore_target": window}, ensure_ascii=False, indent=2), encoding="utf-8")
    return records


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.output), ensure_ascii=False))
