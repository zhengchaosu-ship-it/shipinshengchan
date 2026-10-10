"""2060本机只读官方CLI预检；不上传、不提交、不得复制Server clientId。"""
import json
import os
from pathlib import Path
import socket
from datetime import datetime,timezone
from startup_render.common import read
from yixiaoer_adapter.cli_runner import run_hidden
from .coordinator import atomic_json


def main():
    if socket.gethostname()!='DESKTOP-9VQ76D3':raise PermissionError('2060_HOST_REQUIRED')
    root=Path('D:/JianyingRenderWorker/Resident')
    config=read(root/'media_execution.config.json')
    user=Path.home();app=read(user/'AppData/Roaming/蚁小二4.0/config.json')
    credentials=read(config['cli_config'])
    if credentials['localPublishClientId']!=app['deviceId']:raise PermissionError('LOCAL_CLIENT_ID_MISMATCH')
    observations={}
    for key,args in [('doctor',['doctor']),('accounts',['accounts','list','douyin','--json'])]:
        result=run_hidden([config['cli_executable'],*args],capture_output=True,timeout=75)
        value=json.loads(result.stdout)
        if result.returncode or value.get('ok') is not True:raise RuntimeError('LOCAL_'+key.upper()+'_FAILED')
        observations[key]=value
    data=observations['accounts']['data']
    count=len(data) if isinstance(data,list) else None
    proof={'hostname':socket.gethostname(),'local_client_verified':True,'client_id':app['deviceId'],
           'source':'LOCAL_APP_CONFIG_AND_OFFICIAL_CLI_DOCTOR','cli_version':observations['doctor']['version'],
           'schema_ready':observations['doctor']['data']['schemaDirOK'],'account_api_ok':True,'visible_account_count':count,
           'checked_at':datetime.now(timezone.utc).isoformat(),'provider_writes':0,'realtime_provider_executor_online':'UNKNOWN_NOT_ASSERTED'}
    atomic_json(root/'yixiaoer_local_ready.json',proof)
    print(json.dumps(proof,ensure_ascii=True))


if __name__=='__main__':main()
