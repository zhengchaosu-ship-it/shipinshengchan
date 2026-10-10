"""当前用户 Session、进程、启动参数和本地端口识别。"""
from __future__ import annotations

import ctypes
import json
import os
import socket
import subprocess
from ctypes import wintypes
from pathlib import Path

from ..discovery import _windows_processes

ROOT = Path(__file__).resolve().parents[2]
PS = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"


def settings() -> dict:
    config = json.loads((ROOT / "xiaovcat_adapter/config.json").read_text(encoding="utf-8"))
    if config.get("real_publish_enabled") is not False:
        raise PermissionError("V0.3 必须保持 real_publish_enabled=false")
    return config


def session_info(pid: int | None = None) -> dict:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    value = wintypes.DWORD()
    if not kernel.ProcessIdToSessionId(pid or os.getpid(), ctypes.byref(value)):
        raise ctypes.WinError(ctypes.get_last_error())
    active = int(kernel.WTSGetActiveConsoleSessionId())
    return {"pid": pid or os.getpid(), "session_id": value.value, "console_session_id": active}


def require_interactive_session() -> dict:
    current = session_info()
    if current["session_id"] == 0 or current["session_id"] != current["console_session_id"]:
        raise RuntimeError("WORKER_NOT_IN_ACTIVE_SESSION：请从当前登录桌面双击 run_worker.bat")
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user.OpenInputDesktop.restype = wintypes.HANDLE
    user.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                              wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    user.CloseDesktop.argtypes = [wintypes.HANDLE]
    desktop = user.OpenInputDesktop(0, False, 0x0001)
    if not desktop:
        raise RuntimeError("INPUT_DESKTOP_UNAVAILABLE：请解锁当前 Windows 桌面")
    try:
        name = ctypes.create_unicode_buffer(256)
        length = wintypes.DWORD()
        if not user.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name), ctypes.byref(length)):
            raise ctypes.WinError(ctypes.get_last_error())
        if name.value.lower() != "default":
            raise RuntimeError("SECURE_DESKTOP：当前不是普通交互桌面")
        current["input_desktop"] = name.value
    finally:
        user.CloseDesktop(desktop)
    return current


def app_windows(config: dict) -> list[dict]:
    processes = _windows_processes(config["process_name"])
    own_session = session_info()["session_id"]
    pids = set()
    for process in processes:
        try:
            if session_info(process.pid)["session_id"] == own_session:
                pids.add(process.pid)
        except OSError:
            continue
    user = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetParent.argtypes = [wintypes.HWND]
    user.GetParent.restype = wintypes.HWND
    user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.IsWindowVisible.argtypes = user.IsWindowEnabled.argtypes = user.IsZoomed.argtypes = [wintypes.HWND]
    user.GetDpiForWindow.argtypes = [wintypes.HWND]
    windows = []

    @callback_type
    def callback(hwnd, _):
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in pids:
            return True
        name, title = ctypes.create_unicode_buffer(256), ctypes.create_unicode_buffer(512)
        user.GetClassNameW(hwnd, name, 256)
        user.GetWindowTextW(hwnd, title, 512)
        rect = wintypes.RECT()
        user.GetWindowRect(hwnd, ctypes.byref(rect))
        parent = user.GetParent(hwnd)
        windows.append({"hwnd": hex(hwnd), "parent_hwnd": hex(parent) if parent else None,
                        "pid": pid.value, "class_name": name.value, "title": title.value,
                        "visible": bool(user.IsWindowVisible(hwnd)), "enabled": bool(user.IsWindowEnabled(hwnd)),
                        "rect": [rect.left, rect.top, rect.right, rect.bottom],
                        "dpi": int(user.GetDpiForWindow(hwnd)), "maximized": bool(user.IsZoomed(hwnd))})
        return True

    user.EnumWindows(callback, 0)
    return windows


def main_window(config: dict) -> dict:
    candidates = [w for w in app_windows(config) if w["visible"] and w["title"] == config["app_name"]
                  and w["class_name"] == "Chrome_WidgetWin_1"]
    if len(candidates) != 1:
        raise RuntimeError(f"MAIN_WINDOW_AMBIGUOUS：找到 {len(candidates)} 个主窗口")
    return candidates[0]


def process_flags(config: dict) -> list[dict]:
    # 仅输出已知启动参数的布尔值，不记录原始命令行。
    proc = subprocess.run([str(PS), "-NoProfile", "-NonInteractive", "-Command",
        "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); "
        "$data=Get-CimInstance Win32_Process | Where-Object {$_.ExecutablePath -eq $env:XIAOVCAT_PROBE_EXE}; "
        "@($data | ForEach-Object {[pscustomobject]@{pid=$_.ProcessId;parent_pid=$_.ParentProcessId;"
        "force_accessibility=($_.CommandLine -match '--force-renderer-accessibility');"
        "debug_port=($_.CommandLine -match '--remote-debugging-port=9223');"
        "debug_loopback=($_.CommandLine -match '--remote-debugging-address=127.0.0.1')}}) | ConvertTo-Json -Compress"],
        env={**os.environ, "XIAOVCAT_PROBE_EXE": config["executable_path"]},
        capture_output=True, encoding="utf-8", timeout=15,
        creationflags=0x08000000)
    if proc.returncode != 0:
        return [{"error": "PROCESS_FLAGS_READ_FAILED"}]
    value = json.loads(proc.stdout or "[]")
    return value if isinstance(value, list) else [value]


def launch_test(config: dict) -> dict:
    existing = _windows_processes(config["process_name"])
    if existing:
        return {"launched": False, "reason": "ALREADY_RUNNING_NO_RESTART", "pids": [p.pid for p in existing]}
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", 9223))
        except OSError:
            raise RuntimeError("CDP_PORT_OCCUPIED：9223 已被占用，停止启动")
    executable = Path(config["executable_path"])
    if not executable.is_file():
        raise FileNotFoundError(executable)
    child = subprocess.Popen([str(executable), "--force-renderer-accessibility",
                              "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=9223"],
                             cwd=executable.parent)
    return {"launched": True, "pid": child.pid, "flags": ["force-renderer-accessibility", "CDP loopback:9223"]}
