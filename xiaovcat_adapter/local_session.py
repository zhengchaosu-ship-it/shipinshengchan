"""仅Windows进程身份/会话检查；不捕获或控制桌面，不读取应用凭证。"""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import socket
from .desktop_worker.resident_monitor import native_presence


def process_user_sid(pid=None):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    advapi=ctypes.WinDLL('advapi32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    kernel.LocalFree.argtypes=[ctypes.c_void_p]
    advapi.OpenProcessToken.argtypes=[wintypes.HANDLE,wintypes.DWORD,ctypes.POINTER(wintypes.HANDLE)]
    advapi.GetTokenInformation.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]
    advapi.ConvertSidToStringSidW.argtypes=[ctypes.c_void_p,ctypes.POINTER(wintypes.LPWSTR)]
    process=kernel.OpenProcess(0x1000,False,pid or os.getpid())
    if not process:raise ctypes.WinError(ctypes.get_last_error())
    token=wintypes.HANDLE()
    try:
        if not advapi.OpenProcessToken(process,8,ctypes.byref(token)):
            raise ctypes.WinError(ctypes.get_last_error())
        length=wintypes.DWORD()
        advapi.GetTokenInformation(token,1,None,0,ctypes.byref(length))
        buffer=ctypes.create_string_buffer(length.value)
        if not advapi.GetTokenInformation(token,1,buffer,length,ctypes.byref(length)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid=ctypes.cast(buffer,ctypes.POINTER(ctypes.c_void_p))[0]
        text=wintypes.LPWSTR()
        if not advapi.ConvertSidToStringSidW(sid,ctypes.byref(text)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:return text.value
        finally:kernel.LocalFree(ctypes.cast(text,ctypes.c_void_p))
    finally:
        if token:kernel.CloseHandle(token)
        kernel.CloseHandle(process)


def check_session(config):
    if os.name!='nt' or socket.gethostname().casefold()!=config['hostname'].casefold():
        raise PermissionError('LOCAL_WINDOWS_HOST_REQUIRED')
    if process_user_sid()!=config['windows_user_sid']:
        raise PermissionError('WINDOWS_USER_MISMATCH')
    presence=native_presence(config['xiaovcat_executable'])
    if not presence['interactive_session_present']:
        raise RuntimeError('WINDOWS_INTERACTIVE_LOGIN_REQUIRED')
    if not presence['xiaovcat_process_present']:
        raise RuntimeError('XIAOVCAT_PROCESS_NOT_PRESENT')
    if any(process_user_sid(pid)!=config['windows_user_sid'] for pid in presence['process_ids']):
        raise PermissionError('XIAOVCAT_USER_MISMATCH')
    from .desktop_worker.electron_probe import require_interactive_session
    require_interactive_session()  # 只读默认输入桌面检查，锁屏/安全桌面停止。
    return presence
