"""用户主动运行的Job3唯一入口。Codex准备时只允许--preflight-only，不调用本机UI。"""
import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import os
import subprocess
import time

from xiaovcat_publish_worker import ROOT, PublishWorker, load_config, safe_code, single_instance
from .desktop_worker.resident_monitor import instance_lock, write_json
from .local_worker_queue import LocalWorkerQueue

PLAN_ID='52e11ba8-fe9b-47f4-ae1f-74ed593712a9'
JOB_ID='af6c16d3-2912-4390-88c7-4584b3e4feea'
CONTENT_ID='STARTUP-a16c1f3b-2dbc-41ca-9c9d-8eb157a3e73e'
ACCOUNT_ID='1621131832863931'
VIDEO_NAME='丙曜起号10月4日-6.mp4'
VIDEO_PATH=ROOT/'outputs/startup_exports/STARTUP_b681bc5228bb43018cdfb6d4556a7af4'/VIDEO_NAME
VIDEO_SHA256='8e6d565018aca1d2770ad8c38e4efdd27db2aac4e4a84b36cd5a6fa0fbefc256'
SCHEDULED_AT='2026-10-05T15:00:00+08:00'
CONFIG_PATH=ROOT/'xiaovcat_adapter/local_ui_worker.config.json'
RUNTIME=ROOT/'xiaovcat_adapter/runtime/job3_first_real_acceptance'
TASK_NAME='XUNZHEN_XIAOVCAT_PUBLISH_WORKER'


def powershell(script):
    # 仅进程/Task信息或恢复原未武装Task，无桌面控制、无凭证日志。
    value=subprocess.run(['powershell.exe','-NoProfile','-Command',script],
                         capture_output=True,text=True,encoding='utf-8',timeout=20)
    if value.returncode:raise RuntimeError('WINDOWS_MAINTENANCE_CHECK_FAILED')
    return value.stdout.strip()


def worker_processes():
    script=r"""$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[System.Text.Encoding]::UTF8;
$rows=@(Get-CimInstance Win32_Process | Where-Object {
 $_.Name -match '^python(w)?\.exe$' -and $_.ProcessId -ne PID_PLACEHOLDER -and
 $_.CommandLine -match '(?:^|\s)-m\s+(?:xiaovcat_publish_worker|xiaovcat_adapter\.job3_first_acceptance|xiaovcat_adapter\.desktop_worker\.production_worker)(?:\s|$)|xiaovcat_publish_worker\.py'
} | ForEach-Object { [pscustomobject]@{pid=$_.ProcessId;session_id=$_.SessionId;
 resident=($_.CommandLine -match '(?:^|\s)-m\s+xiaovcat_publish_worker(?:\s|$)');
 expected_config=($_.CommandLine -match [regex]::Escape('CONFIG_PLACEHOLDER'))} });
ConvertTo-Json -InputObject $rows -Compress"""
    script=script.replace('PID_PLACEHOLDER',str(os.getpid())).replace('CONFIG_PLACEHOLDER',str(CONFIG_PATH))
    return json.loads(powershell(script))


def check_task(config):
    python=json.loads((ROOT/'config.json').read_text('utf-8'))['paths']['python_executable']
    expected_exe=str(Path(python).with_name('pythonw.exe'))
    expected_args='-X utf8 -m xiaovcat_publish_worker --config "'+str(CONFIG_PATH)+'"'
    script=r"""$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[System.Text.Encoding]::UTF8;
$t=Get-ScheduledTask -TaskName 'XUNZHEN_XIAOVCAT_PUBLISH_WORKER';
$sid=if ($t.Principal.UserId -match '^S-1-') { $t.Principal.UserId } else {
 ([Security.Principal.NTAccount]$t.Principal.UserId).Translate([Security.Principal.SecurityIdentifier]).Value };
[pscustomobject]@{actions=@($t.Actions | ForEach-Object { [pscustomobject]@{exe=$_.Execute;args=$_.Arguments} });
user_sid=$sid;logon=[string]$t.Principal.LogonType} | ConvertTo-Json -Depth 4 -Compress"""
    task=json.loads(powershell(script))
    if (len(task['actions'])!=1 or task['actions'][0]!=dict(exe=expected_exe,args=expected_args)
        or task['user_sid']!=config['windows_user_sid']
        or task['logon']!='Interactive'):
        raise PermissionError('RESIDENT_TASK_IDENTITY_OR_ACTION_MISMATCH')
    return dict(name=TASK_NAME,identity_verified=True)


