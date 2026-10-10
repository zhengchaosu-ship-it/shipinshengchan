"""2060S导出交接；没有真实发布入口，不修改已有小V猫Worker。"""
import argparse
from contextlib import contextmanager
import ctypes
from datetime import datetime, timezone
import json
import http.client
import logging
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit

from .common import below, digest, identifier, media_probe, normalized, read, rewrite, save


def event(folder, status, **detail):
    path = Path(folder) / 'events.json'
    events = read(path) if path.exists() else []
    at = datetime.now(timezone.utc).isoformat()
    timestamp_field = {'CLOSE_REQUESTED': 'close_requested_at', 'PROCESS_EXITED': 'process_exited_at',
                       'JIANYING_RESTARTING': 'restart_at', 'JIANYING_UI_READY': 'ui_ready_at'}.get(status)
    if timestamp_field:
        detail[timestamp_field] = at
    events.append({'status': status, 'at': at, **detail})
    save(path, events)


def upload_result(config, state, output, media):
    url = urlsplit(config['server_url'])
    connection = http.client.HTTPConnection(url.hostname, url.port, timeout=180)
    try:
        connection.putrequest('PUT', '/result/' + state['manifest']['job_id'])
        for key, value in {'Content-Length': str(media['size']), 'X-Claim': state['claim'], 'X-SHA256': media['sha256']}.items():
            connection.putheader(key, value)
        connection.endheaders()
        with Path(output).open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''): connection.send(block)
        response = connection.getresponse()
        value = json.loads(response.read())
        if response.status != 200: raise ValueError('HOST_RESULT_REJECTED:' + str(value.get('error')))
        return value
    finally:
        connection.close()


@contextmanager
def mutex(name):
    # 与既有发布Worker使用同一桌面互斥锁；崩溃后不自动重复导出。
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateMutexW(None, False, name)
    if not handle:
        raise OSError('MUTEX_CREATE_FAILED')
    acquired = False
    try:
        result = kernel.WaitForSingleObject(handle, 0)
        acquired = result in (0, 0x80)
        if result != 0:
            raise RuntimeError('DESKTOP_BUSY_OR_ABANDONED')
        yield
    finally:
        if acquired:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


def request(base, route, value=None):
    body = None if value is None else json.dumps(value).encode()
    req = urllib.request.Request(base.rstrip('/') + route, data=body,
                                 headers={'Content-Type': 'application/json'})
    # 仅直连配置的局域网服务，不通过环境HTTP代理传素材。
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(req, timeout=60)


def download(config, manifest, folder):
    entries = manifest['files']
    if not entries or len(entries) > 3000:
        raise ValueError('INVALID_FILE_COUNT')
    relatives = [e['relative'].casefold() for e in entries]
    if len(set(relatives)) != len(relatives):
        raise ValueError('DUPLICATE_FILE_PATH')
    total = sum(e['size'] for e in entries)
    if total != manifest['total_bytes'] or total > config.get('max_package_bytes', 20 * 1024**3):
        raise ValueError('PACKAGE_LIMIT_EXCEEDED')
    folder.mkdir(parents=True, exist_ok=False)
    if shutil.disk_usage(folder).free < total + 5 * 1024**3:
        raise ValueError('INSUFFICIENT_DISK_SPACE')
    for index, entry in enumerate(entries):
        if entry['size'] < 0 or not entry['relative'].startswith(('draft/', 'assets/')):
            raise ValueError('INVALID_FILE_ENTRY')
        target = below(folder, entry['relative'])
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + '.part')
        count = 0
        with request(config['server_url'], '/file/%s/%d' % (identifier(manifest['job_id']), index)) as source, partial.open('xb') as out:
            while block := source.read(1024 * 1024):
                count += len(block)
                if count > entry['size']:
                    raise ValueError('FILE_SIZE_EXCEEDED')
                out.write(block)
        if count != entry['size'] or digest(partial) != entry['sha256']:
            raise ValueError('TRANSFER_HASH_MISMATCH')
        partial.replace(target)


