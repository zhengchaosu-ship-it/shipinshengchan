"""2060唯一执行循环；Server决定候选，Worker只执行并持久回报。"""
import json
import os
from pathlib import Path
import threading
import time

from .locking import LaneBusy, media_lock


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary = path.with_suffix(path.suffix+'.tmp')
    with temporary.open('w',encoding='utf-8') as target:
        json.dump(value,target,ensure_ascii=False,indent=2)
        target.flush()
        os.fsync(target.fileno())
    os.replace(temporary,path)


class ExecutionFailure(RuntimeError):
    def __init__(self, domain, reason, *, gate=None, evidence=None):
        super().__init__(reason)
        self.domain,self.reason,self.gate,self.evidence = domain,reason,gate,evidence


def classify_failure(error):
    if isinstance(error,ExecutionFailure):
        return error
    evidence = getattr(error,'evidence',None)
    text = str(error)+' '+json.dumps(evidence or {},ensure_ascii=False)
    # 平台错误正文优先于CLI通用退出码，避免将单账号验证误判为全站不可用。
    if any(word in text for word in ('ACCOUNT_RISK','账号存在风险','账号风险')):
        return ExecutionFailure('ACCOUNT_LEVEL','ACCOUNT_RISK',gate='BLOCKED_RISK',evidence=evidence)
    if any(word in text for word in ('SMS_REQUIRED','MANUAL_PUBLISH_REQUIRED','CREATOR_CENTER_VERIFICATION_REQUIRED',
                                     'ACCOUNT_VERIFICATION_REQUIRED','ACCOUNT_PROVIDER_BLOCKED','AUTH_REQUIRED','MANUAL_ACTION_REQUIRED',
                                     '短信验证','人工验证','创作者中心','发布验证')):
        return ExecutionFailure('ACCOUNT_LEVEL','MANUAL_PUBLISH_REQUIRED',gate='BLOCKED_MANUAL_ACTION',evidence=evidence)
    if any(word in text for word in ('AUTH_EXPIRED','ACCOUNT_NOT_ONLINE','ACCOUNT_OFFLINE','授权过期','登录失效','账号失效')):
        return ExecutionFailure('ACCOUNT_LEVEL','AUTH_EXPIRED',gate='BLOCKED_AUTH',evidence=evidence)
    if any(word in text for word in ('PUBLISH_NETWORK_ATTENTION','LOCAL_EXECUTOR_OFFLINE','DATABASE_UNAVAILABLE','EXECUTION_COORDINATOR_BROKEN','FORMAL_PUBLISH_NETWORK_NODE_REQUIRED')):
        return ExecutionFailure('INFRA_LEVEL','PUBLISH_NETWORK_ATTENTION' if 'PUBLISH_NETWORK_ATTENTION' in text else 'PUBLISHER_UNAVAILABLE',evidence=evidence)
    if isinstance(error,OSError) and getattr(error,'errno',None)==28:
        return ExecutionFailure('INFRA_LEVEL','EXECUTOR_IO_FAILURE',evidence={'error':str(error)})
    return ExecutionFailure('JOB_LEVEL',str(error),evidence=evidence)


class ExecutionContext:
    def __init__(self, coordinator, job, lost):
        self.coordinator,self.job,self.lost = coordinator,job,lost

    def assert_live(self):
        if self.lost.is_set():
            raise ExecutionFailure('INFRA_LEVEL','EXECUTION_LEASE_HEARTBEAT_LOST')
        self.coordinator.control.heartbeat(self.job['worker_id'],self.job['lease_token'])

    def stage(self, stage):
        self.assert_live()
        self.coordinator.control.stage(self.job['worker_id'],self.job['lease_token'],stage)
        self.coordinator.journal(self.job,stage)

    def reserve_submit(self, intent):
        self.assert_live()
        # 先写本地意图，再请求Server闩锁；任何响应不明确均退出，不能重试POST。
        self.coordinator.journal(self.job,'SUBMIT_INTENT_REQUESTED',intent=intent)
        result = self.coordinator.control.reserve_submit(self.job['worker_id'],self.job['lease_token'],intent)
        if not result.get('submit_reserved'):
            raise ExecutionFailure('INFRA_LEVEL','SUBMIT_RESERVATION_UNCONFIRMED')
        self.coordinator.journal(self.job,'SUBMIT_INTENT',intent=intent)


