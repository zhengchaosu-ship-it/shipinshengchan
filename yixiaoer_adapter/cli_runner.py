"""Windows无窗口进程入口；保留管道、返回码与超时，不做重试。"""
import os
import subprocess


def hidden_process_options():
    if os.name != 'nt':
        return {}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    return {'creationflags': subprocess.CREATE_NO_WINDOW, 'startupinfo': startup}


def run_hidden(command, *, backend=None, **kwargs):
    """直接执行参数数组，拒绝shell；测试可注入原有runner。"""
    if isinstance(command, (str, bytes)) or kwargs.get('shell'):
        raise ValueError('DIRECT_PROCESS_ARGUMENT_LIST_REQUIRED')
    options = hidden_process_options()
    if options:
        # 禁止CREATE_NEW_CONSOLE覆盖无窗口策略。
        flags = kwargs.get('creationflags', 0) & ~subprocess.CREATE_NEW_CONSOLE
        kwargs['creationflags'] = flags | options['creationflags']
        kwargs['startupinfo'] = options['startupinfo']
    kwargs['shell'] = False
    kwargs.setdefault('capture_output', True)
    return (backend or subprocess.run)(command, **kwargs)


class YixiaoerCliRunner:
    """accounts/health/validate/upload/publish/query统一经此入口。"""
    def __init__(self, *, backend=None):
        self.backend = backend

    @staticmethod
    def launch_policy():
        return {'runner': 'YixiaoerCliRunner', 'shell': False,
                'windows_no_window': os.name == 'nt',
                'creationflags': subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                'startup_show_window': 'SW_HIDE' if os.name == 'nt' else None}

    def __call__(self, command, **kwargs):
        return run_hidden(command, backend=self.backend, **kwargs)
