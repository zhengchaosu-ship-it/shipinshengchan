"""剪映占用与故障分开判断；健康采样只读，不关闭、激活或操作窗口。"""
from datetime import datetime
import json
import ntpath
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from .coordinator import atomic_json


LABELS = {
    'JIANYING_NOT_RUNNING':'空闲', 'JIANYING_IDLE_WORKER_OWNED':'空闲',
    'JIANYING_RENDERING':'正在渲染', 'JIANYING_EXPORTING':'正在导出',
    'JIANYING_VERIFYING':'正在校验成片', 'JIANYING_MANUAL_USE':'人工使用中，自动任务等待',
    'JIANYING_ORPHAN_IDLE':'空闲', 'JIANYING_UNKNOWN_BLOCKED':'需要处理',
}


def owner_path(config):
    return Path(config['state_root'])/'media_execution/jianying_owner.json'


def read_optional(path, default=None):
    try:
        return json.loads(Path(path).read_text('utf-8-sig'))
    except FileNotFoundError:
        return {} if default is None else default


def record_launch(config, job, processes, *, launch_token=None, launch_time=None):
    """已验证专用启动器成功后持久记录；PID必须同时匹配创建时间。"""
    import psutil
    main=min(processes,key=lambda row:row['started_at'])
    worker_pid=job.get('resident_pid',config.get('_resident_pid',os.getppid()))
    meta=read_optional(Path(job['draft'])/'draft_meta_info.json')
    value={'worker_id':config['worker_id'],'jianying_pid':main['pid'],
        'launch_token':launch_token or uuid.uuid4().hex,'launch_time':launch_time or time.time(),
        'render_job_id':job['manifest']['job_id'],
        'draft_id':meta.get('draft_id') or job['manifest']['draft_name'],
        'draft_name':job['manifest']['draft_name'],'draft_path':job['draft'],
        'worker_pid':worker_pid,'worker_started_at':psutil.Process(worker_pid).create_time(),
        'processes':processes,'jianying_exe':config['jianying_exe']}
    atomic_json(owner_path(config),value)
    return value


def owned_pids(processes, owner, worker_id):
    if not owner.get('launch_token') or owner.get('worker_id')!=worker_id:
        return set()
    known={p['pid']:datetime.fromisoformat(p['started_at']).timestamp() for p in owner.get('processes',[])}
    owned={p['pid'] for p in processes if p['pid'] in known and abs(p['create_time']-known[p['pid']])<.01}
    # 只接纳仍存活且已验证父进程的子进程；不能通过可复用的PID单独继承归属。
    for _ in processes:
        for p in processes:
            if p.get('ppid') in owned and p['create_time']>=next(x['create_time'] for x in processes if x['pid']==p['ppid']):
                owned.add(p['pid'])
    return owned


def current_launch_pids(processes, owner, *, worker_id, job_id, launch_token):
    """收尾只能延续本次launch的已验证归属，不能接管另一Job/另一次启动。"""
    if (not launch_token or owner.get('worker_id')!=worker_id or owner.get('render_job_id')!=job_id
            or owner.get('launch_token')!=launch_token):
        raise PermissionError('LAUNCH_OWNERSHIP_CHANGED_NO_CLOSE')
    return owned_pids(processes,owner,worker_id)


def adopt_environment_relaunch(config,job):
    """5.9环境检测成功后会换主PID；仅凭已核验输入前后证据延续同一launch token。"""
    import psutil
    from startup_render.export_state import known_modal
    owner=read_optional(owner_path(config))
    if owner.get('render_job_id')!=job['manifest']['job_id']:return False
    engine=Path(config['jianying_exe']).resolve()
    live=[p.info for p in psutil.process_iter(['pid','name','exe','create_time','ppid'])
          if (p.info['name'] or '').lower()=='jianyingpro.exe']
    adopted=[]
    for after_path in (Path(job['evidence_root'])/'export_evidence').glob('*-known-modal-after.json'):
        sequence=int(after_path.name.split('-',1)[0])
        before_path=after_path.with_name(str(sequence-1)+'-known-modal-before.json')
        if not before_path.exists():continue
        before,after=read_optional(before_path),read_optional(after_path)
        if not known_modal(before):continue
        checked=datetime.fromisoformat(after['at']).timestamp()
        for detector in before['processes']:
            if (detector['name'].lower()!='vedetector.exe' or Path(detector['exe']).resolve().parent!=engine.parent
                or not owner['launch_time']<=detector['create_time']<=owner['launch_time']+30):continue
            for p in live:
                if (p['ppid']==detector['pid'] and Path(p['exe'] or '').resolve()==engine
                    and detector['create_time']<=p['create_time']<=checked+15):
                    entry={'pid':p['pid'],'started_at':datetime.fromtimestamp(p['create_time']).astimezone().isoformat(),'path':p['exe']}
                    if not any(r['pid']==entry['pid'] and abs(datetime.fromisoformat(r['started_at']).timestamp()-p['create_time'])<.01
                               for r in owner['processes']):adopted.append(entry)
    if not adopted:return False
    owner['processes'].extend(adopted);owner['jianying_pid']=min(adopted,key=lambda p:p['started_at'])['pid']
    owner['environment_relaunch_verified_at']=time.time()
    atomic_json(owner_path(config),owner)
    return True


