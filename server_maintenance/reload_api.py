"""本次Hotfix的API安全加载；只在重槽空闲且无候选任务时执行。"""
from pathlib import Path
import subprocess
import time

from .precheck import ROOT, PLANNER_CONFIG, API_CONFIG, read_config, service_precheck
from .watchdog import OUT, database_snapshot, host_probe, api_health, audit


def main():
    c=read_config(PLANNER_CONFIG); a=read_config(API_CONFIG)
    state=database_snapshot(c['operations_db'],Path(a['state_root'])/'render_jobs.db',time.time())
    host=host_probe()
    if host['api']['instance_count']!=1 or state['node']['state']!='ONLINE' or state['heavy_slot']['state']!='IDLE':
        raise RuntimeError('API_RELOAD_DEFERRED_ACTIVE_SLOT_OR_UNKNOWN_NODE')
    if state['queue']['waiting_render'] or state['queue']['waiting_publish']:
        raise RuntimeError('API_RELOAD_DEFERRED_RUNNABLE_QUEUE')
    service_precheck('api')
    old_pids=set(host['api']['pids'])
    task=host['api']['task_name']
    evidence={'heavy_slot':state['heavy_slot'],'queue':state['queue'],'2060':state['node'],
              'changes':'DIRECT_DISK_GUARD_ROTATION_NO_STARTUP_MIGRATION','no_render_submit_calls':True}
    if host['api'].get('wrapper_count')==0:
        if state['node'].get('executor_quiescent') is not True:
            raise RuntimeError('ORPHAN_API_RECOVERY_DEFERRED_EXECUTOR_NOT_QUIESCENT')
        from .orphan_api import inspect,stop
        proof=inspect()
        stop(proof,evidence)
    audit(OUT,'LOAD_VERIFIED_LOCAL_HOTFIX',evidence,'RELOAD_FORMAL_API_TASK',host['api'],None,'INTENT')
    script="Stop-ScheduledTask -TaskName '"+task+"'; Start-ScheduledTask -TaskName '"+task+"'"
    subprocess.run(['powershell.exe','-NoProfile','-Command',script],check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    deadline=time.time()+45
    while time.time()<deadline:
        time.sleep(2)
        fresh=host_probe()['api']
        from startup_render.lan_protocol import token_from
        from .watchdog import http_health
        coordination=http_health(f"http://{a['render_api_host']}:{a['port']}/maintenance/coordination",token_from(a))
        if (api_health(a).get('online') and fresh['instance_count']==1 and fresh['task_state']=='Running'
            and fresh.get('wrapper_count')==1 and not old_pids.intersection(fresh['pids']) and coordination.get('online')):
            result=database_snapshot(c['operations_db'],Path(a['state_root'])/'render_jobs.db',time.time())
            if result['node']['state']=='ONLINE':
                audit(OUT,'LOAD_VERIFIED_LOCAL_HOTFIX',evidence,'RELOAD_FORMAL_API_TASK',host['api'],host_probe()['api'],'SELF_CHECK_PASS')
                print('API_RELOAD_SELF_CHECK_PASS'); return
    audit(OUT,'API_HOTFIX_SELF_CHECK_FAILED',evidence,'PRESERVE_AND_REQUEST_SERVER_OWNER',None,host_probe()['api'],'FAILED')
    # 未知进程/正在运行的副作用不允许通过自动回滚掩盖；保留现场。
    raise RuntimeError('API_HOTFIX_SELF_CHECK_FAILED_SERVER_ACTION_REQUIRED')


if __name__=='__main__':main()