def validate_locked_config(config):
    # 用户架构纠正：此历史入口绑定服务器，永久禁止再次武装。
    if config.get('hostname','').casefold()=='pc-20260617geop':
        raise PermissionError('SERVER_PUBLISH_EXECUTION_RETIRED_2060S_REQUIRED')
    if (config['worker_id']!='XIAOVCAT-WORKER-01' or not config['worker_enabled']
        or config['dry_run_mode'] is not True or config['real_submit_armed'] is not False
        or config['allowed_plan_ids']!=[PLAN_ID] or config['allowed_job_ids']!=[JOB_ID]
        or Path(config['operations_db']).resolve()!=(ROOT/'operations.db').resolve()
        or Path(config['runtime_dir']).resolve()!=(ROOT/'xiaovcat_adapter/runtime/local_ui_worker').resolve()
        or Path(config['xiaovcat_executable']).resolve()!=Path('D:/小V猫/小V猫.exe').resolve()):
        raise PermissionError('JOB3_LOCKED_UNARMED_CONFIG_REQUIRED')
    if not Path(config['xiaovcat_executable']).is_file():raise RuntimeError('XIAOVCAT_EXECUTABLE_NOT_FOUND')
    if not Path(config['operations_db']).is_file():raise RuntimeError('OPERATIONS_DB_NOT_FOUND')
    if json.loads((ROOT/'xiaovcat_adapter/config.json').read_text('utf-8')).get('real_publish_enabled') is not False:
        raise PermissionError('GLOBAL_PUBLISH_SWITCH_MUST_STAY_OFF')


def validate_policy(policy):
    expected=dict(plan_id=PLAN_ID,job_id=JOB_ID,content_id=CONTENT_ID,account_id=ACCOUNT_ID,
                  account_name='丙曜',platform='抖音',scheduled_at=SCHEDULED_AT,title='',
                  description='陶老师小妙招',topics=['#健康','#健康科普','#养生'],business_type='STARTUP',
                  video_sha256=VIDEO_SHA256)
    for field,value in expected.items():
        if policy.get(field)!=value:raise PermissionError('JOB3_LOCKED_FIELD_MISMATCH:'+field)
    if Path(policy['video_path']).resolve()!=VIDEO_PATH.resolve() or not VIDEO_PATH.is_file():
        raise PermissionError('JOB3_ORIGINAL_VIDEO_REQUIRED')


def check_job(queue):
    # 无迁移、无claim、无数据库写入；复用正式_context，包括在线快照/授权/ffprobe/固定排期。
    row=queue.row(JOB_ID)
    if row['plan_id']!=PLAN_ID or row['state']!='QUEUED' or row['claim_token'] or row['claimed_at']:
        raise PermissionError('JOB3_NOT_UNCLAIMED_NO_REPLAY')
    if queue.submission(JOB_ID)['submit_attempt_count']!=0:
        raise PermissionError('JOB3_ALREADY_ATTEMPTED_NO_RETRY')
    with queue.store.connect() as db:
        policy=queue.dispatcher._context(db,JOB_ID)
    validate_policy(policy)
    return policy


class Job3OnlyQueue(LocalWorkerQueue):
    """代码层硬限制，不依赖可编辑配置扩展范围；所有UI沿用现有Publisher。"""
    def allowed(self,row):
        return row['job_id']==JOB_ID and row['plan_id']==PLAN_ID and super().allowed(row)

    def claim(self,row):
        if not self.allowed(row):raise PermissionError('JOB3_ONLY_NO_OTHER_JOB')
        check_job(self)
        return super().claim(row)

    def scope(self,row,nonce,results):
        if not self.allowed(row):raise PermissionError('JOB3_ONLY_NO_OTHER_JOB')
        scope=super().scope(row,nonce,results)
        validate_policy(scope.policy)  # 原子claim之后再次核验，防预检到claim的配置竞态。
        return scope


def check_resident(config,presence,*,inventory=worker_processes):
    from .local_session import process_user_sid
    rows=inventory()
    if len(rows)!=1 or not rows[0]['resident'] or not rows[0]['expected_config']:
        raise RuntimeError('EXACTLY_ONE_EXPECTED_RESIDENT_WORKER_REQUIRED')
    row=rows[0]
    if row['session_id']!=presence['session_id'] or process_user_sid(row['pid'])!=config['windows_user_sid']:
        raise PermissionError('WORKER_USER_OR_SESSION_MISMATCH')
    beat=json.loads((Path(config['runtime_dir'])/'heartbeat.json').read_text('utf-8'))
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(beat['last_heartbeat'])).total_seconds()
    if (beat['pid']!=row['pid'] or beat['worker_id']!=config['worker_id'] or beat['current_job_id'] is not None
        or beat['status'] not in {'IDLE','ARMED_REQUIRED'} or not 0<=age<=75
        or beat['dry_run_mode'] is not True or beat['real_submit_armed'] is not False
        or beat['real_publish_enabled'] is not False):
        raise RuntimeError('RESIDENT_NOT_FRESH_UNARMED_IDLE')
    return row


def preflight(config,queue,*,session_check=None,inventory=worker_processes,task_check=check_task):
    from .local_session import check_session
    validate_locked_config(config)
    presence=(session_check or check_session)(config)
    resident=check_resident(config,presence,inventory=inventory)
    task=task_check(config)
    policy=check_job(queue)
    return dict(status='PREFLIGHT_PASS_NO_UI',policy=policy,resident=resident,task=task,
                submit_attempt_count=0,real_submit_armed=False,real_publish_enabled=False)