class MediaExecutionCoordinator:
    def __init__(self, control, worker_id, journal_path, *, render, publish,
                 recover_render, executor_quiescent, heartbeat_seconds=20, reconcile=None, workstation_available=None,
                 execution_state=None):
        if not 0 < heartbeat_seconds < 60:
            raise ValueError('INVALID_HEARTBEAT_INTERVAL')
        self.control,self.worker_id,self.journal_path = control,worker_id,Path(journal_path)
        self.render,self.publish,self.recover_render = render,publish,recover_render
        self.executor_quiescent = executor_quiescent
        self.workstation_available = workstation_available or (lambda:True)
        self.execution_state = execution_state or (lambda busy:None)
        self.reconcile = reconcile
        self.heartbeat_seconds = heartbeat_seconds

    def journal(self, job, stage, **details):
        atomic_json(self.journal_path,{k:job[k] for k in ('worker_id','job_type','job_id','lease_token')} |
                    {'stage':stage,'updated_at':time.time(),**details})

    def _heartbeat(self, job, stop, lost):
        while not stop.wait(self.heartbeat_seconds):
            try:
                self.control.heartbeat(job['worker_id'],job['lease_token'])
            except Exception:
                lost.set()
                return

    def run_once(self):
        try:
            with media_lock():
                # 锁内再次采样，覆盖上一心跳之后人工打开剪映的情况。
                if not self.workstation_available():
                    return {'state':'WAITING_FOR_WORKSTATION'}
                # 网络失效/旧子进程残留时不释放旧Server lease，不领取下一项。
                prior = json.loads(self.journal_path.read_text('utf-8')) if self.journal_path.exists() else None
                recovered = self.control.recovery(self.worker_id,
                    executor_quiescent=self.executor_quiescent(),journal=prior)
                if recovered and recovered['state']=='SUBMIT_RESULT_UNCERTAIN':
                    atomic_json(self.journal_path,recovered)
                    return recovered
                if not (recovered and recovered.get('recover_render')):
                    # 领取响应丢失时没有当前lease token；空journal让Server恢复其唯一租约。
                    atomic_json(self.journal_path,{})
                if not self.workstation_available():
                    return {'state':'WAITING_FOR_WORKSTATION'}
                job = recovered if recovered and recovered.get('recover_render') else self.control.claim(self.worker_id)
                if not job:
                    return {'state':'IDLE'}
                return self._execute(job)
        except LaneBusy:
            return {'state':'WAITING_FOR_WORKSTATION'}

    def reconcile_once(self):
        """单次只读查询：不持重槽、Mutex或busy，不改提交/渲染journal。"""
        if not self.reconcile: return None
        job = self.control.claim_reconciliation(self.worker_id)
        if not job: return None
        coordinator = self
        class QueryContext:
            def __init__(self):
                self.job=job
                self.coordinator=type('QueryCoordinator',(),{'control':coordinator.control,'journal':staticmethod(lambda *a,**k:None)})()
            def assert_live(self): coordinator.control.heartbeat(job['worker_id'],job['lease_token'])
            def stage(self,*args): raise PermissionError('QUERY_ONLY_NO_HEAVY_STAGE')
            def reserve_submit(self,*args): raise PermissionError('QUERY_ONLY_NO_SUBMIT')
        try:
            result = self.reconcile(job,QueryContext())
            self.control.record_reconciliation(job['worker_id'],job['lease_token'],result)
            return result
        except Exception as error:
            self.control.reconciliation_error(job['worker_id'],job['lease_token'],type(error).__name__+':'+str(error))
            return {'state':'RECONCILIATION_WAIT','job_id':job['job_id']}

    def _execute(self, job):
        stop,lost = threading.Event(),threading.Event()
        thread = threading.Thread(target=self._heartbeat,args=(job,stop,lost),daemon=True)
        context = ExecutionContext(self,job,lost)
        self.journal(job,job['state'])
        thread.start()
        try:
            self.execution_state(True)
            if job.get('reconcile_only'):
                result = self.reconcile(job,context)
                context.assert_live()
                self.control.record_reconciliation(job['worker_id'],job['lease_token'],result)
                state = result['state']
            elif job['job_type']=='RENDER':
                executor = self.recover_render if job.get('recover_render') else self.render
                result = executor(job,context)
                context.stage('OUTPUT_VERIFYING')
                self.control.complete_render(job['worker_id'],job['lease_token'],result)
                state = 'COMPLETED'
            else:
                result = self.publish(job,context)
                context.assert_live()
                self.control.complete_publish(job['worker_id'],job['lease_token'],result)
                state = result['state']
            self.journal(job,state,receipt=result)
            return {'state':state,'job_id':job['job_id'],'job_type':job['job_type']}
        except Exception as error:
            failure = classify_failure(error)
            # executor必须同步收割子进程；无法证明已停止时保留租约并阻止后续重任务。
            if not self.executor_quiescent():
                self.journal(job,'EXECUTOR_NOT_QUIESCENT',error=str(error))
                raise ExecutionFailure('INFRA_LEVEL','OLD_EXECUTOR_QUIESCENCE_REQUIRED') from error
            state = self.control.fail(job['worker_id'],job['lease_token'],failure.domain,failure.reason,
                                      gate=failure.gate,evidence=failure.evidence)
            self.journal(job,state,error=failure.reason)
            return {'state':state,'job_id':job['job_id'],'job_type':job['job_type']}
        finally:
            stop.set()
            thread.join(timeout=self.heartbeat_seconds+1)
            self.execution_state(False)
