"""独立本机Publish Worker。默认Dry Run只观察正式字段，绝不执行桌面输入。"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import socket
import threading

ROOT=Path(__file__).resolve().parent


def validate_config(config):
    for key in ('worker_enabled','dry_run_mode','real_submit_armed'):
        if type(config.get(key)) is not bool:raise ValueError('WORKER_CONFIG_INVALID:'+key)
    if config['dry_run_mode'] and config['real_submit_armed']:
        raise PermissionError('DRY_RUN_CANNOT_ARM_REAL_SUBMIT')
    for key in ('allowed_plan_ids','allowed_job_ids'):
        production = config.get('execution_site')=='SERVER_ONLY' and config.get('authorization_mode')=='CONFIRMED_PRODUCTION'
        if not isinstance(config.get(key),list) or (not config[key] and not production) or len(set(config[key]))!=len(config[key]):
            raise ValueError('EXPLICIT_UNIQUE_SCOPE_REQUIRED:'+key)
    for key in ('worker_id','hostname','windows_user_sid','operations_db','runtime_dir','xiaovcat_executable'):
        if not config.get(key):raise ValueError('WORKER_CONFIG_INVALID:'+key)
    return config


def load_config(path):
    return validate_config(json.loads(Path(path).read_text('utf-8')))


def safe_code(error):
    # 日志不写原始异常/凭证，不包含token、密码或命令行。
    match=re.match(r'[A-Z][A-Z0-9_]+',str(error))
    return match.group() if match else 'LOCAL_WORKER_ERROR'


@contextmanager
def single_instance(runtime):
    from xiaovcat_adapter.desktop_worker.resident_monitor import instance_lock
    from xiaovcat_adapter.desktop_worker.production_worker import worker_lock
    try:
        with instance_lock(Path(runtime)/'executor.lock'),worker_lock():
            yield
    except RuntimeError as error:
        if str(error) in {'OTHER_RESIDENT_WORKER_ACTIVE','OTHER_WORKER_ACTIVE'}:
            raise RuntimeError('WORKER_ALREADY_RUNNING') from error
        raise


class PublishWorker:
    def __init__(self, config, queue, *, publisher_factory=None, session_check=None, config_path=None, one_shot=False):
        self.config=validate_config(config)
        self.queue,self.config_path=queue,config_path
        if one_shot and config_path is not None:
            raise PermissionError('ONE_SHOT_MEMORY_AUTHORITY_ONLY')
        self.one_shot=one_shot
        if session_check is None:
            from xiaovcat_adapter.local_session import check_session
            session_check=check_session
        self.session_check=session_check
        if publisher_factory is None:
            from xiaovcat_adapter.local_ui_publisher import XiaovcatLocalUiPublisher
            publisher_factory=XiaovcatLocalUiPublisher
        self.publisher_factory=publisher_factory
        self.runtime=Path(config['runtime_dir']);self.runtime.mkdir(parents=True,exist_ok=True)
        self.status='IDLE';self.current_job_id=None;self.failure_code=None;self.presence={}
        self.stop=threading.Event()
        self.heartbeat_lock=threading.Lock()

    def refresh_config(self):
        if self.config_path:
            new=load_config(self.config_path)
            # 身份、DB、运行范围变更必须停进程再重启，不允许热切到其它计划。
            for key in ('allowed_plan_ids','allowed_job_ids','worker_id','windows_user_sid','hostname','operations_db','runtime_dir','xiaovcat_executable'):
                if new[key]!=self.config[key]:raise PermissionError('WORKER_IDENTITY_OR_SCOPE_CHANGED_RESTART_REQUIRED')
            self.config=new;self.queue.config=new

    def global_off(self):
        config=json.loads((ROOT/'xiaovcat_adapter/config.json').read_text('utf-8'))
        if config.get('real_publish_enabled') is not False:
            raise PermissionError('GLOBAL_PUBLISH_SWITCH_MUST_STAY_OFF')

    def authority(self):
        self.refresh_config();self.global_off()
        self.presence=self.session_check(self.config)
        return self.presence

    def armed(self):
        self.authority()
        if self.config.get('production_execution_authorized') and self.config['worker_enabled']:
            # Confirm允许准备；真实武装只能由持久化reserve后的回调授予。
            return
        if not self.config['worker_enabled'] or self.config['dry_run_mode'] or not self.config['real_submit_armed']:
            raise PermissionError('ARMED_REQUIRED')

    def grant_reserved_submit_permission(self):
        self.authority()
        row=self.queue.row(self.current_job_id)
        if (self.status!='SUBMITTING' or not self.config.get('production_execution_authorized')
            or not self.config['worker_enabled'] or not self.queue.allowed(row)
            or row['state']!='CLAIMED' or row['worker_id']!=self.config['worker_id']
            or self.queue.submission(self.current_job_id)['submit_attempt_count']!=1):
            raise PermissionError('DURABLE_SINGLE_JOB_SUBMIT_AUTHORITY_REQUIRED')
        self.config.update(dry_run_mode=False,real_submit_armed=True)
        self.heartbeat()

    def revoke_submit_permission(self):
        # 一次性入口只使用内存授权；磁盘上的常驻配置始终未武装。
        self.config.update(dry_run_mode=True,real_submit_armed=False)
        self.queue.config=self.config
        self.global_off()
        self.heartbeat()

    def heartbeat(self):
        with self.heartbeat_lock:
            self._heartbeat()

    def _heartbeat(self):
        from xiaovcat_adapter.desktop_worker.resident_monitor import write_json
        write_json(self.runtime/'heartbeat.json',dict(worker_id=self.config['worker_id'],hostname=socket.gethostname(),
            pid=os.getpid(),session_id=self.presence.get('session_id'),status=self.status,current_job_id=self.current_job_id,
            last_heartbeat=datetime.now(timezone.utc).isoformat(),xiaovcat_process_present=self.presence.get('xiaovcat_process_present',False),
            interactive_session_present=self.presence.get('interactive_session_present',False),
            dry_run_mode=self.config['dry_run_mode'],real_submit_armed=self.config['real_submit_armed'],
            real_publish_enabled=False,failure_code=self.failure_code))

    def stage(self, state):
        self.status=state
        self.queue.stage(self.current_job_id,state)
        self.heartbeat()

    def run_once(self):
        from xiaovcat_adapter.desktop_worker.resident_monitor import write_json
        self.current_job_id=None;self.failure_code=None
        self.authority()
        rows=self.queue.discover()
        if not self.config['worker_enabled']:
            self.status='DISABLED';self.heartbeat();return {'status':self.status}
        if (self.config['dry_run_mode'] or not self.config['real_submit_armed']) and not self.config.get('production_execution_authorized'):
            # 初始部署Dry Run不claim、不调用Publisher/UIA、不修改正式Job。
            data=[self.queue.context_preview(row) for row in rows]
            self.status='ARMED_REQUIRED' if rows else 'IDLE'
            result=dict(status=self.status,mode='FORM_DATA_DRY_RUN_NO_UI',jobs=data,claim_count=0,
                        final_submit_invocations=0,real_publish_enabled=False)
            write_json(self.runtime/'DRY_RUN.json',result);self.heartbeat();return result
        if not rows:
            self.status='IDLE';self.heartbeat();return {'status':'IDLE'}
        row=rows[0];self.current_job_id=row['job_id']
        results=self.runtime/'jobs'/row['job_id']
        results.mkdir(parents=True,exist_ok=True)
        try:
            submission=self.queue.submission(row['job_id'])
            if submission['submit_attempt_count']:
                # 重启恢复只查结果，绝不再prepare/claim/submit。
                if row['worker_id']!=self.config['worker_id'] or not row['claim_token']:
                    raise PermissionError('OTHER_WORKER_CLAIM_NO_TAKEOVER')
                from types import SimpleNamespace
                scope=SimpleNamespace(policy=json.loads(row['context_json']),results=results,job_id=row['job_id'],capture_screenshots=False)
                publisher=self.publisher_factory(scope,armed_check=self.armed)
            elif row['state']=='CLAIMED':
                raise RuntimeError('INTERRUPTED_PRE_SUBMIT_NO_WRITE_REPLAY')
            elif row['state']!='QUEUED':
                raise RuntimeError('SUBMIT_RESULT_UNCERTAIN')
            else:
                try:nonce=self.queue.claim(row)
                except PermissionError as error:
                    if str(error)!='PUBLISH_ACCOUNT_SNAPSHOT_EXPIRED':raise
                    self.queue.refresh_snapshot(row,results/'account_refresh')
                    nonce=self.queue.claim(row)  # 最多刷新1次，不重放控件写入。
                row=self.queue.row(row['job_id'])
                scope=self.queue.scope(row,nonce,results)
                if self.one_shot:
                    scope.on_submit_permission_revoked=self.revoke_submit_permission
                if self.config.get('production_execution_authorized'):
                    scope.on_reserved_submit_permission=self.grant_reserved_submit_permission
                publisher=self.publisher_factory(scope,armed_check=self.armed)
                self.stage('PREPARING');publisher.prepare_job()
                self.stage('FORM_READY');publisher.verify_form();self.stage('FORM_VERIFIED')
                self.armed();self.stage('SUBMITTING')
                try:
                    submitted=publisher.submit_once()
                finally:
                    if self.one_shot:self.revoke_submit_permission()
                self.queue.returned(row['job_id'],submitted)
                submission={**self.queue.submission(row['job_id']),**submitted}
                if submitted.get('invoke_returned'):self.stage('TASK_CREATED')
            path=results/'SUBMIT_RESULT.json'
            if path.exists():
                recorded=json.loads(path.read_text('utf-8'))
                if recorded.get('invocation_local_time'):
                    submission['invocation_local_time']=recorded['invocation_local_time']
            self.stage('VERIFYING')
            proof=publisher.reconcile_result(submission)
            if proof.get('verified') is not True:
                raise RuntimeError(proof['status'])
            self.queue.success(row,proof)
            self.stage('SCHEDULED_QUEUED')
            write_json(results/'RESULT.json',proof)
            self.status='IDLE';self.current_job_id=None;self.heartbeat()
            return proof
        except Exception as error:
            code=safe_code(error)
            # 已有reserve必转未知；失败不吞掉，也不自动重领。前置claim失败留QUEUED不消费其它。
            actual=self.queue.row(row['job_id'])
            if actual['worker_id']==self.config['worker_id'] and actual['state']!='SCHEDULED_QUEUED':
                self.queue.dispatcher.block(row['job_id'],code)
            self.status='HALTED_NEEDS_MANUAL';self.failure_code=code;self.heartbeat()
            logging.error('job_id=%s failure_code=%s',row['job_id'],code)
            self.stop.set()  # 未知/失败不继续下一条，不自动重放。
            return dict(status=self.status,failure_code=code,real_publish_enabled=False)
        finally:
            if self.one_shot:self.revoke_submit_permission()
            self.global_off()

    def heartbeat_loop(self):
        while not self.stop.wait(25):self.heartbeat()

    def run_forever(self):
        beat=threading.Thread(target=self.heartbeat_loop,daemon=True);beat.start()
        try:
            while not self.stop.is_set() and not (self.runtime/'STOP_WORKER').exists():
                self.run_once()
                self.stop.wait(25)
        finally:
            self.stop.set();beat.join(timeout=2)
            self.global_off()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--once',action='store_true')
    args=parser.parse_args();config=load_config(args.config)
    runtime=Path(config['runtime_dir']);runtime.mkdir(parents=True,exist_ok=True)
    handler=RotatingFileHandler(runtime/'worker.log',maxBytes=1024*1024,backupCount=3,encoding='utf-8')
    logging.basicConfig(level=logging.INFO,handlers=[handler],format='%(asctime)s %(levelname)s %(message)s')
    from publish_planner.storage import PlannerStore
    if config.get('execution_site') == 'SERVER_ONLY':
        from xiaovcat_adapter.server_resident import run_server
        run_server(args.config, once=args.once)
        return
    from startup_pipeline.production_dispatch import ProductionDispatcher
    from xiaovcat_adapter.local_worker_queue import LocalWorkerQueue
    queue=LocalWorkerQueue(ProductionDispatcher(PlannerStore(config['operations_db'])),config,lambda:worker.authority())
    worker=PublishWorker(config,queue,config_path=args.config)
    try:
        with single_instance(runtime):
            worker.run_once() if args.once else worker.run_forever()
    except Exception as error:
        code=safe_code(error)
        if code!='WORKER_ALREADY_RUNNING':
            worker.status='HALTED_NEEDS_MANUAL';worker.failure_code=code;worker.heartbeat()
        logging.error('failure_code=%s',code)
        raise SystemExit(1) from None


if __name__=='__main__':main()
