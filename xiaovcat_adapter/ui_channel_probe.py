"""小V猫 UI 通道只读诊断。

仅枚举进程模块、Win32 HWND/Class 层级，并探测 HWND 是否提供
UI Automation host provider 和 MSAA IAccessible。不发送键鼠输入，不读取
Cookie/token/凭证，不修改小V猫文件。
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from ctypes import wintypes
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .discovery import _windows_processes


TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
OBJID_CLIENT = 0xFFFFFFFC


@dataclass(slots=True)
class WindowNode:
    hwnd: str
    parent_hwnd: str | None
    pid: int
    class_name: str
    title: str
    visible: bool
    enabled: bool
    rect: list[int]
    dpi: int | None
    maximized: bool
    uia_host_provider: bool
    uia_hresult: str
    msaa_iaccessible: bool
    msaa_hresult: str


@dataclass(slots=True)
class UiChannelReport:
    app_name: str
    process_name: str
    process_ids: list[int]
    package_version: str | None
    electron_version: str | None
    inferred_stack: str
    stack_evidence: list[str]
    modules_by_pid: dict[str, list[str]]
    windows: list[WindowNode]
    standard_win32_controls: list[str]
    chrome_window_classes: list[str]
    uia_host_provider_count: int
    msaa_iaccessible_count: int
    native_control_channel_available: bool
    native_control_channel_error: str | None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


IID_IACCESSIBLE = GUID(
    0x618736E0,
    0x3C3D,
    0x11CF,
    (ctypes.c_ubyte * 8)(0x81, 0x0C, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71),
)


def probe(
    executable_path: str | Path,
    process_name: str = "小V猫.exe",
    *,
    native_control_channel_available: bool = False,
    native_control_channel_error: str | None = None,
) -> UiChannelReport:
    if os.name != "nt":
        raise RuntimeError("此诊断仅支持 Windows")
    executable = Path(executable_path)
    processes = _windows_processes(process_name)
    pids = sorted(item.pid for item in processes)
    if not pids:
        raise RuntimeError(f"未找到运行进程: {process_name}")
    modules_by_pid = {str(pid): _enum_modules(pid) for pid in pids}
    windows = _enum_windows(set(pids))
    classes = sorted({node.class_name for node in windows})
    standard = sorted({
        name for name in classes
        if name.lower() in {
            "button", "edit", "listbox", "combobox", "static", "syslistview32",
            "systreeview32", "richedit20w", "richedit50w", "#32770",
        }
    })
    chrome_classes = sorted({
        name for name in classes
        if name.startswith("Chrome_") or "RenderWidgetHost" in name
    })
    package = _read_package(executable)
    electron_version = _electron_version(executable)
    evidence: list[str] = []
    if chrome_classes:
        evidence.append("窗口层级包含 Chromium Chrome_* class")
    if (executable.parent / "resources" / "app" / "package.json").is_file():
        evidence.append("安装目录存在 resources/app/package.json")
    if any("chrome_elf.dll" in {name.lower() for name in modules} for modules in modules_by_pid.values()):
        evidence.append("进程加载 chrome_elf.dll")
    if any("libegl.dll" in {name.lower() for name in modules} for modules in modules_by_pid.values()):
        evidence.append("进程加载 Chromium GPU 模块 libEGL.dll")
    inferred = "Electron/Chromium embedded web UI" if len(evidence) >= 2 else "Unknown"
    uia_count = sum(node.uia_host_provider for node in windows)
    msaa_count = sum(node.msaa_iaccessible for node in windows)
    notes = [
        "UIA host provider/MSAA 存在只表示 HWND 层有 provider，不等于页面 DOM 控件已可结构化操作。",
        "Chrome_RenderWidgetHostHWND 下的网页控件不是标准 Win32 Edit/Button/List 子窗口。",
    ]
    if not native_control_channel_available:
        notes.append("当前 Codex Windows 原生控制通道未暴露应用窗口，无法验证 UIA ControlView/RawView 或执行键鼠输入。")
    return UiChannelReport(
        app_name=package.get("name", "小V猫"),
        process_name=process_name,
        process_ids=pids,
        package_version=package.get("version"),
        electron_version=electron_version,
        inferred_stack=inferred,
        stack_evidence=evidence,
        modules_by_pid=modules_by_pid,
        windows=windows,
        standard_win32_controls=standard,
        chrome_window_classes=chrome_classes,
        uia_host_provider_count=uia_count,
        msaa_iaccessible_count=msaa_count,
        native_control_channel_available=native_control_channel_available,
        native_control_channel_error=native_control_channel_error,
        notes=notes,
    )


def _enum_windows(pids: set[int]) -> list[WindowNode]:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    oleacc = ctypes.OleDLL("oleacc", use_last_error=True)
    uia_core = ctypes.OleDLL("uiautomationcore", use_last_error=True)

    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [enum_proc, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.EnumChildWindows.argtypes = [wintypes.HWND, enum_proc, wintypes.LPARAM]
    user32.EnumChildWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsWindowEnabled.argtypes = [wintypes.HWND]
    user32.IsWindowEnabled.restype = wintypes.BOOL
    user32.IsZoomed.argtypes = [wintypes.HWND]
    user32.IsZoomed.restype = wintypes.BOOL
    if hasattr(user32, "GetDpiForWindow"):
        user32.GetDpiForWindow.argtypes = [wintypes.HWND]
        user32.GetDpiForWindow.restype = wintypes.UINT

    oleacc.AccessibleObjectFromWindow.argtypes = [
        wintypes.HWND, wintypes.DWORD, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)
    ]
    oleacc.AccessibleObjectFromWindow.restype = ctypes.c_long
    uia_core.UiaHostProviderFromHwnd.argtypes = [wintypes.HWND, ctypes.POINTER(ctypes.c_void_p)]
    uia_core.UiaHostProviderFromHwnd.restype = ctypes.c_long

    handles: set[int] = set()

    @enum_proc
    def top_callback(hwnd: int, _lparam: int) -> bool:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if int(pid.value) in pids:
            handles.add(int(hwnd))

            @enum_proc
            def child_callback(child: int, _child_lparam: int) -> bool:
                handles.add(int(child))
                return True

            user32.EnumChildWindows(hwnd, child_callback, 0)
        return True

    user32.EnumWindows(top_callback, 0)
    nodes: list[WindowNode] = []
    for handle in sorted(handles):
        hwnd = wintypes.HWND(handle)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        class_buffer = ctypes.create_unicode_buffer(512)
        user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
        title_length = user32.GetWindowTextLengthW(hwnd)
        title_buffer = ctypes.create_unicode_buffer(max(1, title_length + 1))
        if title_length:
            user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        parent = user32.GetParent(hwnd)
        uia_ptr = ctypes.c_void_p()
        uia_hr = int(uia_core.UiaHostProviderFromHwnd(hwnd, ctypes.byref(uia_ptr)))
        uia_ok = uia_hr >= 0 and bool(uia_ptr.value)
        if uia_ptr.value:
            _release_unknown(uia_ptr)
        msaa_ptr = ctypes.c_void_p()
        msaa_hr = int(oleacc.AccessibleObjectFromWindow(
            hwnd, wintypes.DWORD(OBJID_CLIENT), ctypes.byref(IID_IACCESSIBLE), ctypes.byref(msaa_ptr)
        ))
        msaa_ok = msaa_hr >= 0 and bool(msaa_ptr.value)
        if msaa_ptr.value:
            _release_unknown(msaa_ptr)
        dpi = int(user32.GetDpiForWindow(hwnd)) if hasattr(user32, "GetDpiForWindow") else None
        nodes.append(WindowNode(
            hwnd=f"0x{handle:016X}",
            parent_hwnd=f"0x{int(parent):016X}" if parent else None,
            pid=int(pid.value),
            class_name=class_buffer.value,
            title=title_buffer.value,
            visible=bool(user32.IsWindowVisible(hwnd)),
            enabled=bool(user32.IsWindowEnabled(hwnd)),
            rect=[rect.left, rect.top, rect.right, rect.bottom],
            dpi=dpi,
            maximized=bool(user32.IsZoomed(hwnd)),
            uia_host_provider=uia_ok,
            uia_hresult=f"0x{uia_hr & 0xFFFFFFFF:08X}",
            msaa_iaccessible=msaa_ok,
            msaa_hresult=f"0x{msaa_hr & 0xFFFFFFFF:08X}",
        ))
    return nodes


def _release_unknown(pointer: ctypes.c_void_p) -> None:
    try:
        vtable = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
        release(pointer)
    except (ValueError, OSError):
        pass


def _enum_modules(pid: int) -> list[str]:
    class MODULEENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("th32ModuleID", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("GlblcntUsage", wintypes.DWORD),
            ("ProccntUsage", wintypes.DWORD),
            ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
            ("modBaseSize", wintypes.DWORD),
            ("hModule", wintypes.HMODULE),
            ("szModule", wintypes.WCHAR * 256),
            ("szExePath", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Module32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MODULEENTRY32W)]
    kernel32.Module32FirstW.restype = wintypes.BOOL
    kernel32.Module32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MODULEENTRY32W)]
    kernel32.Module32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if snapshot == ctypes.c_void_p(-1).value:
        return []
    modules: list[str] = []
    item = MODULEENTRY32W()
    item.dwSize = ctypes.sizeof(item)
    try:
        ok = kernel32.Module32FirstW(snapshot, ctypes.byref(item))
        while ok:
            modules.append(item.szModule)
            ok = kernel32.Module32NextW(snapshot, ctypes.byref(item))
    finally:
        kernel32.CloseHandle(snapshot)
    return sorted(set(modules), key=str.lower)


def _read_package(executable: Path) -> dict[str, Any]:
    path = executable.parent / "resources" / "app" / "package.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}


def _electron_version(executable: Path) -> str | None:
    version_file = executable.parent / "version"
    try:
        return version_file.read_text(encoding="ascii").strip() or None
    except OSError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="小V猫 UI 通道只读诊断")
    parser.add_argument("--exe", default=r"D:\小V猫\小V猫.exe")
    parser.add_argument("--process-name", default="小V猫.exe")
    parser.add_argument("--output", required=True)
    parser.add_argument("--channel-error", default="Codex native Windows app inventory returned empty")
    args = parser.parse_args()
    report = probe(
        args.exe,
        args.process_name,
        native_control_channel_available=False,
        native_control_channel_error=args.channel_error,
    )
    target = Path(args.output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(target),
        "inferred_stack": report.inferred_stack,
        "windows": len(report.windows),
        "uia_host_provider_count": report.uia_host_provider_count,
        "msaa_iaccessible_count": report.msaa_iaccessible_count,
        "standard_win32_controls": report.standard_win32_controls,
        "chrome_window_classes": report.chrome_window_classes,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

