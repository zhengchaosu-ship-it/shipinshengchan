"""一键回滚本次局部Hotfix和正式Task动作；从不覆盖业务数据库。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

from .precheck import ROOT, PLANNER_CONFIG, API_CONFIG, read_config
from .watchdog import OUT, host_probe, database_snapshot, audit

FILES = ('production_autopilot/operations.py','startup_autopilot/production_worker.py',
         'media_execution/production.py','startup_render/lan_server.py')


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--apply',action='store_true'); args=parser.parse_args()
    c=read_config(PLANNER_CONFIG); a=read_config(API_CONFIG)
    state=database_snapshot(c['operations_db'],Path(a['state_root'])/'render_jobs.db',time.time())
    if not args.apply:
        print(json.dumps({'rollback_available':(OUT/'rollback_manifest.json').is_file() and all((ROOT/(p+'.maintenance-watchdog-20261009.bak')).is_file() for p in FILES),
                          'safe_to_stop':state['heavy_slot']['state']=='IDLE' and state['node']['executor_quiescent'] is True,
                          'database_restore':False})); return
    if state['heavy_slot']['state']!='IDLE' or state['node']['state']!='ONLINE' or state['node']['executor_quiescent'] is not True:
        raise RuntimeError('ROLLBACK_DEFERRED_ACTIVE_EXECUTION')
    from .storage import disk_probe
    if disk_probe(ROOT)['state']!='NORMAL':raise RuntimeError('ROLLBACK_DEFERRED_UNSAFE_STORAGE')
    # 其它Server修复可能随后改同一文件；绝不以旧备份覆盖新的独立修复。
    rollback_files=json.loads((OUT/'rollback_manifest.json').read_text('utf-8'))['files']
    verified=json.loads((OUT/'rollback_self_check.json').read_text('utf-8'))
    if verified['state']!='PASS':raise RuntimeError('ROLLBACK_SELF_CHECK_NOT_PASSED')
    for p in FILES:
        current=hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
        manifest=OUT/'deployment_hashes.json'
        if not manifest.exists() or json.loads(manifest.read_text('utf-8')).get(p)!=current:
            raise RuntimeError('ROLLBACK_SOURCE_CHANGED_REVIEW_REQUIRED: '+p)
        if hashlib.sha256(Path(rollback_files[p]).read_bytes()).hexdigest()!=verified['source_hashes'][p]:
            raise RuntimeError('ROLLBACK_FALLBACK_CHANGED: '+p)
    evidence=audit(OUT,'HOTFIX_SELF_CHECK_FAILED',state['heavy_slot'],'ROLLBACK',None,None,'INTENT')
    names=('XUNZHEN_SERVER_LOCAL_GUARD_V2','XUNZHEN_SERVER_MAINTENANCE_SNAPSHOT_V2',
           'STARTUP_AUTOPILOT_PRODUCTION_SERVER_01','XunZhen-Startup-Render-server')
    # 避免一分钟监督任务在回滚期间重新启动尚未恢复完成的服务。
    disable="\n".join("Disable-ScheduledTask -TaskName '"+name+"' | Out-Null" for name in names[:2])
    subprocess.run(['powershell.exe','-NoProfile','-Command',disable],check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    script="\n".join("Stop-ScheduledTask -TaskName '"+name+"' -ErrorAction SilentlyContinue" for name in names)
    subprocess.run(['powershell.exe','-NoProfile','-Command',script],check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    deadline=time.time()+15
    while time.time()<deadline and any(host_probe()[r]['instance_count'] for r in ('api','planner')):
        time.sleep(1)
    # 部署前旧入口没有Job；只收口启动记录和创建时间匹配、且父入口已退出的Server子树。
    from .orphan_api import inspect,stop
    for role in ('api','planner'):
        if host_probe()[role]['instance_count']:
            fresh=database_snapshot(c['operations_db'],Path(a['state_root'])/'render_jobs.db',time.time())
            if fresh['heavy_slot']['state']!='IDLE' or fresh['node'].get('executor_quiescent') is not True:
                raise RuntimeError('ROLLBACK_ORPHAN_STOP_DEFERRED_ACTIVE_EXECUTION')
            proof=inspect(role); stop(proof,{'rollback':True,'heavy_slot':fresh['heavy_slot'],'node':fresh['node']},role)
    if any(host_probe()[r]['instance_count'] for r in ('api','planner')):
        raise RuntimeError('ROLLBACK_SERVICE_STOP_NOT_CONFIRMED')
    for p in FILES:
        backup=Path(rollback_files[p]).resolve()
        if not backup.is_relative_to((OUT/'rollback_sources').resolve()):raise ValueError('ROLLBACK_SOURCE_PATH_INVALID')
        shutil.copy2(backup,ROOT/p)
    for role,name in [('planner',names[2]),('api',names[3])]:
        xml=(OUT/'task_baseline'/(role+'.xml')).read_text('utf-8-sig')
        # XML从本次现场Task基线读取，通过普通参数脚本转义引号。
        quoted=xml.replace("'","''")
        code="Register-ScheduledTask -TaskName '"+name+"' -Xml '"+quoted+"' -Force | Out-Null; Start-ScheduledTask -TaskName '"+name+"'"
        subprocess.run(['powershell.exe','-NoProfile','-Command',code],check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    enable="\n".join("Enable-ScheduledTask -TaskName '"+name+"' | Out-Null" for name in names[:2])
    subprocess.run(['powershell.exe','-NoProfile','-Command',enable],check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    audit(OUT,'HOTFIX_SELF_CHECK_FAILED',{'source_files':list(FILES)},'ROLLBACK',evidence,host_probe(),'RESTORED_OLD_CODE_AND_TASKS_NO_DB_RESTORE')


if __name__=='__main__': main()
