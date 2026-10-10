"""小V猫本机只读发现。

不读取 Cookie/token/密码，不解密凭证，不修改安装目录。
"""
from __future__ import annotations

import csv
import importlib.util
import json
import os
import re
import socket
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


SENSITIVE_NAME = re.compile(r"cookie|token|password|credential|secret|login|ck\.json", re.I)
DATA_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".json", ".csv", ".xlsx", ".xls"}


@dataclass(slots=True)
class ProcessInfo:
    image_name: str
    pid: int
    window_title: str | None = None


@dataclass(slots=True)
class DiscoveryReport:
    app_name: str
    installed: bool
    install_location: str | None
    executable_path: str | None
    registry_version: str | None
    package_version: str | None
    executable_file_version: str | None
    process_name: str
    processes: list[ProcessInfo] = field(default_factory=list)
    main_window_title: str | None = None
    config_directories: list[str] = field(default_factory=list)
    log_files: list[str] = field(default_factory=list)
    export_directories: list[str] = field(default_factory=list)
    ordinary_data_files: list[str] = field(default_factory=list)
    localhost_ports: list[int] = field(default_factory=list)
    uia_backend_available: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


def discover(config: dict[str, Any]) -> DiscoveryReport:
    executable = Path(config.get("executable_path", ""))
    user_data = Path(os.path.expandvars(config.get("user_data_dir", "")))
    install_dir = executable.parent if executable.name else None
    package = _read_safe_json(install_dir / "resources" / "app" / "package.json") if install_dir else {}
    registry = _find_registry_install(config.get("app_name", "小V猫"))
    processes = _tasklist_processes(config.get("process_name", "小V猫.exe"))
    pids = {item.pid for item in processes}
    ports = _netstat_ports(pids)
    export_dirs = [
        path for path in (
            user_data / "_download",
            user_data / "_upload",
            *(Path(os.path.expandvars(p)) for p in config.get("export_directories", [])),
        ) if path.is_dir()
    ]
    logs = []
    for candidate in [install_dir / "debug.log" if install_dir else None,
                      user_data / "logs", user_data / "Logs"]:
        if candidate and candidate.is_file():
            logs.append(str(candidate))
        elif candidate and candidate.is_dir():
            logs.extend(str(p) for p in candidate.glob("*.log"))
    report = DiscoveryReport(
        app_name=config.get("app_name", "小V猫"),
        installed=executable.is_file(),
        install_location=str(install_dir) if install_dir and install_dir.is_dir() else registry.get("install_location"),
        executable_path=str(executable) if executable.is_file() else registry.get("executable_path"),
        registry_version=registry.get("version"),
        package_version=str(package.get("version")) if package.get("version") else None,
        executable_file_version=config.get("observed_executable_file_version"),
        process_name=config.get("process_name", "小V猫.exe"),
        processes=processes,
        main_window_title=next((p.window_title for p in processes if p.window_title), None),
        config_directories=[str(user_data)] if user_data.is_dir() else [],
        log_files=sorted(set(logs)),
        export_directories=sorted(set(map(str, export_dirs))),
        ordinary_data_files=_find_safe_data_files(user_data),
        localhost_ports=ports,
        uia_backend_available=importlib.util.find_spec("pywinauto") is not None,
    )
    if ports:
        report.notes.append("只确认本机端口在监听，未视为公开或稳定 API")
    if not report.uia_backend_available:
        report.notes.append("pywinauto 未安装；当前 Python 环境无法执行 UIA 驱动")
    return report


def localhost_http_status(port: int, path: str = "/", timeout: float = 2.0) -> int | None:
    """仅对已发现的 localhost 端口发起普通 GET；不枚举私有协议。"""
    request = f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as conn:
            conn.sendall(request.encode("ascii"))
            first = conn.recv(128).decode("iso-8859-1", errors="replace").splitlines()[0]
        match = re.match(r"HTTP/\d(?:\.\d)?\s+(\d+)", first)
        return int(match.group(1)) if match else None
    except OSError:
        return None


def _read_safe_json(path: Path) -> dict[str, Any]:
    if not path.is_file() or SENSITIVE_NAME.search(path.name):
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}


