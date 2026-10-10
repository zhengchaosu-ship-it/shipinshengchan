"""渲染阶段进度与停滞看门狗；心跳不等于进度，不重放任何导出输入。"""
import json
import os
from pathlib import Path
import subprocess
import time

from .coordinator import atomic_json

TIMEOUTS={'JIANYING_START':120,'DRAFT_OPENING':90,'DRAFT_OPENED':45,'DRAFT_OPEN':90,'EXPORT_TRIGGER':45,
          'EXPORT_CONFIGURE':90,'EXPORTING':300,'OUTPUT_VERIFYING':600,'OUTPUT_VERIFY':600}
LABELS={'JIANYING_START':'启动剪映','DRAFT_OPENING':'打开草稿','DRAFT_OPENED':'等待导出',
        'DRAFT_OPEN':'打开草稿','EXPORT_TRIGGER':'触发导出','EXPORT_CONFIGURE':'配置导出',
        'EXPORTING':'导出中','OUTPUT_VERIFYING':'校验中','OUTPUT_VERIFY':'校验中','COMPLETE':'完成'}
TIMEOUTS.update(DRAFT_LAUNCHING=120,DRAFT_WINDOW_FOUND=90,DRAFT_LOADING=120,DRAFT_READY=45,
                EXPORT_TRIGGER_PENDING=45,EXPORT_TRIGGERED=30,OUTPUT_DETECTED=90,VERIFYING=600,COMPLETED=600)
LABELS.update(DRAFT_LAUNCHING='启动草稿窗口',DRAFT_WINDOW_FOUND='已找到草稿列表',DRAFT_LOADING='等待编辑器稳定',
              DRAFT_READY='草稿已就绪',EXPORT_TRIGGER_PENDING='等待导出入口',EXPORT_TRIGGERED='已提交导出',
              OUTPUT_DETECTED='已检测成片',VERIFYING='校验中',COMPLETED='完成')


class JobStalled(RuntimeError):
    pass


def reserve_recovery(folder, job_id):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    try:
        with (folder/'render_recovery_once.json').open('x',encoding='utf-8') as stream:
            json.dump({'job_id':job_id,'recovery_count':1,'reserved_at':time.time()},stream)
            stream.flush();os.fsync(stream.fileno())
    except FileExistsError:
        raise JobStalled('JOB_STALLED:RECOVERY_ALREADY_ATTEMPTED_NO_RETRY')


def remaining_stage_seconds(folder, default):
    value=evaluate(read_progress(folder))
    if not value or value['stage'] not in ('OUTPUT_VERIFY','OUTPUT_VERIFYING'):return default
    if value['state']=='JOB_STALLED':raise JobStalled('JOB_STALLED:OUTPUT_VERIFYING')
    return min(default,max(.1,value['stage_max_seconds']-value['elapsed_seconds']))


def read_progress(folder):
    try:return json.loads((Path(folder)/'render_progress.json').read_text('utf-8'))
    except FileNotFoundError:return None


def evaluate(progress, *, now=None):
    if not progress:return None
    result=dict(progress);now=time.time() if now is None else now
    result['elapsed_seconds']=max(0,now-progress['stage_started_at'])
    result['seconds_without_progress']=max(0,now-progress['last_progress_at'])
    stalled=(progress.get('state')=='JOB_STALLED' or progress['stage']!='COMPLETE' and
        (result['seconds_without_progress']>progress['stage_timeout'] or
         result['elapsed_seconds']>progress.get('stage_max_seconds',progress['stage_timeout'])))
    result['state']='JOB_STALLED' if stalled else progress.get('state','RUNNING')
    result['stage_label']=LABELS.get(progress['stage'],progress['stage'])
    return result


