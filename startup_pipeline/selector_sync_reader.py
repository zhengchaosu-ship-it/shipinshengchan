"""后台网页单组同步调用器：短暂连接前台输入队列，原读取器仍验证小V猫前台。"""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import json
from pathlib import Path


@contextmanager
def foreground_queue(target_hwnd):
    from xiaovcat_adapter.desktop_worker.electron_probe import require_interactive_session
    session = require_interactive_session()
    user = ctypes.WinDLL('user32',use_last_error=True)
    kernel = ctypes.WinDLL('kernel32',use_last_error=True)
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowThreadProcessId.restype = wintypes.DWORD
    user.AttachThreadInput.argtypes = [wintypes.DWORD,wintypes.DWORD,wintypes.BOOL]
    user.AttachThreadInput.restype = wintypes.BOOL
    kernel.GetCurrentThreadId.restype = wintypes.DWORD
    current = kernel.GetCurrentThreadId()
    foreground = user.GetForegroundWindow()
    owner = user.GetWindowThreadProcessId(foreground,None) if foreground else 0
    target = user.GetWindowThreadProcessId(target_hwnd,None)
    print(json.dumps({'stage':'FOREGROUND_QUEUE','session_id':session['session_id'],
        'current_thread':current,'foreground_thread':owner,'foreground_hwnd':hex(foreground or 0),
        'target_thread':target,'target_hwnd':hex(target_hwnd)},
        ensure_ascii=False),flush=True)
    attached = []
    try:
        # 前台与目标都是当前交互桌面的已核验窗口；后台调用线程同时连接两者的输入队列。
        for thread in dict.fromkeys([owner,target]):
            if thread and thread != current:
                if not user.AttachThreadInput(current,thread,True):
                    raise RuntimeError('FOREGROUND_QUEUE_ATTACH_FAILED')
                attached.append(thread)
        yield
    finally:
        for thread in reversed(attached):
            user.AttachThreadInput(current,thread,False)


def main():
    import argparse
    from xiaovcat_adapter.group_sync import GroupSyncUI
    from xiaovcat_adapter.desktop_worker.electron_probe import main_window,settings
    parser=argparse.ArgumentParser()
    parser.add_argument('--group-id',required=True)
    parser.add_argument('--expected-account-id',action='append',required=True)
    parser.add_argument('--results',type=Path,required=True)
    parser.add_argument('--no-screenshots',action='store_true')
    args=parser.parse_args()
    # 仅在原PrepareUI定位真实主窗口并确认前台期间连接队列，不改变原激活/焦点守卫。
    window=main_window(settings())
    with foreground_queue(int(window['hwnd'],16)):
        reader=GroupSyncUI(args.results,capture_screenshots=not args.no_screenshots)
    result=reader.sync_group(args.group_id,args.expected_account_id)
    print(json.dumps({'group_ids':[g['group_id'] for g in result['groups']],
                      'accounts':result['accounts'],'submit_calls':result['submit_calls']},ensure_ascii=False))


if __name__=='__main__':main()
