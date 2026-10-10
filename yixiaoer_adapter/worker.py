"""服务器LOCAL Worker；Confirm后串行消费显式灰度范围，不采用旧Job。"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import time

from publish_planner.storage import PlannerStore
from .publisher import YixiaoerPublisherAdapter, ProviderError
from .storage import ProviderStore, audit, production_enabled


def write_json(path, value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    with temp.open('w',encoding='utf-8') as target:
        json.dump(value,target,ensure_ascii=False,indent=2); target.flush(); os.fsync(target.fileno())
    os.replace(temp,path)


@contextmanager
def single_instance(runtime):
    import msvcrt
    path=Path(runtime)/'worker.lock'; path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as lock:
        lock.seek(0); lock.write(b'1'); lock.flush(); lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:
            raise RuntimeError('YIXIAOER_WORKER_ALREADY_RUNNING')
        try:
            yield
        finally:
            lock.seek(0); msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)


class YixiaoerPublishWorker:
    def __init__(self, config, *, store=None, adapter=None):
        self.config=config
        self.store=store or ProviderStore(PlannerStore(config['operations_db']))
        self.adapter=adapter or YixiaoerPublisherAdapter(config,self.store)

    def scope(self):
        allowed=self.config.get('allowed_plan_ids',[])
        mode=self.config.get('execution_mode')
        if mode not in ('CANARY_ONLY','CONFIRMED_PRODUCTION') or not self.config.get('worker_enabled'):
            return []
        with self.store.planner.connect() as db:
            if mode=='CONFIRMED_PRODUCTION' and not production_enabled(db):
                raise PermissionError('YIXIAOER_PRODUCTION_GATE_NOT_OPEN')
            for key in allowed:
                if mode=='CONFIRMED_PRODUCTION':
                    authorization=db.execute('SELECT a.*,p.status,p.employee_id AS plan_employee FROM provider_plan_authorizations a JOIN publish_plans p USING(plan_id) WHERE plan_id=?',(key,)).fetchone()
                    if not authorization or authorization['status']!='CONFIRMED' or authorization['employee_id']!=authorization['plan_employee']:
                        raise PermissionError('USER_CONFIRMED_PROVIDER_PLAN_REQUIRED')
                    wanted=json.loads(authorization['content_ids_json'])
                    items=[r[0] for r in db.execute('SELECT content_id FROM publish_plan_items WHERE plan_id=? ORDER BY scheduled_at',(key,))]
                    count=db.execute('SELECT count(*) FROM provider_publish_jobs WHERE plan_id=?',(key,)).fetchone()[0]
                    if not wanted or len(wanted)!=len(set(wanted)) or items!=wanted or count!=len(wanted):
                        raise PermissionError('PRODUCTION_PLAN_SCOPE_MISMATCH')
                    continue
                canary=db.execute('SELECT content_ids_json FROM yixiaoer_canary_plans WHERE plan_id=?',(key,)).fetchone()
                if not canary or len(set(json.loads(canary[0]))) != 3:
                    raise PermissionError('EXPLICIT_THREE_CONTENT_CANARY_REQUIRED')
                items=db.execute('SELECT content_id FROM publish_plan_items WHERE plan_id=?',(key,)).fetchall()
                if items and (len(items)!=3 or {r[0] for r in items} != set(json.loads(canary[0]))):
                    raise PermissionError('CANARY_SCOPE_MISMATCH')
        return allowed

    def cycle(self):
        plans=self.scope()
        if not plans:
            return {'state':'IDLE_SCOPE_CLOSED','publish_calls':0}
        from .account_registry import exists
        with self.store.planner.connect() as db:
            registry_enabled = exists(db)
        if not registry_enabled:
            self.store.refresh_bindings(self.adapter.clean(self.adapter.list_accounts()))
        # 进程重启后先只读对账已消费闩锁，绝不重新领取/POST。
        with self.store.planner.connect() as db:
            existing=[dict(r) for r in db.execute('SELECT * FROM provider_publish_jobs WHERE plan_id IN ('+','.join('?' for _ in plans)+') AND submit_attempt_count=1',tuple(plans))]
        for row in existing:
            from media_execution.integration import managed_job
            with self.store.planner.connect() as db:
                if managed_job(db,row['job_id']):continue
            if row['provider_task_set_id'] and row['state'] not in ('PUBLISHED','FAILED','CANCELLED'):
                self.adapter.reconcile_publish_result(row['job_id'])
            elif row['state']=='SUBMIT_INTENT':
                self.store.transition(row['job_id'],'SUBMIT_RESULT_UNCERTAIN',{'reason':'RESTART_AFTER_CONSUMED_INTENT_NO_REPOST'})
                self.adapter.reconcile_publish_result(row['job_id'])
            elif row['state']=='SUBMIT_RESULT_UNCERTAIN':
                self.adapter.reconcile_publish_result(row['job_id'])
            if self.store.row(row['job_id'])['state']=='SUBMIT_RESULT_UNCERTAIN':
                return {'state':'NEEDS_RECONCILIATION','job_id':row['job_id'],'reason':'CONSUMED_INTENT_READ_ONLY_NO_NEW_SUBMIT'}
        claimed=self.store.claim(self.config['worker_id'],plans)
        if claimed:
            job_id,token=claimed
            self.adapter.create_publish_job(job_id,token)
            self.adapter.reconcile_publish_result(job_id)
            return {'state':'JOB_PROCESSED','job_id':job_id}
        with self.store.planner.connect() as db:
            rows=[dict(r) for r in db.execute('SELECT * FROM provider_publish_jobs WHERE plan_id IN ('+','.join('?' for _ in plans)+')',tuple(plans))]
            expected=db.execute('SELECT count(*) FROM publish_plan_items WHERE plan_id IN ('+','.join('?' for _ in plans)+')',tuple(plans)).fetchone()[0]
        complete=bool(rows) and len(rows)==expected and all(r['state'] in ('SCHEDULED_QUEUED','PUBLISHED') and r['submit_attempt_count']==1 for r in rows)
        final='PRODUCTION_PROVIDER_QUEUED' if self.config.get('execution_mode')=='CONFIRMED_PRODUCTION' else 'CANARY_PROVIDER_QUEUED'
        return {'state':final if complete else 'WAITING_OR_RECONCILIATION_REQUIRED','job_count':len(rows)}


def interactive_identity(config):
    import ctypes
    import getpass
    session=ctypes.c_ulong()
    if not ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(),ctypes.byref(session)) or session.value==0:
        raise PermissionError('ADMINISTRATOR_INTERACTIVE_SESSION_REQUIRED')
    if getpass.getuser().lower() != 'administrator' or socket.gethostname()!=config['hostname']:
        raise PermissionError('PUBLISH_NODE_IDENTITY_MISMATCH')
    return session.value


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--config',required=True); parser.add_argument('--once',action='store_true'); args=parser.parse_args()
    path=Path(args.config); config=json.loads(path.read_text('utf-8-sig')); session=interactive_identity(config)
    worker=YixiaoerPublishWorker(config)
    runtime=Path(config['runtime_dir'])
    with single_instance(runtime):
        while True:
            config=json.loads(path.read_text('utf-8-sig')); worker.config=config
            if not config['worker_enabled']:
                write_json(runtime/'heartbeat.json',{'worker_id':config['worker_id'],'pid':os.getpid(),'session_id':session,'state':'DISABLED','last_heartbeat':datetime.now(timezone.utc).isoformat()})
                break
            try:
                result=worker.cycle()
            except Exception as error:
                result={'state':'NEEDS_RECONCILIATION','error_code':getattr(error,'code',str(error).split(':')[0])}
            result.update(worker_id=config['worker_id'],pid=os.getpid(),session_id=session,last_heartbeat=datetime.now(timezone.utc).isoformat())
            write_json(runtime/'heartbeat.json',result)
            if result['state'] in ('CANARY_PROVIDER_QUEUED','PRODUCTION_PROVIDER_QUEUED'):
                config['worker_enabled']=False
                write_json(path,config)
                write_json(runtime/('PRODUCTION_PROVIDER_COMPLETE.json' if result['state']=='PRODUCTION_PROVIDER_QUEUED' else 'CANARY_PROVIDER_COMPLETE.json'),result)
                break
            if args.once:
                break
            time.sleep(15)


if __name__=='__main__':
    main()
