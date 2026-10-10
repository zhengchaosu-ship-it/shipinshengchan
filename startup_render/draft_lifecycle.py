"""剪映5.9名称核验与刷新；不领取任务、不补素材、不操作发布。"""
from pathlib import Path
import re
import time

from .common import read


def official_name(manifest):
    name = manifest.get('draft_name')
    if (not isinstance(name, str) or not name or name in {'.', '..'}
            or re.search(r'[\\/:*?"<>|\x00-\x1f]', name)
            or name.endswith(('.', ' '))
            or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', name, re.I)):
        raise ValueError('UNSAFE_DRAFT_NAME')
    return name


def verify_names(job):
    """5.9列表名称来自draft_meta_info；content.name不是列表名的依据。"""
    name = official_name(job['manifest'])
    folder = Path(job['draft'])
    meta = read(folder / 'draft_meta_info.json')
    evidence = {'business_draft_name': name, 'filesystem_draft_name': folder.name,
                'metadata_draft_name': meta.get('draft_name'),
                'output_name': Path(job['output']).name}
    if (folder.name != name or meta.get('draft_name') != name
            or Path(meta.get('draft_fold_path', '')).resolve() != folder.resolve()
            or Path(meta.get('draft_root_path', '')).resolve() != folder.parent.resolve()
            or (job['manifest'].get('target_account_id')
                and Path(job['output']).name != name + '.mp4')):
        raise RuntimeError('DRAFT_NAME_MISMATCH:' + str(evidence))
    return evidence


def visible_names(controller):
    """读取库实际使用的FullDescription，不用业务字段冒充UI回读。"""
    controller.get_window()
    if controller.app_status != 'home':
        raise RuntimeError('JIANYING_BUSY_NO_CLOSE')
    if isinstance(getattr(controller,'snapshot',None),dict):
        return [n['description'].removeprefix('HomePageDraftTitle:')
                for t in controller.snapshot['trees'] for n in t['nodes']
                if n.get('description','').startswith('HomePageDraftTitle:')]
    result = []
    def walk(control, depth):
        if depth > 3:
            return
        if depth and control.ControlTypeName == 'WindowControl':
            raise RuntimeError('UNKNOWN_DIALOG_NEEDS_MANUAL')
        desc = str(control.GetPropertyValue(30159) or '')
        if desc.startswith('HomePageDraftTitle:'):
            result.append(desc.removeprefix('HomePageDraftTitle:'))
        for child in control.GetChildren():
            walk(child, depth + 1)
    walk(controller.app, 0)
    return result


def wait_for(predicate, timeout, *, clock=time.monotonic, pause=time.sleep):
    deadline = clock() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if clock() >= deadline:
            return None
        pause(min(.5, max(0, deadline - clock())))


def close_home(factory, processes, close, emit, *, timeout=30, wait=wait_for):
    active = processes()
    emit('JIANYING_CLOSING', processes=active)
    if active:
        controller = factory()
        # 编辑、导出、保存或未知弹窗均不发送关闭，不强杀进程。
        visible_names(controller)
        emit('CLOSE_REQUESTED')
        close(controller)
        if not wait(lambda: not processes(), timeout):
            raise RuntimeError('JIANYING_CLOSE_TIMEOUT_NEEDS_MANUAL')
    emit('PROCESS_EXITED')


def restart_and_discover(job, factory, processes, close, launch, verify_version,
                         emit, *, ready_timeout=60, wait=wait_for):
    verify_names(job)
    verify_version('before_restart')
    close_home(factory, processes, close, emit, wait=wait)
    emit('JIANYING_RESTARTING')
    launch()
    latest = {'controller': None, 'names': [], 'error': None}
    def ready():
        try:
            controller = factory()  # 重新取得真实UI根，不重用旧句柄。
            names = visible_names(controller)
            latest.update(controller=controller, names=names, error=None)
            # 实际home和草稿列表特征必须存在；空列表不判为ready。
            return controller if names else None
        except Exception as error:
            if str(error).startswith(('VERSION_DRIFT', 'JIANYING_LOGIN_REQUIRED')):
                raise
            latest['error'] = str(error)
            return None
    controller = wait(ready, ready_timeout)
    if controller is None:
        emit('JIANYING_UI_NOT_READY', error=latest['error'])
        raise RuntimeError('JIANYING_UI_NOT_READY')
    verify_version('after_restart')
    emit('JIANYING_UI_READY', visible_names=latest['names'], processes=processes())
    expected = official_name(job['manifest'])
    if isinstance(getattr(controller,'snapshot',None),dict):
        if not controller.find_draft(expected):raise RuntimeError('JIANYING_DRAFT_NOT_VISIBLE')
    def found():
        latest['names'] = visible_names(controller)
        return expected in latest['names']
    if not wait(found, ready_timeout):
        error = ('DRAFT_NAME_MISMATCH' if 'XZ-' + job['manifest']['job_id'] in latest['names']
                 else 'JIANYING_DRAFT_NOT_VISIBLE')
        emit(error, expected=expected, visible_names=latest['names'])
        raise RuntimeError(error)
    emit('JIANYING_DRAFT_VISIBLE', business_draft_name=expected,
         actual_visible_draft_name=expected, filesystem_draft_name=Path(job['draft']).name)
    return controller
