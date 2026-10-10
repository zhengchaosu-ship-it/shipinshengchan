"""账号API和LOCAL执行器历史证据分别显示，不虚构实时在线接口。"""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from .cli_runner import run_hidden

from .storage import enabled


def health(store, config):
    result={'client_process':'UNKNOWN','ACCOUNT_API_OK':'UNKNOWN','LOCAL_EXECUTOR_LAST_CONFIRMED':'UNKNOWN',
            'clientId':'UNKNOWN','test_account_visible':'UNKNOWN','last_successful_query':'UNKNOWN','last_heartbeat':'UNKNOWN'}
    result.update(primary_provider=config.get('primary_provider','yixiaoer'),execution_mode=config.get('execution_mode','UNKNOWN'),
                  worker_enabled=bool(config.get('worker_enabled')),authorized_plan_count=len(config.get('allowed_plan_ids',[])))
    credentials=json.loads(Path(config['cli_config']).read_text('utf-8-sig'))
    result['clientId']=credentials.get('localPublishClientId','UNKNOWN')
    command="@(Get-Process -Name '蚁小二4.0' -ErrorAction SilentlyContinue).Count"
    observed=run_hidden(['powershell.exe','-NoProfile','-Command',command],capture_output=True,timeout=10)
    if observed.returncode==0:
        result['client_process']=int(observed.stdout.decode().strip())
    with store.connect() as db:
        settings=dict(db.execute('SELECT key,value FROM yixiaoer_settings')) if enabled(db) else {}
        query=settings.get('last_successful_account_query')
        result['last_successful_query']=query or 'UNKNOWN'
        result['ACCOUNT_API_OK']=bool(query and 0 <= (datetime.now(timezone.utc)-datetime.fromisoformat(query)).total_seconds() <= 1800)
        result['LOCAL_EXECUTOR_LAST_CONFIRMED']=settings.get('local_executor_last_confirmed','UNKNOWN')
        result['test_account_visible']=bool(db.execute("SELECT 1 FROM provider_account_bindings WHERE provider_account_id=? AND provider_account_status='ONLINE'",(config['test_provider_account_id'],)).fetchone())
    heartbeat=Path(config['runtime_dir'])/'heartbeat.json'
    if heartbeat.exists():
        result['worker']=json.loads(heartbeat.read_text('utf-8'))
        result['last_heartbeat']=result['worker'].get('last_heartbeat','UNKNOWN')
    result['executor_realtime_online']='UNKNOWN'
    return result