def progress(job, stage, marker=None, *, timeout=None, max_seconds=None, now=None, restart=False):
    now=time.time() if now is None else now;folder=Path(job['evidence_root'])
    old=read_progress(folder)
    if restart or not old or old['job_id']!=job['manifest']['job_id']:old={}
    if evaluate(old or None,now=now) and evaluate(old,now=now)['state']=='JOB_STALLED':
        raise JobStalled('JOB_STALLED:'+old['stage'])
    changed=old.get('stage')!=stage
    value=dict(old,job_id=job['manifest']['job_id'],draft_name=job['manifest']['draft_name'],
        recovery_count=int((json.loads((folder/'render_recovery_once.json').read_text('utf-8'))
            if (folder/'render_recovery_once.json').exists() else {}).get('recovery_count',0)),
        stage=stage,stage_started_at=now if changed else old['stage_started_at'],
        last_progress_at=now if changed or marker!=old.get('marker') else old['last_progress_at'],
        marker=marker,stage_timeout=timeout or (TIMEOUTS.get(stage,600) if changed else old['stage_timeout']),
        stage_max_seconds=max_seconds or timeout or (TIMEOUTS.get(stage,600) if changed else old['stage_max_seconds']),
        state='COMPLETE' if stage=='COMPLETE' else 'RUNNING',last_observed_at=now)
    draft=Path(job['draft'])/'draft_content.json'
    if draft.exists():value['observed_draft_mtime_ns']=draft.stat().st_mtime_ns
    atomic_json(folder/'render_progress.json',value)
    return value


def assert_progress(folder):
    value=evaluate(read_progress(folder))
    if value and value['state']=='JOB_STALLED':raise JobStalled('JOB_STALLED:'+value['stage'])


def mark_stalled(folder, reason):
    value=read_progress(folder)
    if value:
        value.update(state='JOB_STALLED',error=reason,detected_at=time.time())
        # 记录失败当时的版本，而不是打开前的mtime（剪映加载会补写默认字段）。
        job_path=Path(folder)/'render_job.json'
        if job_path.exists():
            job=json.loads(job_path.read_text('utf-8'));draft=Path(job['draft'])/'draft_content.json'
            if draft.exists():value['observed_draft_mtime_ns']=draft.stat().st_mtime_ns
        atomic_json(Path(folder)/'render_progress.json',value)


def stop_python_helpers(process, job_path):
    """只收割本次启动的Python自动化进程；绝不终止剪映或原生导出。"""
    import psutil
    try:root=psutil.Process(process.pid);children=root.children(recursive=True)
    except psutil.NoSuchProcess:return
    targets=[]
    for item in children+[root]:
        try:
            args=item.cmdline()
            if (item.name().lower() not in ('python.exe','pythonw.exe') or '--render-job' not in args):continue
            index=args.index('--render-job')
            if index+1>=len(args) or Path(args[index+1]).resolve()!=Path(job_path).resolve():continue
            item.terminate();targets.append(item)
        except psutil.NoSuchProcess:pass
    _,alive=psutil.wait_procs(targets,timeout=5)
    if alive:raise JobStalled('JOB_STALLED:AUTOMATION_HELPER_STILL_ALIVE')


def run_render_child(command, job, job_path, log, *, total_timeout):
    deadline=time.monotonic()+total_timeout
    # 维护入口和计划任务都从确定的代码根启动模块，不继承调用终端的工作目录。
    child=subprocess.Popen(command,cwd=str(Path(__file__).resolve().parents[1]),stdout=log,stderr=log,
                           creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    while child.poll() is None:
        value=evaluate(read_progress(job['evidence_root']))
        if value and value['state']=='JOB_STALLED' or time.monotonic()>deadline:
            detail=dict(value or {},state='JOB_STALLED',detected_at=time.time(),job_id=job['manifest']['job_id'])
            atomic_json(Path(job['evidence_root'])/'stall.json',detail)
            stop_python_helpers(child,job_path)
            raise JobStalled('JOB_STALLED:'+str(detail.get('stage','RENDER_PROCESS_TIMEOUT')))
        time.sleep(.5)
    if child.returncode:raise subprocess.CalledProcessError(child.returncode,command)


def current_progress(config, job_id):
    if not job_id:return None
    root=Path(config['local_jobs_root']).resolve();folder=(root/job_id).resolve()
    if folder.parent!=root:return None
    value=read_progress(folder)
    if value:return evaluate(value)
    # 升级前的任务也提供真实失败阶段；旧EXPORTING事件并不能证明已点击导出。
    failure=folder/'render_error.json';job_file=folder/'render_job.json'
    if failure.exists() and job_file.exists():
        job=json.loads(job_file.read_text('utf-8'));error=json.loads(failure.read_text('utf-8'))
        stamp=failure.stat().st_mtime
        stage='DRAFT_OPENED' if not (folder/'export_submit_once.json').exists() else 'EXPORTING'
        return evaluate({'job_id':job_id,'draft_name':job['manifest']['draft_name'],'stage':stage,
            'stage_started_at':stamp,'last_progress_at':stamp,'stage_timeout':TIMEOUTS[stage],
            'state':'JOB_STALLED','error':error['error']})
    return None
