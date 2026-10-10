"""服务器唯一业务真相的最小LAN仓库。无桌面控制、不复制operations.db。"""
import argparse
from datetime import datetime,timezone
import hmac
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import logging
from pathlib import Path
import threading
from types import SimpleNamespace

from .lan_publish_contract import *
from .models import PublishStatus,utc_now_iso
from .storage import OperationsStore
from .desktop_worker.resident_monitor import write_json
from .desktop_worker.v04_submit import reserve_once
from publish_planner.storage import PlannerStore
from startup_pipeline.production_dispatch import ProductionDispatcher,ProductionScope
from startup_pipeline.account_binding import guard_publish_job
from startup_render.lan_protocol import token_from
from startup_render.common import digest


class Repository:
    def __init__(self,config,*,dispatcher=None):
        self.config=config
        self.root=Path(config['runtime_dir']);self.root.mkdir(parents=True,exist_ok=True)
        self.store=PlannerStore(config['operations_db'])
        if not self.store.path.is_file():raise RuntimeError('OPERATIONS_DB_NOT_FOUND')
        self.dispatcher=dispatcher or ProductionDispatcher(self.store)
        self.capabilities=set();self.lock=threading.RLock()

    def off(self):
        if json.loads(Path(self.config['adapter_config']).read_text('utf-8')).get('real_publish_enabled') is not False:
            raise PermissionError('GLOBAL_PUBLISH_SWITCH_MUST_STAY_OFF')

    def owned(self,value):
        if value.get('job_id')!=JOB_ID:raise PermissionError('JOB3_ONLY')
        with self.store.connect() as db:
            row=db.execute('SELECT * FROM startup_production_dispatch WHERE job_id=?',(JOB_ID,)).fetchone()
            if (not row or row['plan_id']!=PLAN_ID or row['worker_id']!=WORKER_ID
                or not value.get('claim_token') or row['claim_token']!=value['claim_token']):
                raise PermissionError('PRODUCTION_CLAIM_REQUIRED')
            guard_publish_job(db,JOB_ID)
        return dict(row)

    def context(self,*,claimed=False):
        self.off()
        with self.store.connect() as db:
            policy=self.dispatcher._context(db,JOB_ID,claimed=claimed)
        return check_policy(policy)

    def handle(self,route,value):
        self.off()
        if value.get('worker_id')!=WORKER_ID:raise PermissionError('WORKER_ID_MISMATCH')
        with self.lock:
            if route=='/publish/heartbeat':
                keys=('hostname','ip','windows_user','session_id','status','current_job_id','xiaovcat_process_present',
                      'render_worker_status','last_heartbeat','pid','real_submit_armed','dry_run_mode')
                if (value.get('hostname')!=HOSTNAME or value.get('windows_user')!='DESKTOP-9VQ76D3\\sdaffwS'
                    or value.get('current_job_id') not in {None,JOB_ID}):raise PermissionError('WORKER_IDENTITY_MISMATCH')
                beat={k:value.get(k) for k in keys}
                beat.update(worker_id=WORKER_ID,received_at=utc_now_iso(),real_publish_enabled=False)
                write_json(self.root/'worker_heartbeat.json',beat);return {'accepted':True}
            if route=='/publish/jobs':
                from .local_worker_queue import LocalWorkerQueue
                q=LocalWorkerQueue(self.dispatcher,dict(allowed_plan_ids=[PLAN_ID],allowed_job_ids=[JOB_ID]),lambda:None)
                row=q.row(JOB_ID);job=q.context_preview(row);check_policy(job)
                job.update(q.submission(JOB_ID),dispatch_state=row['state'],video_sha256=digest(job['video_path']),
                    source_unc=self.config['job3_video_unc'],expected_group_id=GROUP_ID,expected_account_ids=sorted(ACCOUNT_IDS))
                check_policy(job)
                return {'jobs':[job] if row['state']=='QUEUED' and job['submit_attempt_count']==0 else [],
                        'submit_attempt_count':job['submit_attempt_count'],'dispatch_state':row['state']}
            if route=='/publish/snapshot':
                from .group_sync import persist_group_snapshot
                from startup_pipeline.selector_refresh import _SnapshotWriter
                repo=self
                with self.store.connect() as db:
                    employee=db.execute('SELECT employee_id FROM startup_job_metadata WHERE job_id=?',(JOB_ID,)).fetchone()[0]
                class BoundActor:
                    def connect(self,**kwargs):return repo.store.connect(**kwargs)
                    def _principal(self,db,token):
                        if token is not self:raise PermissionError('WORKER_SCOPE_DENIED')
                        actor=db.execute('SELECT * FROM employees WHERE employee_id=? AND enabled=1',(employee,)).fetchone()
                        if not actor:raise PermissionError('EMPLOYEE_DISABLED')
                        return actor
                bound=BoundActor()
                return persist_group_snapshot(_SnapshotWriter(bound,bound,GROUP_ID,ACCOUNT_IDS),bound,value['snapshot'],GROUP_ID,ACCOUNT_IDS)
            if route=='/publish/context':
                if value.get('job_id')!=JOB_ID:raise PermissionError('JOB3_ONLY')
                if value.get('claim_token'):self.owned(value)
                return self.context(claimed=bool(value.get('claim_token')))
            if route=='/publish/claim':
                if value.get('job_id')!=JOB_ID:raise PermissionError('JOB3_ONLY')
                if value.get('user_confirmation')!=USER_CONFIRMATION:
                    raise PermissionError('USER_ONE_SHOT_REQUIRED')
                self.context()
                with self.store.connect(write=True) as db:
                    nonce=self.dispatcher._claim_in_transaction(db,PLAN_ID,JOB_ID,WORKER_ID)
                self.capabilities.add(nonce)
                return {'claim_token':nonce,'policy':self.context(claimed=True)}
            if route=='/publish/dry-verified':
                self.context()
                proof=value['proof']
                if not proof.get('all_checks_passed') or proof.get('status')!='READY_FOR_SINGLE_SUBMIT':
                    raise PermissionError('FORM_NOT_VERIFIED')
                check_policy(proof)
                write_json(self.root/'JOB3_LOCAL_UI_DRY_RUN.json',dict(proof=proof,received_at=utc_now_iso(),submit_count=0))
                return {'accepted':True,'submit_count':0}
            row=self.owned(value)
            nonce=row['claim_token']
            if route=='/publish/guard':return {'guarded':True}
            if route=='/publish/job':
                with self.store.connect() as db:
                    return dict(db.execute('SELECT * FROM publish_jobs WHERE job_id=?',(JOB_ID,)).fetchone())
            if route=='/publish/prepare-verified':
                self.context(claimed=True)
                with self.store.connect(write=True) as db:
                    db.execute("UPDATE publish_jobs SET status='DRY_RUN_READY',current_step='PRE_SUBMIT_VERIFIED',updated_at=? WHERE job_id=?",(utc_now_iso(),JOB_ID))
                return {'prepared':True}
            if route=='/publish/reserve':
                if nonce not in self.capabilities:raise PermissionError('SINGLE_CAPABILITY_NOT_ARMED')
                self.capabilities.remove(nonce)  # 网络失联/崩溃不能重取这次提交许可。
                scope=ProductionScope(self.dispatcher,JOB_ID,nonce,self.root)
                reserve_once(OperationsStore(self.store.path),JOB_ID,scope)
                return {'attempt_committed':True,'submit_attempt_count':1}
            if route=='/publish/unknown':
                with self.store.connect() as db:
                    if db.execute('SELECT count(*) FROM state_events WHERE job_id=? AND step=?',(JOB_ID,'V04_FINAL_SUBMIT_RESERVED')).fetchone()[0]!=1:
                        raise PermissionError('DURABLE_ATTEMPT_REQUIRED')
                OperationsStore(self.store.path).update_job(JOB_ID,status=PublishStatus.NEEDS_MANUAL,
                    current_step='UNKNOWN_AFTER_SUBMIT',error_code='PENDING_UI_OUTCOME_VERIFICATION',error_message='At most one final invocation; no retry.')
                return {'recorded':True}
            if route=='/publish/result':
                proof=value['proof']
                if proof.get('verified'):
                    return self.dispatcher.record_scheduled_success(JOB_ID,nonce,proof,allow_reconciliation=True)
                return {'state':self.dispatcher.block(JOB_ID,'SUBMIT_RESULT_UNCERTAIN')}
            if route=='/publish/disarm':
                self.capabilities.discard(nonce);return {'real_submit_armed':False,'real_publish_enabled':False}
            raise ValueError('UNKNOWN_ROUTE')


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if (self.client_address[0] not in self.server.allowed_clients or
            not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+self.server.token)):
            return self.reply({'error':'FORBIDDEN'},403)
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=2*1024*1024 or self.headers.get('Content-Type')!='application/json':
                raise ValueError('JSON_BODY_REQUIRED')
            value=json.loads(self.rfile.read(length))
            result=self.server.repository.handle(self.path,value)
            self.reply(result)
        except Exception as error:
            from xiaovcat_publish_worker import safe_code
            self.reply({'error':safe_code(error)},400)
    def reply(self,value,status=200):
        data=json.dumps(value,ensure_ascii=False).encode('utf-8')
        self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def log_message(self,fmt,*args):logging.info('%s %s',self.client_address[0],fmt%args)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);args=parser.parse_args()
    config=json.loads(Path(args.config).read_text('utf-8'))
    repo=Repository(config)
    render=json.loads(Path(config['render_server_config']).read_text('utf-8'))
    server=ThreadingHTTPServer((config['bind'],config['port']),Handler)
    server.repository=repo;server.token=token_from(render);server.allowed_clients=['192.168.1.89']
    logging.basicConfig(filename=repo.root/'lan_publish_server.log',level=logging.INFO)
    server.serve_forever()


if __name__=='__main__':main()
