"""仅诊断本机、进程归属已验证的 CDP/3101；不读 cookie/storage/响应业务体。"""
from __future__ import annotations

import base64
import ctypes
import http.client
import json
import os
import subprocess
from ctypes import wintypes
from pathlib import Path
from urllib.parse import urlsplit

from .electron_probe import session_info


def process_executable(pid: int) -> str:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        name = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(name))
        if not kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        return name.value
    finally:
        kernel.CloseHandle(handle)


def listeners(port: int) -> list[dict]:
    exe = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/netstat.exe"
    proc = subprocess.run([str(exe), "-ano"], capture_output=True,
                          encoding="mbcs", timeout=10, creationflags=0x08000000)
    if proc.returncode:
        raise RuntimeError("NETSTAT_FAILED")
    rows = []
    for line in proc.stdout.splitlines():
        fields = line.split()
        if len(fields) == 5 and fields[0] == "TCP" and fields[3] == "LISTENING":
            address, _, number = fields[1].rpartition(":")
            if number == str(port):
                rows.append({"address": address.strip("[]"), "port": port, "pid": int(fields[4])})
    return rows


def safe_listener(port: int, config: dict) -> dict:
    rows = listeners(port)
    if not rows:
        return {"safe": False, "reason": "NOT_LISTENING", "port": port}
    if any(r["address"] not in {"127.0.0.1", "::1"} for r in rows):
        return {"safe": False, "reason": "NOT_LOOPBACK_ONLY", "listeners": rows}
    own = session_info()["session_id"]
    for row in rows:
        if (Path(process_executable(row["pid"])).resolve() != Path(config["executable_path"]).resolve()
                or session_info(row["pid"])["session_id"] != own):
            return {"safe": False, "reason": "OWNER_MISMATCH", "listeners": rows}
    if not any(r["address"] == "127.0.0.1" for r in rows):
        return {"safe": False, "reason": "NO_IPV4_LOOPBACK", "listeners": rows}
    return {"safe": True, "listeners": rows}


def request(port, path, *, headers=None, read_json=False):
    # http.client 不采用系统代理；禁止重定向，不输出响应正文。
    if (port == 9223 and path not in {"/json/version", "/json/list"}
            or port == 3101 and path not in {"/", "/health", "/healthz"}
            or port not in {9223, 3101}):
        raise PermissionError("只允许固定只读诊断路径")
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        conn.request("GET", path, headers=headers or {})
        response = conn.getresponse()
        info = {"path": path, "status": response.status,
                "headers": {key: response.getheader(key) for key in
                            ("Server", "X-Powered-By", "Content-Type", "Upgrade", "Connection")}}
        if read_json and response.status == 200:
            payload = response.read(262145)
            if len(payload) > 262144:
                raise RuntimeError("CDP_RESPONSE_TOO_LARGE")
            return info, json.loads(payload)
        return info, None
    finally:
        conn.close()


def probe_cdp(config: dict) -> dict:
    owner = safe_listener(9223, config)
    if not owner["safe"]:
        return {"connected": False, **owner}
    version_http, version = request(9223, "/json/version", read_json=True)
    list_http, pages = request(9223, "/json/list", read_json=True)
    if not isinstance(version, dict) or not isinstance(pages, list):
        return {"connected": False, "reason": "INVALID_CDP_METADATA", "http": [version_http, list_http]}
    # URL只记录协议和origin，不保留路径查询参数（可能含凭证）。不连接账号平台页面。
    safe_pages = []
    for page in pages:
        parsed = urlsplit(page.get("url", ""))
        safe_pages.append({"type": page.get("type"), "scheme": parsed.scheme,
                           "host": parsed.hostname, "websocket_available": bool(page.get("webSocketDebuggerUrl"))})
    return {"connected": True, "listeners": owner["listeners"],
            "browser": version.get("Browser"), "protocol_version": version.get("Protocol-Version"),
            "pages": safe_pages, "dom_tested": False,
            "reason": "UIA_PRIMARY_NO_ADDITIONAL_CDP_DRIVER", "http": [version_http, list_http]}


def probe_3101(config: dict) -> dict:
    owner = safe_listener(3101, config)
    if not owner["safe"]:
        return {"route_abandoned": True, **owner}
    records = []
    for path in ("/", "/health", "/healthz"):
        try:
            records.append(request(3101, path)[0])
        except (OSError, http.client.HTTPException) as exc:
            records.append({"path": path, "error": type(exc).__name__})
    try:
        records.append(request(3101, "/", headers={"Connection": "Upgrade", "Upgrade": "websocket",
            "Sec-WebSocket-Version": "13", "Sec-WebSocket-Key": base64.b64encode(os.urandom(16)).decode()})[0])
    except (OSError, http.client.HTTPException) as exc:
        records.append({"path": "/", "websocket_error": type(exc).__name__})
    return {"route_abandoned": True, "listeners": owner["listeners"], "http": records,
            "reason": "NO_DOCUMENTED_LOCAL_UI_SERVICE_CONTRACT"}
