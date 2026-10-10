"""只收口有启动记录、父入口消失的旧Server API；未知进程一律拒绝。"""
from datetime import datetime
import json
import subprocess

from .watchdog import OUT, audit
from .precheck import PLANNER_CONFIG, API_CONFIG


def inspect(role='api'):
    if role not in ('api','planner'):raise ValueError('SERVER_ROLE_REQUIRED')
    module='startup_render.lan_server' if role=='api' else 'startup_autopilot.production_worker'
    config=(API_CONFIG if role=='api' else PLANNER_CONFIG).name
    record=json.loads((OUT/'services'/role/'child.json').read_text('utf-8'))
    pid=int(record['pid'])
    script=f"""
$all=@(Get-CimInstance Win32_Process)
$root=$all | Where-Object {{$_.ProcessId -eq {pid}}}
if (-not $root) {{throw 'KNOWN_API_CHILD_MISSING'}}
$family=@($root)+@($all | Where-Object {{$_.ParentProcessId -eq {pid}}})
$proof=@($family | ForEach-Object {{@{{pid=$_.ProcessId;parent=$_.ParentProcessId;created=$_.CreationDate.ToUniversalTime().ToString('o');valid=($_.Name -match '^python(w)?\\.exe$' -and $_.CommandLine -like '*-m {module} --config *{config}*')}}}})
@{{processes=$proof;parent_missing=(-not ($all | Where-Object {{$_.ProcessId -eq $root.ParentProcessId}}))}} | ConvertTo-Json -Depth 5 -Compress
"""
    result=subprocess.run(['powershell.exe','-NoProfile','-Command',script],capture_output=True,check=True,
                          timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
    proof=json.loads(result.stdout.decode('utf-8-sig'))
    if not proof['parent_missing'] or not 1<=len(proof['processes'])<=2 or not all(r['valid'] for r in proof['processes']):
        raise RuntimeError('UNKNOWN_OR_NON_ORPHAN_API_PRESERVED')
    created=datetime.fromisoformat(proof['processes'][0]['created'])
    started=datetime.fromisoformat(record['started_at'])
    if abs((created-started).total_seconds())>10:raise RuntimeError('API_PID_REUSED_PRESERVED')
    return proof


def stop(proof,evidence,role='api'):
    fresh=inspect(role)
    if fresh!=proof:raise RuntimeError('API_ORPHAN_EVIDENCE_CHANGED')
    action='STOP_PROVEN_SERVER_'+role.upper()+'_ORPHAN'
    audit(OUT,'ORPHAN_SERVER_PARENT_EXIT',evidence,action,proof,None,'INTENT')
    statements=[]
    for row in reversed(proof['processes']):
        statements.append(f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={row['pid']}'; if ($p) {{if ($p.CreationDate.ToUniversalTime().ToString('o') -ne '{row['created']}') {{throw 'PID_REUSED'}}; Stop-Process -Id {row['pid']} -ErrorAction Stop}}")
    subprocess.run(['powershell.exe','-NoProfile','-Command',"$ErrorActionPreference='Stop'; "+'; '.join(statements)],
                   check=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
    audit(OUT,'ORPHAN_SERVER_PARENT_EXIT',evidence,action,proof,{'stopped_pids':[r['pid'] for r in proof['processes']]},'COMPLETE')
