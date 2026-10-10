"""每次读/单次输入一个MTA进程。JSON边界不允许传出Control/COM proxy。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def call(config,job,operation='read',**payload):
    # pythonw经venv包装时不能可靠收割；优先同环境内真实解释器。
    executable=getattr(sys,'_base_executable',sys.executable)
    request={'config':config,'job':job,'operation':operation,**payload}
    try:
        child=subprocess.run([executable,'-X','utf8','-B','-m','startup_render.uia_probe'],
            input=json.dumps(request,ensure_ascii=True),capture_output=True,encoding='utf-8',
            timeout=config.get('uia_probe_timeout',12),
            env={**os.environ,'PYTHONPATH':os.pathsep.join(sys.path)},
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        result=json.loads(child.stdout)
    except subprocess.TimeoutExpired:
        return {'ok':False,'error':'UIA_PROBE_TIMEOUT','input_dispatched':operation!='read','at':time.time()}
    except (ValueError,OSError) as error:
        return {'ok':False,'error':'UIA_PROBE_RESULT_UNKNOWN:'+type(error).__name__,
                'input_dispatched':operation!='read','at':time.time()}
    return result


def matching_node(snapshot,node):
    keys=('hwnd','name','description','class','type','rect')
    rows=[n for tree in snapshot['trees'] for n in tree['nodes'] if all(n.get(k)==node.get(k) for k in keys)]
    if len(rows)!=1:raise RuntimeError('STALE_UIA_CONTROL_NO_CLICK')
    return rows[0]


def main():
    # comtypes首次import会初始化当前线程；必须在所有UIA导入之前设定MTA。
    sys.coinit_flags=0
    request=json.load(sys.stdin);result={'ok':False,'pid':os.getpid(),'input_dispatched':False,'at':time.time()}
    ui=None
    try:
        import ctypes, threading
        import comtypes
        import uiautomation as uia
        from .export_ui import JianyingExportUi
        from .draft_ready import snapshot_problem
        from xiaovcat_adapter.desktop_worker.electron_probe import require_interactive_session
        session=require_interactive_session()
        apartment=ctypes.c_int();qualifier=ctypes.c_int()
        status=ctypes.OleDLL('ole32').CoGetApartmentType(ctypes.byref(apartment),ctypes.byref(qualifier))
        if status or apartment.value!=1:raise RuntimeError('UIA_MTA_REQUIRED')
        result.update(thread_id=threading.get_native_id(),apartment='MTA',session=session)
        uia.GetRootControl().Name  # 即使没有剪映窗口，也真正核验UIA服务。
        ui=JianyingExportUi(request['config'],request['job'],isolated=True)
        snapshot=ui._capture('probe',persist=False)
        snapshot['probe']={k:result[k] for k in ('pid','thread_id','apartment','session')}
        operation=request['operation']
        if operation!='read':
            problem=snapshot_problem(snapshot)
            if problem:raise RuntimeError('UI_NOT_STABLE_NO_INPUT:'+problem)
            old=request['snapshot']
            from .export_state import known_modal, settings_menu_input_allowed
            if snapshot['detection']['state']!=old['detection']['state']:
                raise RuntimeError('UI_STATE_CHANGED_NO_INPUT')
            if snapshot['detection']['state']=='UNKNOWN_MODAL' and not known_modal(snapshot):
                raise RuntimeError('UNKNOWN_MODAL_NO_INPUT')
            def identity(s):
                window=next((w for w in s['windows'] if w['hwnd']==request['node']['hwnd']),None)
                if not window:return None
                process=next((p for p in s['processes'] if p['pid']==window['pid']),None)
                return (window['hwnd'],window['pid'],process['create_time']) if process else None
            if identity(old)!=identity(snapshot):raise RuntimeError('PROCESS_GENERATION_CHANGED_NO_INPUT')
            ui.snapshot=snapshot
            node=matching_node(snapshot,request['node'])
            if snapshot['detection']['state']=='EXPORT_SETTINGS_MENU' and not settings_menu_input_allowed(snapshot,node):
                raise RuntimeError('SETTINGS_MENU_ONLY_NO_UNDERLYING_INPUT')
            if operation=='click':
                import contextlib
                with contextlib.redirect_stdout(sys.stderr):ui._click_local(node)
                result['input_dispatched']=ui.input_dispatched
            elif operation=='scroll':
                if not ui.inside(node):raise RuntimeError('SCROLL_TARGET_NOT_VISIBLE')
                user=ctypes.WinDLL('user32');user.GetForegroundWindow.restype=ctypes.c_void_p
                user.GetWindowThreadProcessId.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
                foreground_pid=ctypes.c_ulong()
                user.GetWindowThreadProcessId(user.GetForegroundWindow(),ctypes.byref(foreground_pid))
                control=ui.controls[(node['hwnd'],node['index'])];root=ui.controls[(node['hwnd'],0)]
                if foreground_pid.value!=root.ProcessId:
                    from startup_pipeline.selector_sync_reader import foreground_queue
                    import contextlib
                    with contextlib.redirect_stdout(sys.stderr),foreground_queue(root.NativeWindowHandle):root.SetActive()
                    raise RuntimeError('FOCUS_CHANGED_REOBSERVE_BEFORE_CLICK')
                result['input_dispatched']=True
                # Control.WheelDown先SetFocus，会让Qt列表滚回获焦卡片。已核对前台后直接滚动。
                a,b,c,d=node['rect']
                hit=uia.ControlFromPoint((a+c)//2,(b+d)//2)
                if hit.ProcessId!=root.ProcessId:raise RuntimeError('SCROLL_TARGET_OCCLUDED')
                uia.SetCursorPos((a+c)//2,(b+d)//2)
                wheel=uia.WheelUp if request.get('direction')=='up' else uia.WheelDown
                notches=request.get('notches',1)
                if not isinstance(notches,int) or not 1<=notches<=3:raise ValueError('INVALID_SCROLL_DISTANCE')
                wheel(notches,.1,1)
            else:raise ValueError('UNKNOWN_UIA_OPERATION')
        result.update(ok=True,snapshot=snapshot)
    except Exception as error:
        if ui is not None:result['input_dispatched']=result['input_dispatched'] or ui.input_dispatched
        import traceback
        result.update(error=type(error).__name__+':'+str(error),hresult=getattr(error,'hresult',None))
        result['traceback']=traceback.format_exc()
    # 所有COM对象随进程终止释放，不在主Render进程重建全局singleton。
    print(json.dumps(result,ensure_ascii=True))


if __name__=='__main__':main()