def classify(evidence):
    processes=evidence.get('processes',[])
    active=evidence.get('active_lease')
    ui=evidence.get('ui',{}).get('state','NOT_RUNNING')
    owned=bool(processes) and all(p.get('worker_owned') for p in processes)
    executing=evidence.get('executing',False)
    reason=evidence.get('error')
    state='JIANYING_NOT_RUNNING';status='READY'
    if reason or ui in ('UNKNOWN_MODAL','UNRESPONSIVE','VERSION_DRIFT','EXPORT_STUCK') or (owned and active and ui=='WRONG_DRAFT'):
        state='JIANYING_UNKNOWN_BLOCKED';status='NEEDS_ATTENTION';reason=reason or ui
    elif processes and not owned:
        if active:
            state='JIANYING_UNKNOWN_BLOCKED';status='NEEDS_ATTENTION';reason='UNOWNED_PROCESS_WITH_EXECUTION_LEASE'
        else:
            state='JIANYING_MANUAL_USE';status='WAITING_FOR_WORKSTATION'
    elif active and (executing or processes or evidence.get('other_executors')):
        journal=evidence.get('journal',{})
        matching=all(journal.get(k)==active.get(k) for k in ('worker_id','job_id','job_type'))
        if not matching or active.get('expires_at',0)<=evidence['checked_at']:
            state='JIANYING_UNKNOWN_BLOCKED';status='NEEDS_ATTENTION';reason='EXECUTION_LEASE_OR_JOURNAL_UNCERTAIN'
        elif processes and evidence.get('owner',{}).get('render_job_id')!=active.get('job_id'):
            state='JIANYING_UNKNOWN_BLOCKED';status='NEEDS_ATTENTION';reason='OWNED_DRAFT_JOB_MISMATCH'
        else:
            stage=journal.get('stage',active.get('stage'))
            state=('JIANYING_VERIFYING' if stage=='OUTPUT_VERIFYING' else
                'JIANYING_EXPORTING' if ui in ('EXPORTING','EXPORT_DIALOG','EXPORT_COMPLETE') else
                'JIANYING_RENDERING' if active['job_type']=='RENDER' else 'JIANYING_NOT_RUNNING')
            status='BUSY'
    elif evidence.get('other_executors'):
        state='JIANYING_UNKNOWN_BLOCKED';status='NEEDS_ATTENTION';reason='UNATTRIBUTED_HEAVY_EXECUTOR'
    elif processes:
        if ui=='HOME':
            state='JIANYING_IDLE_WORKER_OWNED' if evidence.get('owner_alive') else 'JIANYING_ORPHAN_IDLE'
        elif ui in ('EDITING','EXPORT_BUTTON_AVAILABLE','EXPORTING','EXPORT_DIALOG','EXPORT_COMPLETE','DRAFT_LOADING','WRONG_DRAFT'):
            # 即使最初由Worker启动，无租约时有人继续编辑也不能抢回窗口。
            state='JIANYING_MANUAL_USE';status='WAITING_FOR_WORKSTATION'
        else:
            state='JIANYING_UNKNOWN_BLOCKED';status='NEEDS_ATTENTION';reason='OWNED_UI_STATE_UNCERTAIN'
    elif executing:
        status='BUSY'
    label='正在发布' if status=='BUSY' and active and active.get('job_type')=='PUBLISH' else '正在执行' if status=='BUSY' and state=='JIANYING_NOT_RUNNING' else LABELS[state]
    if status=='BUSY' and active and active.get('stage')=='PUBLISH_RECONCILING':label='正在核对发布状态'
    return {'jianying_state':state,'status':status,'label':label,'reason':reason,
        'can_claim':status=='READY','evidence':evidence}