def _tasklist_processes(process_name: str) -> list[ProcessInfo]:
    native = _windows_processes(process_name)
    if native:
        return native
    try:
        completed = subprocess.run(
            ["tasklist", "/v", "/fo", "csv", "/fi", f"imagename eq {process_name}"],
            capture_output=True,
            text=True,
            encoding="mbcs",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    rows = list(csv.reader(completed.stdout.splitlines()))
    if len(rows) < 2:
        return []
    result: list[ProcessInfo] = []
    for row in rows[1:]:
        if len(row) < 2 or row[0].lower() != process_name.lower():
            continue
        title = row[-1].strip() if row[-1].strip() not in {"", "N/A"} else None
        try:
            result.append(ProcessInfo(row[0], int(row[1]), title))
        except ValueError:
            continue
    return result


def _windows_processes(process_name: str) -> list[ProcessInfo]:
    """用 Windows 标准进程/窗口枚举 API 只读获取信息。

    这避免中文进程名经 tasklist 管道时受控制台代码页影响。
    """
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32FirstW.restype = wintypes.BOOL
        kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32NextW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
        invalid_handle = ctypes.c_void_p(-1).value
        if snapshot == invalid_handle:
            return []
        pids: dict[int, str] = {}
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        try:
            ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while ok:
                if entry.szExeFile.lower() == process_name.lower():
                    pids[int(entry.th32ProcessID)] = entry.szExeFile
                ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
        if not pids:
            return []

        titles: dict[int, str] = {}
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL

        @callback_type
        def enum_window(hwnd: int, _lparam: int) -> bool:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) not in pids or not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            if buffer.value:
                titles.setdefault(int(pid.value), buffer.value)
            return True

        user32.EnumWindows(enum_window, 0)
        return [ProcessInfo(name, pid, titles.get(pid)) for pid, name in sorted(pids.items())]
    except (OSError, AttributeError, ValueError):
        return []


def _netstat_ports(pids: set[int]) -> list[int]:
    if not pids:
        return []
    try:
        output = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True,
            encoding="mbcs", errors="replace", timeout=10, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    ports: set[int] = set()
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP" or parts[3].upper() != "LISTENING":
            continue
        try:
            pid = int(parts[4])
            host, port_text = parts[1].rsplit(":", 1)
            if pid in pids and host.strip("[]") in {"127.0.0.1", "::1"}:
                ports.add(int(port_text))
        except (ValueError, IndexError):
            continue
    return sorted(ports)


def _find_safe_data_files(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    excluded_parts = {"network", "local storage", "session storage", "indexeddb",
                      "service worker", "cache", "code cache"}
    result: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in DATA_SUFFIXES:
            continue
        if SENSITIVE_NAME.search(path.name):
            continue
        if any(part.lower() in excluded_parts for part in path.parts):
            continue
        result.append(str(path))
        if len(result) >= 200:
            break
    return sorted(result)


def _find_registry_install(display_name: str) -> dict[str, str | None]:
    if os.name != "nt":
        return {}
    try:
        import winreg
    except ImportError:
        return {}
    locations = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for hive, key_path in locations:
        try:
            with winreg.OpenKey(hive, key_path) as parent:
                for index in range(winreg.QueryInfoKey(parent)[0]):
                    with winreg.OpenKey(parent, winreg.EnumKey(parent, index)) as item:
                        name = _reg_value(item, "DisplayName")
                        if name != display_name:
                            continue
                        uninstall = _reg_value(item, "UninstallString") or ""
                        install_location = _reg_value(item, "InstallLocation")
                        executable = None
                        if uninstall:
                            candidate = Path(uninstall.strip('"')).parent / f"{display_name}.exe"
                            executable = str(candidate) if candidate.is_file() else None
                        return {
                            "version": _reg_value(item, "DisplayVersion"),
                            "install_location": install_location or (str(Path(uninstall.strip('"')).parent) if uninstall else None),
                            "executable_path": executable,
                        }
        except OSError:
            continue
    return {}


def _reg_value(key: Any, name: str) -> str | None:
    try:
        return str(__import__("winreg").QueryValueEx(key, name)[0])
    except OSError:
        return None
