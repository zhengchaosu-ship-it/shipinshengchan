"""进程间唯一媒体锁；命名空间覆盖同一Windows主机的所有会话。"""
from contextlib import contextmanager
import ctypes
import os
import threading

from . import WORKSTATION_MEDIA_EXECUTION_LOCK

_threads = threading.Lock()


class LaneBusy(RuntimeError):
    pass


@contextmanager
def media_lock():
    # Named Mutex本身允许同线程递归获取；额外闩锁禁止嵌套重任务。
    if not _threads.acquire(blocking=False):
        raise LaneBusy('WAITING_FOR_WORKSTATION')
    handle = None
    acquired = False
    try:
        if os.name != 'nt':
            raise RuntimeError('WINDOWS_EXECUTION_NODE_REQUIRED')
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.WaitForSingleObject.restype = ctypes.c_uint32
        kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.CreateMutexW(None, False, WORKSTATION_MEDIA_EXECUTION_LOCK)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        result = kernel.WaitForSingleObject(handle, 0)
        acquired = result in (0, 0x80)
        if not acquired:
            if result == 0x102:
                raise LaneBusy('WAITING_FOR_WORKSTATION')
            raise ctypes.WinError(ctypes.get_last_error())
        # abandoned只证明旧进程退出。Coordinator随后仍须执行Server/journal恢复。
        yield {'abandoned': result == 0x80}
    finally:
        if handle:
            if acquired:
                kernel.ReleaseMutex(handle)
            kernel.CloseHandle(handle)
        _threads.release()
