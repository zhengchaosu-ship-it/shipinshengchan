"""本机受控键盘辅助及真实窗口截图，不提供任意坐标点击。"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from pathlib import Path

from .electron_probe import require_interactive_session


def native_user():
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetForegroundWindow.restype = wintypes.HWND
    user.SetForegroundWindow.argtypes = [wintypes.HWND]
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user.IsIconic.argtypes = [wintypes.HWND]
    return user


def activate(hwnd: int):
    require_interactive_session()
    user = native_user()
    title = ctypes.create_unicode_buffer(256)
    user.GetWindowTextW(hwnd, title, 256)
    if title.value not in {"小V猫", "打开", "Open"}:
        raise RuntimeError("未知目标窗口，禁止键盘输入")
    if user.IsIconic(hwnd):
        user.ShowWindow(hwnd, 9)
    user.SetForegroundWindow(hwnd)
    end = time.monotonic() + 2
    while time.monotonic() < end:
        if user.GetForegroundWindow() == hwnd:
            return
        time.sleep(.05)
    raise RuntimeError("无法取得目标窗口前台，停止输入")


def screenshot(hwnd: int, output: Path) -> str:
    from PIL import ImageGrab
    activate(hwnd)
    user = native_user()
    rect = wintypes.RECT()
    user.GetWindowRect(hwnd, ctypes.byref(rect))
    if rect.right <= rect.left or rect.bottom <= rect.top:
        raise RuntimeError("窗口截图区域无效")
    output.parent.mkdir(parents=True, exist_ok=True)
    ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom), all_screens=True).save(output)
    return str(output)


def fill_focused_test(uia, hwnd: int, runtime_id: str, text: str) -> str:
    """仅固定测试文字；先验证焦点，Unicode SendInput，最后回读 ValuePattern。"""
    if text not in {"XIAOVCAT_POC_TEST_DO_NOT_PUBLISH", "小V猫适配器UI控制测试，不发布。"}:
        raise PermissionError("只允许 POC 固定文字")
    activate(hwnd)
    element = uia.resolve(hwnd, runtime_id)
    element.SetFocus()
    if not uia.client.CompareElements(uia.client.GetFocusedElement(), element):
        raise RuntimeError("输入框未获得焦点")
    if str(element.CurrentAutomationId) not in {"title", "desc", "item_title", "text"}:
        raise PermissionError("不是经过验证的测试文字字段")
    pattern = element.GetCurrentPattern(10002).QueryInterface(uia.types.IUIAutomationValuePattern)
    if str(pattern.CurrentValue) != "":
        raise RuntimeError("键盘 fallback 只允许空白输入框，避免追加/覆盖")
    send_text(hwnd, text)
    end = time.monotonic() + 5
    aid = str(element.CurrentAutomationId)
    while time.monotonic() < end:
        fresh = uia.unique(hwnd, lambda r:r["control_type"] == 50004 and r["automation_id"] == aid)
        value = str(uia.resolve(hwnd, fresh["runtime_id"]).GetCurrentPattern(10002).QueryInterface(
            uia.types.IUIAutomationValuePattern).CurrentValue)
        if value == text:
            return value
        time.sleep(.15)
    raise RuntimeError("键盘输入后回读不一致")


def send_text(hwnd: int, text: str):
    # 不实现 Enter/Space 的任意发送，避免焦点误落最终提交按钮。
    user = native_user()
    if user.GetForegroundWindow() != hwnd:
        raise RuntimeError("前台改变，禁止输入")
    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.c_size_t)]
    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]
    class INPUTUNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]
    class INPUT(ctypes.Structure):
        _anonymous_ = ("union",)
        _fields_ = [("type", wintypes.DWORD), ("union", INPUTUNION)]
    # 文本不能携带控制字符，按 UTF-16 code unit 注入。
    if any(ord(c) < 32 for c in text):
        raise PermissionError("禁止控制字符")
    units = text.encode("utf-16-le")
    items = []
    for i in range(0, len(units), 2):
        code = int.from_bytes(units[i:i+2], "little")
        for flags in (0x4, 0x6):
            item = INPUT(type=1)
            item.ki = KEYBDINPUT(0, code, flags, 0, 0)
            items.append(item)
    buffer = (INPUT * len(items))(*items)
    user.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    if user.SendInput(len(items), buffer, ctypes.sizeof(INPUT)) != len(items):
        raise RuntimeError("SendInput 未完整接受，停止")
