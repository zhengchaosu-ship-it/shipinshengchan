"""只读SMB诊断：Windows错误码，不读取/输出凭据。"""
import ctypes
import json
import socket


class Resource(ctypes.Structure):
    _fields_=[('scope',ctypes.c_uint),('type',ctypes.c_uint),('display',ctypes.c_uint),
              ('usage',ctypes.c_uint),('local',ctypes.c_wchar_p),('remote',ctypes.c_wchar_p),
              ('comment',ctypes.c_wchar_p),('provider',ctypes.c_wchar_p)]


def main():
    mpr=ctypes.WinDLL('mpr',use_last_error=True)
    mpr.WNetAddConnection2W.argtypes=[ctypes.POINTER(Resource),ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_uint]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetFileAttributesW.argtypes=[ctypes.c_wchar_p]
    kernel.GetFileAttributesW.restype=ctypes.c_uint
    results=[]
    for host in ('192.168.1.126','PC-20260617GEOP'):
        remote='\\\\'+host+'\\RenderOutput'
        item=Resource(type=1,remote=remote)
        error=mpr.WNetAddConnection2W(ctypes.byref(item),None,None,0)
        ctypes.set_last_error(0)
        attr=kernel.GetFileAttributesW(remote)
        results.append(dict(host=host,connect_error=error,stat_error=ctypes.get_last_error(),attributes=attr))
    print(json.dumps({'hostname':socket.gethostname(),'shares':results}))


if __name__=='__main__':main()