def install_draft(config, manifest, folder, evidence_folder=None):
    from .draft_lifecycle import official_name
    from .draft_install import actual_draft_root, install_check
    if 'jianying_settings' in config:
        actual_draft_root(config)  # 复制之前确认是剪映真实扫描目录，不只是Worker存储目录。
    elif '_config_path' in config:
        raise RuntimeError('DRAFT_ROOT_NOT_VERIFIED')
    identifier(manifest['job_id'])  # 中文展示名称不是任务主键。
    name = official_name(manifest)
    target = below(config['draft_root'], name)
    if target.exists():
        raise FileExistsError('DRAFT_ALREADY_EXISTS_NO_OVERWRITE')
    # 仅安装接收的新草稿副本；原始时间线、源草稿及素材保持不变。
    mapping = {normalized(manifest['draft_source']): str(target),
               normalized(str(Path(manifest['draft_source']).parent)): str(target.parent)}
    for entry in manifest['files']:
        local = (below(target, entry['relative'][6:]) if entry['relative'].startswith('draft/')
                 else below(folder, entry['relative']))
        mapping[normalized(entry['source'])] = str(local)
    shutil.copytree(folder / 'draft', target)
    for path in target.rglob('*.json'):
        value = rewrite(read(path), mapping)
        if path.name == 'draft_meta_info.json':
            value['draft_name'] = name
            value['draft_fold_path'] = str(target)
            value['draft_root_path'] = str(target.parent)
            value['draft_is_invisible'] = False
        save(path, value)
    meta = read(target / 'draft_meta_info.json')
    if meta.get('draft_name') != name or Path(meta['draft_fold_path']).resolve() != target.resolve():
        raise RuntimeError('DRAFT_NAME_MISMATCH')
    evidence = Path(evidence_folder) if evidence_folder else folder.parent
    save(evidence / 'source_to_worker.json', [dict(e, worker_path=mapping[normalized(e['source'])]) for e in manifest['files']])
    save(evidence / 'installed_draft.json', {'content_id': manifest['content_id'],
         'business_draft_name': name, 'metadata_draft_name': meta['draft_name'], 'draft_path': str(target)})
    if 'jianying_settings' in config:
        event(evidence, 'DRAFT_INSTALLED', draft_path=str(target))
        result = install_check(config, target, name)
        save(evidence / 'DRAFT_INSTALL_CHECK.json', result)
        event(evidence, 'DRAFT_FILES_VALIDATED', **result)
    return target