def stop_idle_resident(config,expected_pid,*,inventory=worker_processes):
    from .local_session import check_session
    current=load_config(CONFIG_PATH);validate_locked_config(current)
    if check_resident(current,check_session(current),inventory=inventory)['pid']!=expected_pid:
        raise RuntimeError('WORKER_INSTANCE_CHANGED_DURING_HANDOFF')
    marker=Path(config['runtime_dir'])/'STOP_WORKER'
    # 此函数只由用户实际执行入口调用。正常停空闲未武装Worker，不kill、不停小V猫。
    with marker.open('x',encoding='utf-8') as stream:stream.write('USER_JOB3_ONE_SHOT_HANDOFF\n')
    deadline=time.monotonic()+40
    while True:
        rows=inventory()
        if not rows:return
        if len(rows)!=1 or rows[0]['pid']!=expected_pid:
            raise RuntimeError('WORKER_INSTANCE_CHANGED_DURING_HANDOFF')
        if time.monotonic()>=deadline:raise RuntimeError('RESIDENT_GRACEFUL_STOP_TIMEOUT_NO_KILL')
        time.sleep(.25)


def execute_user_once(config,queue,*,worker_factory=PublishWorker):
    # 防双击入口；这不是生产Worker互斥，预检阶段仍可有唯一未武装常驻实例。
    marker=Path(config['runtime_dir'])/'STOP_WORKER'
    with instance_lock(RUNTIME/'user_entry.lock'):
        if marker.exists():raise RuntimeError('EXISTING_STOP_MARKER_NO_OVERWRITE')
        checked=preflight(config,queue)
        write_json(RUNTIME/'PREFLIGHT.json',checked)
        worker=None;handed_off=False
        try:
            handed_off=True
            stop_idle_resident(config,checked['resident']['pid'])
            with single_instance(config['runtime_dir']):
                # 用户运行才会到达此处；二次严格验证通过之后才启用内存能力。
                config=load_config(CONFIG_PATH);validate_locked_config(config)
                queue.config=config
                queue.authority()
                check_job(queue)
                if worker_processes():raise RuntimeError('OTHER_WORKER_PRESENT_NO_ARM')
                worker=worker_factory(config,queue,one_shot=True)
                queue.authority=worker.authority
                config.update(dry_run_mode=False,real_submit_armed=True)
                write_json(RUNTIME/'ARMED.json',dict(job_id=JOB_ID,plan_id=PLAN_ID,
                    armed_at=datetime.now().astimezone().isoformat(),scope='ONE_PROCESS_MEMORY_ONLY',
                    persistent_config_armed=False))
                # 只run_once，不进入循环，不消费任何其它Job。
                return worker.run_once()
        finally:
            config.update(dry_run_mode=True,real_submit_armed=False)
            queue.config=config
            if worker is not None:worker.revoke_submit_permission()
            write_json(RUNTIME/'DISARMED.json',dict(job_id=JOB_ID,real_submit_armed=False,real_publish_enabled=False,
                       disarmed_at=datetime.now().astimezone().isoformat(),persistent_config_unchanged=True))
            if handed_off and marker.exists() and marker.read_text('utf-8')=='USER_JOB3_ONE_SHOT_HANDOFF\n':
                marker.unlink()  # 只移除本入口自己的正常停止标记。
                # 原Task配置未改、仍Dry Run；任何重启都不带真实发布权限。
                restored=load_config(CONFIG_PATH);validate_locked_config(restored);check_task(restored)
                powershell("$ErrorActionPreference='Stop'; Start-ScheduledTask -TaskName 'XUNZHEN_XIAOVCAT_PUBLISH_WORKER'")


def main():
    print('JOB_CANCELLED')
    return 20
    parser=argparse.ArgumentParser();parser.add_argument('--preflight-only',action='store_true')
    args=parser.parse_args()
    RUNTIME.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(level=logging.INFO,handlers=[logging.FileHandler(RUNTIME/'acceptance.log',encoding='utf-8')],
                        format='%(asctime)s %(levelname)s %(message)s')
    from publish_planner.storage import PlannerStore
    from startup_pipeline.production_dispatch import ProductionDispatcher
    from .local_session import check_session
    config=load_config(CONFIG_PATH)
    queue=Job3OnlyQueue(ProductionDispatcher(PlannerStore(config['operations_db'])),config,lambda:check_session(config))
    try:
        result=preflight(config,queue) if args.preflight_only else execute_user_once(config,queue)
        result.update(real_submit_armed=False,real_publish_enabled=False)
        write_json(RUNTIME/('PREPARE_PREFLIGHT.json' if args.preflight_only else 'RESULT.json'),result)
        print(json.dumps(result,ensure_ascii=False))
        return 0 if result.get('verified') or args.preflight_only else 1
    except Exception as error:
        code=safe_code(error)
        result=dict(status='PREFLIGHT_BLOCKED' if args.preflight_only else 'STOPPED_NEEDS_MANUAL',failure_code=code,
                    job_id=JOB_ID,real_submit_armed=False,real_publish_enabled=False)
        write_json(RUNTIME/('PREPARE_PREFLIGHT.json' if args.preflight_only else 'RESULT.json'),result)
        logging.error('job_id=%s failure_code=%s',JOB_ID,code)
        print(json.dumps(result,ensure_ascii=False));return 1


if __name__=='__main__':raise SystemExit(main())
