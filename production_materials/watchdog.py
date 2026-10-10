"""本机素材服务守护：只恢复已退出的原单实例Task，不操作8502或生产执行器。"""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time
from urllib.request import urlopen

from .config import HERE, ROOT, settings
from yixiaoer_adapter.worker import single_instance
from server_maintenance.file_io import write_json

TASK = 'XunZhen-ProductionMaterialUpload-8510'
OUT = HERE/'runtime/watchdog'


def decision(healthy, process_count, task_state, enabled, attempts, now):
    if healthy:
        return 'HEALTHY'
    if process_count:
        return 'NEEDS_ATTENTION_EXISTING_PROCESS'
    if not enabled:
        return 'DISABLED_NO_AUTOMATIC_START'
    if task_state!='Ready':
        return 'TASK_NOT_READY_NO_SECOND_INSTANCE'
    recent = [t for t in attempts if now-t<86400]
    if len(recent)>=3 or recent and now-max(recent)<3600:
        return 'RECOVERY_BACKOFF'
    return 'START_ORIGINAL_TASK'


def powershell(script):
    result = subprocess.run(['powershell.exe','-NoProfile','-Command',script],capture_output=True,
                            timeout=25,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError('MATERIAL_TASK_PROBE_OR_START_FAILED')
    return json.loads(result.stdout.decode('utf-8-sig'))


def probe():
    return powershell("""
$ErrorActionPreference='Stop'
$task=Get-ScheduledTask -TaskName 'XunZhen-ProductionMaterialUpload-8510'
$processes=@(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -in @('python.exe','pythonw.exe') -and $_.CommandLine -match '-m production_materials.service'
})
[PSCustomObject]@{state=[string]$task.State;enabled=$task.Settings.Enabled;process_count=$processes.Count;
                 execute=$task.Actions.Execute;arguments=$task.Actions.Arguments;directory=$task.Actions.WorkingDirectory} | ConvertTo-Json -Compress
""")


def check_action(value):
    expected = '-X utf8 -B -m production_materials.service --config "'+str(HERE/'service.config.json')+'"'
    if (Path(value['execute']).resolve()!=ROOT/'.venv-cuda-test/Scripts/pythonw.exe' or
        value['arguments']!=expected or Path(value['directory']).resolve()!=ROOT):
        raise RuntimeError('UNEXPECTED_MATERIAL_TASK_NO_START')


def main():
    config = settings()
    with single_instance(OUT/'lock'):
        state_path = OUT/'budget.json'
        state = json.loads(state_path.read_text('utf-8')) if state_path.exists() else {'attempts':[]}
        healthy = False
        try:
            with urlopen('http://127.0.0.1:'+str(config['port'])+'/health',timeout=4) as response:
                value = json.loads(response.read(4096))
                healthy = response.status==200 and value.get('status')=='READY' and value.get('service')=='PRODUCTION_MATERIAL_UPLOAD'
        except (OSError,ValueError):
            pass
        value = probe()
        check_action(value)
        now = time.time()
        action = decision(healthy,value['process_count'],value['state'],value['enabled'],state['attempts'],now)
        if action=='START_ORIGINAL_TASK':
            # 启动意图先持久化，崩溃/重复触发不能重置恢复预算。
            state['attempts'] = [t for t in state['attempts'] if now-t<86400]+[now]
            write_json(state_path,state)
            result = powershell("""
$ErrorActionPreference='Stop'
$task=Get-ScheduledTask -TaskName 'XunZhen-ProductionMaterialUpload-8510'
$processes=@(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -in @('python.exe','pythonw.exe') -and $_.CommandLine -match '-m production_materials.service'
})
if($task.State -eq 'Ready' -and $task.Settings.Enabled -and $processes.Count -eq 0){
    Start-ScheduledTask -TaskName $task.TaskName
    @{action='START_REQUESTED'} | ConvertTo-Json -Compress
}else{@{action='STATE_CHANGED_NO_START'} | ConvertTo-Json -Compress}
""")
            action = result['action']
            with (OUT/'actions.jsonl').open('a',encoding='utf-8') as stream:
                stream.write(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'action':action,'owner':'SERVER_ENGINEER','scope':'MATERIAL_UPLOAD_ONLY'})+'\n')
        report = {'at':datetime.now(timezone.utc).isoformat(),'service':'PRODUCTION_MATERIAL_UPLOAD',
                  'healthy':healthy,'task':value['state'],'process_count':value['process_count'],
                  'result':action,'recovery_attempts_24h':len([t for t in state['attempts'] if now-t<86400]),
                  'no_forced_stop':True,'production_jobs_created':0,'publish_calls':0}
        write_json(OUT/'latest.json',report)
        print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    main()
