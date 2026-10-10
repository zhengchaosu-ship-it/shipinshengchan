"""恢复到新的隔离目录并验证身份/发布闩锁；不会启动Worker或触发外部写入。"""
import argparse
import json
from pathlib import Path
import shutil
import sqlite3
from contextlib import closing
from .operations import verify_backup


def restore(backup, destination):
    backup=Path(backup).resolve();destination=Path(destination).resolve()
    manifest=verify_backup(backup)
    if destination.exists():raise ValueError('RESTORE_DESTINATION_MUST_NOT_EXIST')
    destination.mkdir(parents=True)
    for item in manifest['databases']:shutil.copy2(backup/item['file'],destination/item['file'])
    from uuid import uuid4
    from startup_autopilot.production import utcnow
    restore_id=str(uuid4())
    for name in ('operations.db','render_jobs.db'):
        with closing(sqlite3.connect(destination/name)) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS production_restore_guard(id INTEGER PRIMARY KEY,restore_id TEXT,state TEXT,restored_at TEXT,confirmed_by TEXT,confirmed_at TEXT)''')
            db.execute("INSERT OR REPLACE INTO production_restore_guard VALUES(1,?,'HOLD_RECONCILIATION_REQUIRED',?,NULL,NULL)",(restore_id,utcnow().isoformat()));db.commit()
    if (backup/'evidence').is_dir():shutil.copytree(backup/'evidence',destination/'evidence')
    with closing(sqlite3.connect(destination/'operations.db')) as db:
        db.row_factory=sqlite3.Row
        bindings=[dict(r) for r in db.execute('SELECT business_account_id,provider_account_id FROM provider_account_bindings')]
        identities=[r['provider_account_id'] for r in bindings]
        if len(identities)!=len(set(identities)):raise ValueError('RESTORED_PROVIDER_MAPPING_AMBIGUOUS')
        auths=[dict(r) for r in db.execute('SELECT account_id,status,enabled,config_hash FROM autopilot_authorizations')]
        jobs=[dict(r) for r in db.execute('SELECT job_id,state,submit_attempt_count,provider_task_set_id,provider_task_id FROM provider_publish_jobs')]
        if any(j['submit_attempt_count'] not in (0,1) for j in jobs):raise ValueError('RESTORED_SUBMIT_LATCH_INVALID')
        if db.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('RESTORED_FOREIGN_KEY_INVALID')
    report={'validated':True,'restored_to':str(destination),'account_bindings':bindings,'autopilot_states':auths,
        'provider_jobs':jobs,'render_publish_calls':0,'workers_started':False,'dispatch_guard':'HOLD_RECONCILIATION_REQUIRED',
        'next_action':'保持服务停止，核验路径和客户端授权；已提交任务只读对账，绝不重置submit_attempt_count。'}
    (destination/'restore.report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--backup',required=True);parser.add_argument('--destination',required=True)
    args=parser.parse_args();result=restore(args.backup,args.destination)
    print(json.dumps({'validated':result['validated'],'workers_started':False,'render_publish_calls':0},ensure_ascii=False))


if __name__=='__main__':main()