def dedicated_entry(config, evidence, stage, *, check_only, runner=subprocess.run):
    """仅调用2060S已部署入口；不是新的launcher，不提供EXE直启回退。"""
    entry = Path(config.get('jianying_launcher', ''))
    name = config.get('jianying_launcher_name')
    def drift(reason):
        event(evidence, 'VERSION_DRIFT', stage=stage, reason=reason)
        raise RuntimeError('VERSION_DRIFT:' + reason)
    if name != '剪映5.9RENDER WORKER' or not entry.is_absolute() or not entry.is_file():
        drift('DEDICATED_LAUNCHER_REQUIRED')
    if digest(entry) != config.get('jianying_launcher_sha256', '').lower():
        drift('DEDICATED_LAUNCHER_SHA_MISMATCH')
    command = [config['powershell'], '-NoProfile', '-File', str(entry)]
    if check_only:
        command.append('-CheckOnly')
    try:
        result = runner(command, capture_output=True, timeout=60,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except Exception as error:
        drift('DEDICATED_LAUNCHER_CALL_FAILED:' + type(error).__name__)
    (Path(evidence) / ('launcher_' + stage + '.stdout.txt')).write_bytes(result.stdout)
    (Path(evidence) / ('launcher_' + stage + '.stderr.txt')).write_bytes(result.stderr)
    if result.returncode:
        drift('DEDICATED_LAUNCHER_REJECTED')
    if not check_only:
        if result.stdout.decode('utf-8-sig', errors='replace').strip() != 'JIANYING59_STARTED':
            drift('DEDICATED_LAUNCHER_DID_NOT_START_NEW_INSTANCE')
        return {'launcher_name': name, 'launcher_path': str(entry.resolve())}
    try:
        version = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        drift('DEDICATED_LAUNCHER_CHECK_INVALID')
    if (version.get('status') != 'VERSION_OK' or version.get('version') != '5.9.0.11632'
            or Path(version.get('path', '')).resolve() != Path(config['jianying_exe']).resolve()
            or version.get('sha256', '').lower() != config['jianying_sha256'].lower()
            or version.get('signature') != 'Valid'):
        drift('DEDICATED_LAUNCHER_VERSION_DRIFT')
    save(Path(evidence) / ('version_check_' + stage + '.json'), version)
    return version


def check_jianying_login(windows, evidence, stage, *, log_clear=True):
    """复用现有只读窗口清单识别已证实登录阻塞，不读取或操作认证表单。

    没有登录弹窗仅代表当前无阻塞，不能证明会话永不过期；导出期间仍检查。
    """
    login = [w for w in windows if w.get('visible') and w.get('enabled')
             and w.get('title') == '登录']
    if login:
        event(evidence, 'JIANYING_LOGIN_REQUIRED', stage=stage,
              authentication_windows=[{k: w.get(k) for k in ('hwnd', 'pid', 'title')} for w in login])
        raise RuntimeError('JIANYING_LOGIN_REQUIRED')
    if log_clear:
        event(evidence, 'JIANYING_LOGIN_CHECK', stage=stage, result='NO_LOGIN_MODAL_DETECTED')


def render_child(config, job, *, draft_open_only=False):
    """复用已验证的5.9库。版本/桌面未知时停止，不操作发布界面。"""
    import psutil
    from media_execution.workstation_health import owned_pids, current_launch_pids, read_optional, owner_path, record_launch,adopt_environment_relaunch
    initial=[p.info for p in psutil.process_iter(['pid','name','create_time','ppid'])
             if (p.info['name'] or '').lower() in ('jianyingpro.exe','vedetector.exe')]
    if initial and owned_pids(initial,read_optional(owner_path(config)),config['worker_id'])!={p['pid'] for p in initial}:
        raise RuntimeError('WORKSTATION_MANUAL_USE_NO_CLOSE')
    from types import SimpleNamespace
    from .isolated_controller import IsolatedController
    from .draft_lifecycle import close_home, restart_and_discover, verify_names, visible_names
    engine = Path(config['jianying_exe']).resolve()
    evidence = Path(job['evidence_root'])
    names = verify_names(job)
    from .draft_install import install_check
    install_check(config, job['draft'], names['business_draft_name'])
    event(evidence, 'FILESYSTEM_DRAFT_READY', **names)
    def verify_version(stage):
        version = dedicated_entry(config, evidence, stage, check_only=True)
        event(evidence, 'VERSION_OK', stage=stage, launcher_name=config['jianying_launcher_name'],
              launcher_path=config['jianying_launcher'], jianying_exe_path=version['path'],
              jianying_version=version['version'], jianying_sha256=version['sha256'])
    def guard():
        def drift(reason):
            event(evidence, 'VERSION_DRIFT', reason=reason)
            raise RuntimeError('VERSION_DRIFT:' + reason)
        if digest(engine) != config['jianying_sha256'].lower():
            drift('JIANYING_SHA_MISMATCH')
        for process in psutil.process_iter(['name', 'exe']):
            if (process.info['name'] or '').lower() == 'jianyingpro.exe':
                if not process.info['exe'] or Path(process.info['exe']).resolve() != engine:
                    drift('OTHER_JIANYING_VERSION_RUNNING')
    def processes():
        guard()
        handle_environment_check()
        adopt_environment_relaunch(config,job)
        return [dict(pid=p.pid, started_at=datetime.fromtimestamp(p.info['create_time'], timezone.utc).isoformat(),
                     path=p.info['exe']) for p in psutil.process_iter(['name', 'exe', 'create_time'])
                if (p.info['name'] or '').lower() == 'jianyingpro.exe']
    handled_environment = set()
    def handle_environment_check():
        for p in psutil.process_iter(['name','exe','create_time']):
            if (p.info['name'] or '').lower() != 'vedetector.exe':continue
            key=(p.pid,p.info['create_time'])
            if key in handled_environment:continue
            from .export_ui import JianyingExportUi
            ui=JianyingExportUi(config,job)
            try:handler=ui.handle_known_modal()
            except RuntimeError as error:
                # 检测进程会早于成功窗口出现；下一次有界ready轮询重新观察。
                if str(error)=='UNKNOWN_MODAL:NO_APPROVED_HANDLER':return
                raise
            handled_environment.add(key)
            event(evidence,'KNOWN_MODAL_HANDLER',handler=handler)
    class GuardedController(IsolatedController):
        opened_logged = False
        login_checked = False
        def __init__(self):super().__init__(config,job)
        def get_window(self):
            guard()
            handle_environment_check()
            from xiaovcat_adapter.desktop_worker.electron_probe import app_windows
            check_jianying_login(app_windows({'process_name': 'JianyingPro.exe'}), evidence,
                                 'controller_get_window', log_clear=not self.login_checked)
            self.login_checked = True
            super().get_window()
            if self.app_status == 'edit' and not self.opened_logged:
                event(evidence, 'JIANYING_DRAFT_OPENED', expected_draft_name=names['business_draft_name'],
                      actual_window_class=self.app.ClassName)
                self.opened_logged = True
    owned = {}  # 仅跟踪本次专用入口的新实例；PID还必须匹配创建时间，防PID复用。
    launch_identity = {}
    def launch():
        if processes():
            raise RuntimeError('VERSION_DRIFT:PREVIOUS_JIANYING_NOT_EXITED')
        started = time.time()
        origin = dedicated_entry(config, evidence, 'start', check_only=False)
        from .draft_lifecycle import wait_for
        launched = wait_for(processes, 15)
        if not launched:
            event(evidence, 'VERSION_DRIFT', reason='DEDICATED_LAUNCHER_NO_PROCESS')
            raise RuntimeError('VERSION_DRIFT:DEDICATED_LAUNCHER_NO_PROCESS')
        for row in launched:
            if datetime.fromisoformat(row['started_at']).timestamp() < started:
                event(evidence, 'VERSION_DRIFT', reason='UNVERIFIED_REUSED_INSTANCE')
                raise RuntimeError('VERSION_DRIFT:UNVERIFIED_REUSED_INSTANCE')
            owned[row['pid']] = row['started_at']
        main = min(launched, key=lambda row: row['started_at'])
        version = dedicated_entry(config, evidence, 'launcher_started', check_only=True)
        event(evidence, 'VERSION_OK', stage='launcher_started')
        event(evidence, 'JIANYING_LAUNCH_SOURCE', **origin, jianying_exe_path=version['path'],
              jianying_version=version['version'], jianying_sha256=version['sha256'],
              process_id=main['pid'], started_at=main['started_at'], processes=launched)
        launch_identity.update(record_launch(config,job,launched,launch_time=started))
    def close(controller):
        # 正常WM_CLOSE，仅发给已核验的5.9首页；不强杀、不接受保存确认。
        guard()
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
        user32.PostMessageW.restype = ctypes.c_bool
        user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        hwnd = controller.app.NativeWindowHandle
        pid = ctypes.c_uint32()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        active = {p['pid']: p['started_at'] for p in processes()}
        if pid.value not in active:
            raise RuntimeError('JIANYING_WINDOW_IDENTITY_MISMATCH')
        if not owned:
            rows=[p.info for p in psutil.process_iter(['pid','name','create_time','ppid']) if p.pid in active]
            persisted=owned_pids(rows,read_optional(owner_path(config)),config['worker_id'])
            if set(active)!=persisted:raise RuntimeError('WORKSTATION_MANUAL_USE_NO_CLOSE')
            owned.update(active)
        if owned:
            # 环境检测可替换主PID；只合并相同Job/launch token下已验证的持久归属。
            if launch_identity:
                rows=[p.info for p in psutil.process_iter(['pid','name','create_time','ppid']) if p.pid in active]
                current=current_launch_pids(rows,read_optional(owner_path(config)),worker_id=config['worker_id'],
                    job_id=job['manifest']['job_id'],launch_token=launch_identity['launch_token'])
                owned.update({pid:active[pid] for pid in current})
            # 同入口后来生成的子进程也须可追溯到已有PID/创建时间，不接管另开的实例。
            parents = {p.pid: p.info['ppid'] for p in psutil.process_iter(['ppid']) if p.pid in active}
            for _ in range(len(active)):
                changed = False
                for child, parent in parents.items():
                    if child not in owned and parent in owned and active.get(parent) == owned[parent]:
                        owned[child] = active[child]
                        changed = True
                if not changed:
                    break
            if owned.get(pid.value) != active[pid.value]:
                raise RuntimeError('UNOWNED_JIANYING_INSTANCE_NEEDS_MANUAL')
        if not user32.PostMessageW(hwnd, 0x0010, 0, 0):
            raise RuntimeError('JIANYING_NORMAL_CLOSE_FAILED')
    emit = lambda status, **detail: event(evidence, status, **detail)
    from xiaovcat_adapter.desktop_ui_lane import desktop_ui_lane
    with desktop_ui_lane(wait_seconds=config.get('render_timeout',1800),
                         waiting=lambda:event(evidence,'WAITING_UI_LANE')):
        if Path(job['output']).exists():
            raise FileExistsError('EXPORT_ALREADY_EXISTS_NO_OVERWRITE')
        height = min(int(job['manifest']['canvas']['width']), int(job['manifest']['canvas']['height']))
        # 保留已验证的库枚举值；父Render进程不为几个字符串导入UIA/初始化STA。
        resolutions = {n:SimpleNamespace(value=caption) for n,caption in
                       ((480,'480P'),(720,'720P'),(1080,'1080P'),(1440,'2K'),(2160,'4K'),(4320,'8K'))}
        frames = {n:SimpleNamespace(value=str(n)+'fps') for n in (24,25,30,50,60)}
        fps = float(job['manifest']['fps'])
        if height not in resolutions or fps not in frames:
            raise ValueError('UNSUPPORTED_EXPORT_PROFILE')
        controller = restart_and_discover(job, GuardedController, processes, close,
            launch, verify_version, emit)
        # 导出前再次回读，绝不回退到组合X或XZ-content_id查找。
        expected = names['business_draft_name']
        if expected not in visible_names(controller):
            raise RuntimeError('DRAFT_NAME_MISMATCH')
        event(evidence, 'RENDERING_PRE_EXPORT')
        started = time.monotonic()
        from .export_ui import JianyingExportUi
        ui = JianyingExportUi(config, job)
        try:
            if draft_open_only:ui.open_existing_draft()
            else:ui.export_draft(resolutions[height], frames[fps], timeout=config.get('render_timeout', 1800))
        except Exception:
            # 已保存输入前及等待状态；失败再采集最新证据，不重复导出。
            try: ui.capture('halted')
            except Exception: logging.exception('export evidence capture failed')
            raise
        controller = GuardedController()
        controller.switch_to_home()
        event(evidence, 'DRAFT_OPEN_CHECK_PASSED' if draft_open_only else 'EXPORTED', export_duration=time.monotonic() - started)
        event(evidence, 'CLOSE_JIANYING')
        close_home(GuardedController, processes, close, emit)


class Agent:
    def __init__(self, config, renderer=None, probe=media_probe, transport=None):
        self.config = config
        self.root = Path(config['state_root'])
        self.root.mkdir(parents=True, exist_ok=True)
        self.renderer = renderer or self.render
        self.probe = probe
        # LAN只替换通信/传输，不复制或改写已验证的剪映导出流程。
        self.transport = transport
        self.jobs_root = Path(config.get('local_jobs_root', self.root / 'jobs'))

    def request(self, route, value=None):
        if self.transport:
            return self.transport.request(route, value)
        return request(self.config['server_url'], route, value)

    def render(self, job, job_path):
        import os
        from media_execution.progress import progress,run_render_child
        # Windows venv启动器还有一层Python包装进程，不能拿子进程ppid冒充常驻Worker。
        job['resident_pid']=os.getpid();save(job_path,job)
        progress(job,'DRAFT_LAUNCHING','launching',restart=True)
        with (job_path.parent / 'render.log').open('ab') as log:
            run_render_child([sys.executable, '-X', 'utf8', '-B', '-m', 'startup_render.agent',
                '--config', self.config['_config_path'], '--render-job', str(job_path)],job,job_path,log,
                total_timeout=self.config.get('render_timeout',1800)+240)

    def post_receipt(self, state_path, state):
        with self.request('/receipt/' + state['manifest']['job_id'], state['receipt']) as result:
            if not json.load(result).get('saved'):
                raise RuntimeError('RECEIPT_NOT_SAVED')
        state['receipt_sent'] = True
        save(state_path, state)

    def tick(self):
        # 重启只重传已保存回执，不重做已开始的桌面操作。
        from .render_health import failure_scope
        self.job_attention_count = 0
        for path in sorted(self.jobs_root.glob('*/state.json')):
            state = read(path)
            if not state.get('receipt'):
                state['receipt'] = {'claim': state['claim'], 'status': 'NEEDS_MANUAL',
                                    'error': 'INTERRUPTED_NO_AUTO_RETRY'}
                save(path, state)
            if not state.get('receipt_sent'):
                self.post_receipt(path, state)
            if state['receipt']['status'] in {'NEEDS_MANUAL', 'VERSION_DRIFT', 'FAILED_MISSING_SOURCE'}:
                if failure_scope(state['receipt']) == 'WORKER_BROKEN':
                    return 'HALTED_NEEDS_MANUAL'
                self.job_attention_count += 1
                continue  # 单草稿失败保持原回执，不重试、不阻止其它健康任务。
            if self.config.get('stop_after_one') and state['receipt']['status'] == 'COMPLETED':
                return 'COMPLETED'
        with self.request('/claim', {}) as result:
            state = json.load(result)
        if state is None:
            return 'WAITING_NEW_DRAFT'
        return self.execute_claim(state)

    def execute_claim(self, state, *, resume_original=False):
        """执行Server已领取的原RenderJob；供统一媒体通道复用导出实现。"""
        from .render_health import failure_scope
        self.job_attention_count = getattr(self,'job_attention_count',0)
        manifest = state['manifest']
        job_id = identifier(manifest['job_id'])
        state_path = below(self.jobs_root, job_id + '/state.json')
        if state_path.exists():
            raise RuntimeError('DUPLICATE_CLAIM')
        save(state_path, state)
        event(state_path.parent, 'PENDING', issued_at=manifest.get('pending_at'))
        try:
            if manifest['business_type'] != 'STARTUP' or manifest['content_id'] != job_id:
                raise ValueError('IDENTITY_MISMATCH')
            folder = state_path.parent / 'package'
            event(state_path.parent, 'STAGING_FILES')
            if self.transport:
                self.transport.download(manifest, folder)
            else:
                download(self.config, manifest, folder)
            # 全部原始文件到齐并通过哈希后才允许启动剪映。
            for entry in manifest['files']:
                source = below(folder, entry['relative'])
                if not source.is_file() or digest(source) != entry['sha256']:
                    raise ValueError('FAILED_MISSING_SOURCE')
            event(state_path.parent, 'STAGING_COMPLETE', all_files_verified=True)
            installed=state_path.parent/'installed_draft.json'
            if resume_original and installed.is_file():
                from .draft_install import install_check
                proof=read(installed)
                if proof.get('content_id')!=job_id or proof.get('business_draft_name')!=manifest['draft_name']:
                    raise PermissionError('RECOVERY_INSTALLED_IDENTITY_MISMATCH')
                draft=Path(proof['draft_path'])
                install_check(self.config,draft,manifest['draft_name'])
                event(state_path.parent,'RESUMED_ORIGINAL_INSTALLED_DRAFT',draft_path=str(draft))
            else:
                draft = install_draft(self.config, manifest, folder)
            event(state_path.parent, 'DRAFT_READY', material_count=manifest.get('material_count'), all_files_verified=True)
            index = manifest['video_index']
            if type(index) is not int or not 1 <= index <= 10000:
                raise ValueError('INVALID_VIDEO_INDEX')
            from .common import output_relative
            output = (self.transport.output_path(manifest) if self.transport else
                      below(self.config['export_root'], output_relative(manifest)))
            if output.exists():
                raise FileExistsError('EXPORT_ALREADY_EXISTS_NO_OVERWRITE')
            output.parent.mkdir(parents=True, exist_ok=True)
            job = {'manifest': manifest, 'draft': str(draft), 'output': str(output), 'evidence_root': str(state_path.parent)}
            job_path = state_path.parent / 'render_job.json'
            save(job_path, job)
            self.renderer(job, job_path)
            from .media_compat import normalize_export
            normalize_export(self.config,output,state_path.parent)
            event(state_path.parent, 'VALIDATING')
            media = self.probe(self.config['ffprobe'], output, float(manifest['duration_us']) / 1000000)
            if manifest.get('requires_audio') and not media.get('audio_codec'):
                raise ValueError('REQUIRED_AUDIO_STREAM_MISSING')
            if (media['width'], media['height']) != (manifest['canvas']['width'], manifest['canvas']['height']):
                raise ValueError('RESOLUTION_MISMATCH')
            numerator, denominator = media['fps'].split('/')
            if abs(float(numerator) / float(denominator) - float(manifest['fps'])) > .02:
                raise ValueError('FPS_MISMATCH')
            state['receipt'] = {'claim': state['claim'], 'status': 'EXPORTED_AWAITING_PUBLISH_PARAMETERS',
                                'content_id': job_id, 'batch_id': manifest['batch_id'], 'video_index': index,
                                'employee_id': manifest['employee_id'], 'business_type': 'STARTUP',
                                'composition_signature': manifest['composition_signature'],
                                'video_path': str(output), 'media': media, 'real_publish_attempts': 0}
            for key in ('target_account_id', 'target_account_name_snapshot'):
                if key in manifest:
                    state['receipt'][key] = manifest[key]
            event(state_path.parent, 'VALIDATED')
            if manifest.get('return_mp4'):
                uploaded = (self.transport.upload(state, output, media) if self.transport else
                            upload_result(self.config, state, output, media))
                history = read(state_path.parent / 'events.json')
                exported = next(e for e in history if e['status'] == 'EXPORTED')
                event(state_path.parent, 'COMPLETED')
                state['receipt'].update(status='COMPLETED', export_status='VALIDATED',
                    worker_id=self.config['worker_id'], render_job_id=job_id, draft_name=manifest['draft_name'],
                    export_duration=exported['export_duration'], completed_at=datetime.now(timezone.utc).isoformat(),
                    events=read(state_path.parent / 'events.json'), material_count=manifest['material_count'],
                    source_to_worker=read(state_path.parent / 'source_to_worker.json'), **uploaded)
        except Exception as error:
            logging.exception('export failed %s', job_id)
            history = read(state_path.parent / 'events.json')
            child_error = state_path.parent / 'render_error.json'
            detail = read(child_error)['error'] if child_error.exists() else type(error).__name__ + ':' + str(error)
            failed = ('VERSION_DRIFT' if any(e['status'] == 'VERSION_DRIFT' for e in history) else
                      'FAILED_MISSING_SOURCE' if 'MISSING' in str(error) or isinstance(error, FileNotFoundError) else 'NEEDS_MANUAL')
            event(state_path.parent, failed)
            state['receipt'] = {'claim': state['claim'], 'status': failed, 'render_job_id': job_id,
                                'failed_step': read(child_error).get('failed_step', history[-1]['status']) if child_error.exists() else history[-1]['status'],
                                'events': read(state_path.parent / 'events.json'),
                                'error': detail, 'real_publish_attempts': 0}
        save(state_path, state)
        self.post_receipt(state_path, state)
        if state['receipt']['status'] in {'NEEDS_MANUAL','FAILED_MISSING_SOURCE','VERSION_DRIFT'}:
            if failure_scope(state['receipt']) == 'JOB_HALTED':
                self.job_attention_count += 1
                return 'JOB_HALTED'
        return state['receipt']['status']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--render-job')
    args = parser.parse_args()
    config = read(args.config)
    config['_config_path'] = str(Path(args.config).resolve())
    if args.render_job:
        job = read(args.render_job)
        try:
            render_child(config, job)
        except Exception as error:
            history_path = Path(job['evidence_root']) / 'events.json'
            history = read(history_path) if history_path.exists() else []
            failed_step = history[-1]['status'] if history else 'VERIFY_DRAFT_NAME'
            event(job['evidence_root'], 'RENDER_FAILED', error=str(error))
            save(Path(job['evidence_root']) / 'render_error.json', {'error': type(error).__name__ + ':' + str(error),
                 'failed_step': failed_step})
            raise
        return
    agent = Agent(config)
    logging.basicConfig(filename=str(agent.root / 'agent.log'), level=logging.INFO)
    with mutex('Local\\XunZhenStartupRenderAgentV01'):
        while True:
            try:
                status = agent.tick()
            except Exception as error:
                logging.exception('agent tick failed')
                status = 'CONNECTION_OR_STATE_ERROR:' + type(error).__name__
            value = {'status': status, 'checked_at': datetime.now(timezone.utc).isoformat(),
                     'real_publish_enabled': False}
            save(agent.root / 'health.json', value)
            if args.once or config.get('stop_after_one') and status in {'COMPLETED', 'NEEDS_MANUAL', 'VERSION_DRIFT', 'FAILED_MISSING_SOURCE', 'HALTED_NEEDS_MANUAL'}:
                print(json.dumps(value)); return
            time.sleep(config.get('poll_seconds', 10))


if __name__ == '__main__':
    main()
