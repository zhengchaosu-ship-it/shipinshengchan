"""Windows Job只管理本入口启动的Server进程，父入口退出时关闭整个子树。"""
import ctypes
from ctypes import wintypes


class BasicLimits(ctypes.Structure):
    _fields_ = [('ProcessTime',ctypes.c_longlong),('JobTime',ctypes.c_longlong),
                ('Flags',wintypes.DWORD),('MinWorkingSet',ctypes.c_size_t),
                ('MaxWorkingSet',ctypes.c_size_t),('ActiveProcessLimit',wintypes.DWORD),
                ('Affinity',ctypes.c_size_t),('PriorityClass',wintypes.DWORD),
                ('SchedulingClass',wintypes.DWORD)]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [('Basic',BasicLimits),('Io',ctypes.c_ulonglong*6),
                ('ProcessMemoryLimit',ctypes.c_size_t),('JobMemoryLimit',ctypes.c_size_t),
                ('PeakProcessMemoryUsed',ctypes.c_size_t),('PeakJobMemoryUsed',ctypes.c_size_t)]


def kernel():
    api = ctypes.WinDLL('kernel32',use_last_error=True)
    api.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR]
    api.CreateJobObjectW.restype=wintypes.HANDLE
    api.OpenJobObjectW.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.LPCWSTR]
    api.OpenJobObjectW.restype=wintypes.HANDLE
    api.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
    api.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]
    api.GetCurrentProcess.restype=wintypes.HANDLE
    api.CloseHandle.argtypes=[wintypes.HANDLE]
    return api


def create(name):
    api=kernel(); handle=api.CreateJobObjectW(None,name)
    if not handle: raise ctypes.WinError(ctypes.get_last_error())
    limits=ExtendedLimits(); limits.Basic.Flags=0x2000  # KILL_ON_JOB_CLOSE
    if not api.SetInformationJobObject(handle,9,ctypes.byref(limits),ctypes.sizeof(limits)):
        error=ctypes.get_last_error(); api.CloseHandle(handle); raise ctypes.WinError(error)
    return handle


def join(name):
    # 实际解释器自加入，覆盖venv启动器早于父入口Assign就创建解释器的竞态。
    api=kernel(); handle=api.OpenJobObjectW(0x0001,False,name)  # ASSIGN_PROCESS
    if not handle: raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not api.AssignProcessToJobObject(handle,api.GetCurrentProcess()):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        api.CloseHandle(handle)  # 只有父入口保留Job句柄；父死亡立即收口Server子树。


def close(handle):
    kernel().CloseHandle(handle)
