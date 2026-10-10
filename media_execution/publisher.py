"""2060侧复用正式CLI Adapter；账本通过Server接口访问，不共享SQLite文件。"""
import json
import socket
import time
from pathlib import Path

from yixiaoer_adapter.publisher import YixiaoerPublisherAdapter, ProviderError
from .network import require_runtime_network


class ExecutionProviderStore:
    """适配既有Provider协议；Server仍持有闩锁，Worker缓存不具备授权能力。"""
    def __init__(self, job, context, contract):
        self.job,self.context = job,context
        self.value = dict(contract,job_id=job['job_id'],claim_token=job['lease_token'],state='UPLOADING',
                          submit_attempt_count=0,intent_json=None,provider_task_set_id=None,
                          provider_task_id=None,provider_video_id=None,provider_video_url=None)

    def row(self, job_id):
        if job_id!=self.job['job_id']:
            raise PermissionError('CLAIMED_JOB_REQUIRED')
        return dict(self.value)

    def refresh_bindings(self, accounts):
        # 仅回报查询结果，不能在Worker决定解除AccountPublishGate。
        self.accounts = accounts

    def transition(self, job_id, state, evidence=None, **fields):
        self.row(job_id)
        self.value.update(fields,state=state)
        if state=='PROVIDER_VALIDATED':
            self.context.stage(state)
        self.context.coordinator.journal(self.job,state,provider_evidence=evidence,provider_fields=fields)

    def reserve_submit(self, job_id, token, intent):
        self.row(job_id)
        if token!=self.job['lease_token'] or self.value['submit_attempt_count']:
            raise PermissionError('SUBMIT_ONCE_LATCH_CONSUMED')
        self.context.reserve_submit(intent)
        self.value.update(state='SUBMIT_INTENT',submit_attempt_count=1,intent_json=json.dumps(intent))


class WorkstationAdapter(YixiaoerPublisherAdapter):
    def __init__(self, config, store, context, network_check, *, runner=None):
        super().__init__(config,store,runner=runner)
        self.context,self.network_check = context,network_check

    def validate_account_mapping(self, job):
        frozen = self.context.job['payload']
        if (job['business_account_id']!=self.context.job['business_account_id'] or
                job['provider_account_id']!=frozen['provider_account_id']):
            raise ProviderError('YIXIAOER_ACCOUNT_MAPPING_CONFLICT')
        self.context.assert_live()

    def call(self, args, **kwargs):
        if args and args[0]=='upload':
            self.network_check()
            self.context.stage('PROVIDER_UPLOADING')
        elif args and args[0]=='publish' and '--dry-run' not in args:
            self.network_check()
            self.context.stage('PROVIDER_SUBMITTING')
        else:
            self.context.assert_live()
        return super().call(args,**kwargs)


class WorkstationPublisher:
    def __init__(self, config, *, network_check=None, runner=None):
        self.config,self.runner = config,runner
        self.network_check = network_check or require_runtime_network

    def wait_for_client(self, adapter, job, context):
        # 只在平台明确报告仍执行上传/提交时等待；已有作品ID后的公开等待立即脱离重槽。
        deadline=time.monotonic()+120
        observed=adapter.reconcile_publish_result(job['job_id'])
        while (observed.get('state')=='SUBMITTED' and not observed.get('task',{}).get('publishId')
               and observed.get('task',{}).get('stages') in ('upload','push','publish')
               and observed.get('task',{}).get('stageStatus') in ('doing','running','processing')):
            if time.monotonic()>=deadline: raise ProviderError('PUBLISH_STAGE_TIMEOUT_QUERY_ONLY_REQUIRED')
            context.assert_live()
            time.sleep(min(10,max(0,self.config.get('provider_poll_seconds',10))))
            observed=adapter.reconcile_publish_result(job['job_id'])
        return observed

    def __call__(self, job, context):
        if self.config.get('provider_execution_role')!='WORKSTATION' or socket.gethostname().casefold()!=self.config.get('expected_hostname','').casefold():
            raise PermissionError('FORMAL_PUBLISH_NETWORK_NODE_REQUIRED')
        self.network_check()
        # Input只从Server取得；不在2060选择账号/排期/条数，也不复制视频给Server。
        contract = context.coordinator.control.publish_input(job['worker_id'],job['lease_token'])
        root = self.config.get('local_jobs_root')
        if not root or str(contract['video_path']).startswith(('\\\\','//')) or not Path(contract['video_path']).resolve().is_relative_to(Path(root).resolve()):
            raise PermissionError('WORKER_LOCAL_OUTPUT_REQUIRED')
        store = ExecutionProviderStore(job,context,contract)
        adapter = WorkstationAdapter(self.config,store,context,self.network_check,runner=self.runner)
        task_set = adapter.create_publish_job(job['job_id'],job['lease_token'])
        context.stage('PUBLISH_RECONCILING')
        observed = self.wait_for_client(adapter,job,context)
        current = store.row(job['job_id'])
        # 已有明确终态回执时保存Task IDs和失败证据，不能丢成“提交结果未知”。
        return {'state':'FAILED_JOB_LEVEL' if observed.get('state')=='FAILED' else observed.get('state','SUBMITTED'),'provider_task_id':current['provider_task_id'] or task_set,
                'provider_task_set_id':task_set,'provider_video_id':current['provider_video_id'],
                'provider_response':json.loads(current.get('provider_raw_status') or '{}')}

    def reconcile(self, job, context):
        contract = context.coordinator.control.publish_input(job['worker_id'],job['lease_token'])
        if contract.get('submit_attempt_count')!=1:
            raise PermissionError('CONSUMED_INTENT_REQUIRED')
        store = ExecutionProviderStore(job,context,contract)
        store.value.update(contract)
        class ReadOnlyAdapter(WorkstationAdapter):
            def call(inner, args, **kwargs):
                if not args or args[:2] not in (['query','details'],['query','records']):
                    raise PermissionError('RECONCILIATION_QUERY_ONLY')
                kwargs['timeout']=min(kwargs.get('timeout',30),30)
                return super().call(args,**kwargs)
        adapter = ReadOnlyAdapter(dict(self.config,command_timeout=30),store,context,self.network_check,runner=self.runner)
        observed = adapter.reconcile_publish_result(job['job_id'])
        current = store.row(job['job_id'])
        return {'state':'FAILED_JOB_LEVEL' if observed['state']=='FAILED' else observed['state'],
                'provider_task_id':current.get('provider_task_id'),'provider_task_set_id':current.get('provider_task_set_id'),
                'provider_video_id':current.get('provider_video_id'),'provider_response':observed}
