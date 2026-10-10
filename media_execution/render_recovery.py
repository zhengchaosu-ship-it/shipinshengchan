"""恢复前仅正常关闭上次本Worker启动且仍停在首页的剪映。"""
import ctypes
from datetime import datetime,timezone
from pathlib import Path

from startup_render.common import read,digest
from startup_render.agent import event
from startup_render.draft_lifecycle import visible_names,wait_for


def close_owned_home(config, folder, *, pre_export_recovery=None):
    import psutil
    from startup_render.isolated_controller import IsolatedController
    folder=Path(folder)
    job=read(folder/'render_job.json')
    if job['manifest']['job_id']!=folder.name:raise PermissionError('RECOVERY_JOB_IDENTITY_REQUIRED')
    launches=[e for e in read(folder/'events.json') if e['status']=='JIANYING_LAUNCH_SOURCE']
    if not launches:raise PermissionError('OWNED_LAUNCH_EVIDENCE_REQUIRED')
    known={r['pid']:r['started_at'] for r in launches[-1]['processes']}
    engine=Path(config['jianying_exe']).resolve()
    if digest(engine)!=config['jianying_sha256'].lower():raise PermissionError('VERSION_DRIFT')
    processes=[p for p in psutil.process_iter(['name','exe','create_time','ppid']) if (p.info['name'] or '').lower()=='jianyingpro.exe']
    active={p.pid:datetime.fromtimestamp(p.info['create_time'],timezone.utc).isoformat() for p in processes}
    if any(Path(p.info['exe'] or '').resolve()!=engine for p in processes):raise PermissionError('OTHER_JIANYING_VERSION_RUNNING')
    owned={pid:stamp for pid,stamp in known.items() if active.get(pid)==stamp}
    # VEDetector会结束最初启动的主进程，在“检测成功/确定”后重新拉起剪映。
    # 只接纳同Job的成功处理前后快照中，已验证检测器的直接新子进程。
    from startup_render.export_state import known_modal
    for after_path in (folder/'export_evidence').glob('*-known-modal-after.json'):
        sequence=int(after_path.name.split('-',1)[0])
        before_path=after_path.with_name(str(sequence-1)+'-known-modal-before.json')
        if not before_path.is_file():continue
        before,after=read(before_path),read(after_path)
        if not known_modal(before):continue
        checked=datetime.fromisoformat(after['at']).timestamp()
        started=datetime.fromisoformat(launches[-1]['started_at']).timestamp()
        for detector in before['processes']:
            if (detector['name'].lower()!='vedetector.exe' or Path(detector['exe']).resolve().parent!=engine.parent
                    or not started<=detector['create_time']<=started+30):continue
            for p in processes:
                if p.info['ppid']==detector['pid'] and detector['create_time']<=p.info['create_time']<=checked+10:
                    owned[p.pid]=active[p.pid]
    for _ in processes:
        for p in processes:
            if p.info['ppid'] in owned:owned[p.pid]=active[p.pid]
    if set(active)!=set(owned):raise PermissionError('UNOWNED_JIANYING_NO_CLOSE')
    if pre_export_recovery:
        from .workstation_health import read_optional,owner_path
        owner=read_optional(owner_path(config))
        if (pre_export_recovery.get('job_id')!=folder.name or owner.get('render_job_id')!=folder.name
                or owner.get('launch_token')!=pre_export_recovery.get('launch_token')):
            raise PermissionError('PRE_EXPORT_RECOVERY_OWNERSHIP_REQUIRED')
        if list(folder.glob('export_submit_once*.json')) or Path(job['output']).exists():
            raise PermissionError('EXPORT_MAY_HAVE_STARTED_RECONCILE_FIRST')
        if (Path(job['draft'])/'draft_content.json').stat().st_mtime_ns!=pre_export_recovery.get('draft_mtime_ns'):
            raise PermissionError('DRAFT_CHANGED_NO_CLOSE')
        from startup_render.export_ui import JianyingExportUi
        ui=JianyingExportUi(config,job)
        snapshot=ui.capture('pre-export-recovery-readonly',persist=False)
        if snapshot['detection']['state'] not in ('EDITING','EXPORT_BUTTON_AVAILABLE'):
            raise PermissionError('ACTIVE_EXPORT_OR_UNKNOWN_WINDOW_NO_CLOSE')
        main=[w for w in snapshot['windows'] if w['title']=='剪映专业版' and w['parent_hwnd'] is None]
        if len(main)!=1 or main[0]['pid'] not in owned:raise PermissionError('OWNED_EDITOR_REQUIRED')
        # 正常关闭编辑窗口返回首页；遇到保存/未知弹窗即停，不点击确认、不强杀。
        user=ctypes.WinDLL('user32',use_last_error=True)
        user.PostMessageW.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t]
        user.PostMessageW.restype=ctypes.c_bool
        event(folder,'RECOVERY_OWNED_EDITOR_NORMAL_CLOSE',job_id=folder.name)
        if not user.PostMessageW(int(main[0]['hwnd'],16),0x0010,0,0):raise RuntimeError('NORMAL_CLOSE_FAILED')
        def home():
            if not any(p.pid in owned for p in psutil.process_iter()):return True
            current=ui.capture('recovery-await-home',persist=False)
            # WM_CLOSE后Qt可能短暂同时显示旧编辑窗口和新首页；只等待，不点击弹窗。
            # 稳定首页仍由后续visible_names再次验证；未知窗口持续存在则有界失败。
            return current['detection']['state']!='UNKNOWN_MODAL' and any(
                t['nodes'] and t['nodes'][0]['class'].startswith('HomePage_') for t in current['trees'])
        if not wait_for(home,20):raise RuntimeError('EDITOR_DID_NOT_RETURN_HOME')
        if not any(p.pid in owned for p in psutil.process_iter()):
            event(folder,'RECOVERY_OWNED_HOME_EXITED')
            return
    controller=IsolatedController(config,job)
    visible_names(controller)  # 首页及无弹窗；编辑/导出/未知窗口均拒绝关闭。
    if controller.app.ProcessId not in owned:raise PermissionError('UNOWNED_JIANYING_WINDOW')
    user=ctypes.WinDLL('user32',use_last_error=True)
    user.PostMessageW.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t]
    user.PostMessageW.restype=ctypes.c_bool
    event(folder,'RECOVERY_OWNED_HOME_CLOSE_REQUESTED',process_ids=list(owned))
    if not user.PostMessageW(controller.app.NativeWindowHandle,0x0010,0,0):raise RuntimeError('JIANYING_NORMAL_CLOSE_FAILED')
    if not wait_for(lambda:not any(p.pid in owned for p in psutil.process_iter()),30):raise RuntimeError('JIANYING_CLOSE_TIMEOUT')
    event(folder,'RECOVERY_OWNED_HOME_EXITED')
