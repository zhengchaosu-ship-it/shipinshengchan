"""Confirm后的本机Worker通知，限定独立灰度Plan；不启动旧发布节点。"""
import json
from pathlib import Path
import subprocess
from .cli_runner import run_hidden

from .worker import write_json
from .storage import production_enabled

ROOT=Path(__file__).resolve().parents[1]
CONFIG=ROOT/'yixiaoer_adapter/worker.config.json'


def notify_confirmed(store, token, plan_id):
    with store.connect() as db:
        actor=store._principal(db,token)
        plan=db.execute('SELECT * FROM publish_plans WHERE plan_id=?',(plan_id,)).fetchone()
        canary=db.execute('SELECT * FROM yixiaoer_canary_plans WHERE plan_id=?',(plan_id,)).fetchone()
        count=db.execute('SELECT count(*) FROM provider_publish_jobs WHERE plan_id=?',(plan_id,)).fetchone()[0]
        production=production_enabled(db)
        authorization=db.execute('SELECT * FROM provider_plan_authorizations WHERE plan_id=?',(plan_id,)).fetchone() if production else None
        valid_production=bool(authorization and count==len(json.loads(authorization['content_ids_json'])) and count>0)
        if not plan or plan['employee_id']!=actor['employee_id'] or plan['status']!='CONFIRMED' or not (valid_production or (not production and canary and count==3)):
            raise PermissionError('USER_CONFIRMED_PROVIDER_PLAN_REQUIRED')
    config=json.loads(CONFIG.read_text('utf-8-sig'))
    plans=list(dict.fromkeys([*config.get('allowed_plan_ids',[]),plan_id])) if config['worker_enabled'] else [plan_id]
    config.update(worker_enabled=True,allowed_plan_ids=plans,execution_mode='CONFIRMED_PRODUCTION' if production else 'CANARY_ONLY')
    write_json(CONFIG,config)
    result=run_hidden(['powershell.exe','-NoProfile','-Command',"Start-ScheduledTask -TaskName 'YIXIAOER_PUBLISH_WORKER_SERVER_01'"],capture_output=True,timeout=20)
    if result.returncode:
        raise RuntimeError('YIXIAOER_WORKER_START_FAILED_PLAN_PRESERVED')
    return {'plan_id':plan_id,'worker_id':config['worker_id'],'scope':'USER_CONFIRMED_PRODUCTION' if production else 'EXPLICIT_THREE_TEST_CONTENT_CANARY','queued_jobs':count}