def ui_snapshot(config, draft_name):
    """复用正式导出UI读取器，不截图、不保存、无点击；在有界子进程中运行。"""
    from startup_render.export_ui import JianyingExportUi
    job={'manifest':{'draft_name':draft_name},'evidence_root':config['state_root']}
    snapshot=JianyingExportUi(config,job).capture('health-readonly',persist=False)
    detection=snapshot['detection']
    # 首页没有导出控件；使用剪映5.9真实首页特征，不用进程名推断空闲。
    nodes=[n for tree in snapshot['trees'] for n in tree['nodes'] if not n.get('offscreen')]
    home=any(n.get('description','').startswith('HomePage') or n.get('automation_id','').startswith('HomePage')
        or 'homepage' in n.get('class','').lower() for n in nodes)
    state='HOME' if home and detection['state']=='UNKNOWN' else detection['state']
    import ctypes
    user=ctypes.WinDLL('user32');user.IsHungAppWindow.argtypes=[ctypes.c_void_p]
    if any(user.IsHungAppWindow(int(w['hwnd'],16)) for w in snapshot['windows']):state='UNRESPONSIVE'
    output_names={ntpath.basename(n.get('description',''))[:-4] for n in nodes
        if ntpath.isabs(n.get('description','')) and n.get('description','').lower().endswith('.mp4')}
    return {'state':state,'reason':detection['reason'],'windows':snapshot['windows'],
        'active_draft':next(iter(output_names)) if len(output_names)==1 else None,
        'expected_draft':draft_name or None,'draft_evidence':'export_path' if len(output_names)==1 else 'not_observable'}


def observe(config, *, snapshot=None, executing=False):
    import psutil
    now=time.time()
    evidence={'checked_at':now,'active_lease':(snapshot or {}).get('active'),
        'executing':executing,'processes':[],'other_executors':[]}
    try:
        evidence['journal']={k:v for k,v in read_optional(Path(config['state_root'])/'media_execution/journal.json').items()
            if k in ('worker_id','job_type','job_id','stage','updated_at')}
        evidence['previous_heartbeat_at']=read_optional(Path(config['state_root'])/'media_execution/health.json').get('checked_at')
        owner=read_optional(owner_path(config));evidence['owner']=owner
        try:
            evidence['owner_alive']=abs(psutil.Process(owner.get('worker_pid',0)).create_time()-owner.get('worker_started_at',-1))<.01
        except (psutil.Error,ValueError):
            evidence['owner_alive']=False
        engine=Path(config['jianying_exe']).resolve()
        for p in psutil.process_iter(['pid','name','exe','create_time','ppid','cmdline','username']):
            info=p.info;name=(info['name'] or '').lower()
            if name in ('jianyingpro.exe','vedetector.exe'):
                evidence['processes'].append({k:info[k] for k in ('pid','name','exe','create_time','ppid','username')})
                if not info['exe'] or Path(info['exe']).resolve().parent!=engine.parent:
                    evidence['error']='VERSION_DRIFT'
            elif p.pid!=os.getpid() and (name in ('ffmpeg.exe','yxer.exe') or '--render-job' in (info['cmdline'] or [])):
                evidence['other_executors'].append({'pid':p.pid,'name':name,'create_time':info['create_time']})
        owned=owned_pids(evidence['processes'],owner,config['worker_id'])
        for p in evidence['processes']:p['worker_owned']=p['pid'] in owned
        if evidence['processes'] and not evidence.get('error'):
            command=[sys.executable,'-X','utf8','-B','-m','media_execution.workstation_health',
                '--ui',config['_config_path'],'--draft',owner.get('draft_name','') if owned else '']
            probe=subprocess.run(command,capture_output=True,timeout=12,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if probe.returncode:raise RuntimeError('UI_OBSERVATION_FAILED')
            evidence['ui']=json.loads(probe.stdout)
            # 导出超时必须有同一任务的真实导出闩锁，不能因进程运行较久误报。
            if evidence['ui']['state']=='EXPORTING' and owned and evidence['active_lease']:
                root=Path(config['local_jobs_root']).resolve();folder=(root/owner['render_job_id']).resolve()
                if folder.parent!=root:raise ValueError('UNSAFE_OWNER_JOB_PATH')
                latch=read_optional(folder/'export_submit_once.json')
                if latch.get('at') and now-datetime.fromisoformat(latch['at']).timestamp()>config.get('render_timeout',1800)+240:
                    evidence['ui']['state']='EXPORT_STUCK'
    except (OSError,ValueError,KeyError,RuntimeError,psutil.Error,subprocess.TimeoutExpired) as error:
        evidence['error']=type(error).__name__+':'+str(error)
    result=classify(evidence)
    from .progress import current_progress
    active=evidence.get('active_lease')
    job_id=active.get('job_id') if active and active.get('job_type')=='RENDER' else None
    if job_id:
        current=current_progress(config,job_id)
        result['progress']=current
        if current and current['state']=='JOB_STALLED':
            result.update(jianying_state='JIANYING_UNKNOWN_BLOCKED',status='NEEDS_ATTENTION',
                label='任务停滞，需要处理',reason='JOB_STALLED:'+current['stage'],can_claim=False)
    return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--ui',required=True);parser.add_argument('--draft',default='')
    args=parser.parse_args()
    print(json.dumps(ui_snapshot(read_optional(args.ui),args.draft),ensure_ascii=True))
