"""发布页只读运行状态；进程存活不等于真实发布执行器可用。"""
import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path


def pid_alive(pid):
    if os.name != 'nt' or not isinstance(pid, int) or pid <= 0:
        return False
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_uint32()
        return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally:
        kernel.CloseHandle(handle)


def publish_worker_health(config_path, *, now=None, alive=pid_alive):
    result = dict(status='OFFLINE', worker_id='XIAOVCAT-WORKER-SERVER-01',
                  last_heartbeat=None, process_online=False, reason='CONFIG_UNAVAILABLE')
    try:
        config = json.loads(Path(config_path).read_text('utf-8'))
        result['worker_id'] = config['worker_id']
        beat = json.loads((Path(config['runtime_dir'])/'heartbeat.json').read_text('utf-8'))
        result['last_heartbeat'] = beat.get('last_heartbeat')
        stamp = datetime.fromisoformat(beat['last_heartbeat'])
        age = ((now or datetime.now(timezone.utc)) - stamp).total_seconds()
        result['process_online'] = (beat.get('worker_id') == config['worker_id']
                                    and 0 <= age <= 75 and alive(beat.get('pid')))
        if not result['process_online']:
            result['reason'] = 'HEARTBEAT_STALE_OR_PROCESS_MISSING'
        elif not config.get('worker_enabled'):
            result['reason'] = 'EXECUTOR_DISABLED_OBSERVER_ONLY'
        elif beat.get('status') in {'HALTED_NEEDS_MANUAL', 'DISABLED'}:
            result['reason'] = beat.get('failure_code') or beat['status']
        elif not beat.get('interactive_session_present') or not beat.get('xiaovcat_process_present'):
            result['reason'] = 'INTERACTIVE_XIAOVCAT_SESSION_UNAVAILABLE'
        else:
            result.update(status='ONLINE', reason=None)
    except (OSError, ValueError, KeyError, TypeError):
        pass  # 缺失/损坏/无时区状态不得冒称ONLINE；不影响保存计划。
    return result


def render_publish_worker_health(st, config_path):
    health = publish_worker_health(config_path)
    st.caption(f'Publish Worker：{health["status"]} · {health["worker_id"]} · '
               f'last_heartbeat：{health["last_heartbeat"] or "无"}')
    if health['status'] != 'ONLINE':
        st.warning('发布Worker离线，计划可以保存，但暂不会执行。' +
                   ('常驻观察进程在线，但真实执行未启用。' if health['process_online'] else '') +
                   ' ' + str(health['reason']))
    return health
