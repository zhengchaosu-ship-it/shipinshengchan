"""本机共享GUI生产通道；沿用原Render的同名Windows互斥，不涉及桌面输入。"""
from contextlib import contextmanager
import ctypes
import time

NAME='Local\\XiaovcatDesktopWorkerV03'


@contextmanager
def desktop_ui_lane(*,wait_seconds=0,waiting=lambda:None):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p]
    kernel.CreateMutexW.restype=ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32]
    kernel.ReleaseMutex.argtypes=kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=kernel.CreateMutexW(None,False,NAME)
    if not handle:raise RuntimeError('UI_LANE_CREATE_FAILED')
    acquired=False;notified=False;deadline=time.monotonic()+wait_seconds
    try:
        while True:
            result=kernel.WaitForSingleObject(handle,0)
            if result==0:acquired=True;break
            if result==0x80:
                acquired=True;raise RuntimeError('UI_LANE_ABANDONED_NEEDS_MANUAL')
            if result!=258:raise RuntimeError('UI_LANE_WAIT_FAILED')
            if not notified:waiting();notified=True
            if time.monotonic()>=deadline:raise RuntimeError('WAITING_UI_LANE')
            time.sleep(.2)
        yield
    finally:
        if acquired:kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)
