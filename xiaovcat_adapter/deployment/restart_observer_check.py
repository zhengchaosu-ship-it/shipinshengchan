"""维护补证：只重启未武装数据observer，不调用UI、claim、提交或账号同步。"""
from datetime import datetime,timezone
import json
from pathlib import Path
import time

from xiaovcat_adapter.lan_publish_worker import Worker,user_handoff
from xiaovcat_adapter.lan_publish_contract import JOB_ID,WORKER_ID,WINDOWS_SID
from xiaovcat_adapter.local_session import process_user_sid
from xiaovcat_adapter.desktop_worker.resident_monitor import write_json


def main():
    root=Path(__file__).resolve().parent
    config=json.loads((root/'worker.config.json').read_text('utf-8'))
    worker=Worker(config)  # validate_config要求disk dry=true/armed=false/global=false。
    old=json.loads((worker.root/'heartbeat.json').read_text('utf-8'))
    before=worker.observe_data()
    if before['submit_attempt_count']!=0 or before['dispatch_state']!='QUEUED':
        raise RuntimeError('OBSERVER_RESTART_REQUIRES_UNCLAIMED_JOB3')
    if len(before['jobs'])!=1 or before['jobs'][0]['job_id']!=JOB_ID:
        raise RuntimeError('JOB3_ONLY')
    started=datetime.now(timezone.utc)
    # 原正常停止标记等待+锁交接，finally启动原未武装Task。没有kill或任何桌面调用。
    with user_handoff(worker):
        during=worker.observe_data()
        if during!=before:raise RuntimeError('QUEUE_CHANGED_DURING_RESTART')
    deadline=time.monotonic()+55
    while True:
        heartbeat=json.loads((worker.root/'heartbeat.json').read_text('utf-8'))
        if (heartbeat['pid']!=old['pid'] and heartbeat['worker_id']==WORKER_ID
            and datetime.fromisoformat(heartbeat['last_heartbeat'])>=started
            and heartbeat['status']=='IDLE' and heartbeat['current_job_id'] is None):break
        if time.monotonic()>=deadline:raise RuntimeError('OBSERVER_RESTART_HEARTBEAT_TIMEOUT')
        time.sleep(.5)
    import psutil
    processes=[]
    for process in psutil.process_iter(['pid','ppid','name','cmdline']):
        try:
            command=' '.join(process.info['cmdline'] or []).replace('/','\\').casefold()
            if ('d:\\xunzhenpublishworker\\xiaovcat_publish_worker.py' in command
                and '--user-' not in command and '--data-once' not in command):
                processes.append(dict(pid=process.pid,ppid=process.info['ppid']))
        except (psutil.NoSuchProcess,psutil.AccessDenied):continue
    pids={p['pid'] for p in processes}
    families=[p for p in processes if p['ppid'] not in pids]
    if len(families)!=1 or heartbeat['pid'] not in pids or len(pids)>2:
        raise RuntimeError('OBSERVER_SINGLE_INSTANCE_CHECK_FAILED')
    if any(process_user_sid(pid)!=WINDOWS_SID for pid in pids):
        raise RuntimeError('OBSERVER_USER_MISMATCH')
    after=worker.observe_data()
    if after!=before:raise RuntimeError('QUEUE_CHANGED_AFTER_RESTART')
    if not heartbeat['dry_run_mode'] or heartbeat['real_submit_armed'] or heartbeat['real_publish_enabled']:
        raise RuntimeError('OBSERVER_NOT_UNARMED')
    proof=dict(status='UNARMED_OBSERVER_RESTART_PASS',started_at=started.isoformat(),
        finished_at=datetime.now(timezone.utc).isoformat(),old_pid=old['pid'],new_pid=heartbeat['pid'],
        processes=processes,instance_families=len(families),heartbeat=heartbeat,
        job_id=JOB_ID,submit_attempt_count=after['submit_attempt_count'],dispatch_state=after['dispatch_state'],
        queue_unchanged=True,ui_calls=0,claim_calls=0,submit_calls=0,
        production_executor_acceptance=False,real_submit_armed=False,real_publish_enabled=False)
    write_json(worker.root/'OBSERVER_RESTART_ACCEPTANCE.json',proof)
    print(json.dumps(proof,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
