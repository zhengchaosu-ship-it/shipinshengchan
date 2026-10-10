"""复用现有Agent执行已签发草稿；MP4保留2060，本轮回执不等待归档。"""
from contextlib import contextmanager
import io
from pathlib import Path
import shutil
import time

from startup_render.agent import Agent
from .coordinator import ExecutionFailure
from .verification import verify_local_output


class LocalOutputTransport:
    def __init__(self, original, context):
        self.original,self.context,self.receipt = original,context,None

    def download(self, manifest, folder):
        self.context.assert_live()
        if Path(folder).exists() and self.context.job.get('recover_render'):
            # 中断的传输目录保留作证据；原Transport逐文件复核SHA并复用素材缓存。
            Path(folder).rename(Path(folder).with_name('package.interrupted.'+str(time.time_ns())))
        return self.original.download(manifest,folder)

    def output_path(self, manifest):
        return self.original.output_path(manifest)

    def upload(self, state, output, media):
        # 名称沿用Agent协议，但此实现仅返回本机位置，不执行SMB回传。
        self.context.stage('OUTPUT_VERIFYING')
        config=dict(self.original.config,_output_progress_folder=str(Path(self.original.config['local_jobs_root'])/state['manifest']['job_id']))
        verified = verify_local_output(config,output,float(state['manifest']['duration_us'])/1000000)
        media.update(verified['media'])
        return {'worker_output_path':str(output),'sha256':media['sha256'],'size':media['size'],
                'archive_state':'ARCHIVE_PENDING'}

    @contextmanager
    def request(self, route, value=None):
        if not route.startswith('/receipt/'):
            raise PermissionError('SERVER_CLAIM_REQUIRED')
        self.receipt = value
        self.context.coordinator.journal(self.context.job,'RENDER_RECEIPT_LOCAL',receipt=value)
        with io.BytesIO(b'{"saved":true}') as result:
            yield result


class WorkstationRenderer:
    def __init__(self, config, transport, *, renderer=None):
        self.config,self.transport,self.renderer = config,transport,renderer

    def __call__(self, job, context):
        manifest = job['payload']['render_manifest']
        if manifest['job_id']!=job['job_id'] or manifest['content_id']!=job['content_id'] or manifest.get('target_account_id')!=job['business_account_id']:
            raise PermissionError('RENDER_CLAIM_IDENTITY_MISMATCH')
        context.stage('RENDER_PREPARING')
        transport = LocalOutputTransport(self.transport,context)
        agent = Agent(self.config,transport=transport,renderer=self.renderer)
        original = agent.renderer
        def render(claim, path):
            context.stage('RENDERING')
            # 原renderer内部包含剪映Render+Export，整个调用持续持有相同媒体锁。
            result=original(claim,path)
            context.stage('OUTPUT_VERIFYING')
            return result
        agent.renderer = render
        result = agent.execute_claim({'claim':job['lease_token'],'manifest':manifest},resume_original=bool(job.get('recover_render')))
        receipt = transport.receipt
        if result!='COMPLETED' or not receipt:
            from startup_render.automation_health import record
            record(self.config,'EXECUTOR_FAILURE',job_id=job['job_id'],success=False,
                   error=receipt.get('error','RENDER_FAILED') if receipt else 'RENDER_RECEIPT_MISSING')
            from .progress import mark_stalled
            mark_stalled(Path(self.config['local_jobs_root'])/job['job_id'],receipt.get('error','RENDER_FAILED') if receipt else 'RENDER_RECEIPT_MISSING')
            # 单Job在导出前失败时，只按归属/无输入闩锁/草稿未变证据收尾。
            # 收尾失败保留旧槽，绝不强杀；成功后其它任务可用，渲染熔断独立限制新claim。
            folder=Path(self.config['local_jobs_root'])/job['job_id']
            from .workstation_health import read_optional,owner_path
            from .progress import read_progress
            from .render_recovery import close_owned_home
            owner=read_optional(owner_path(self.config));stage=read_progress(folder) or {}
            if owner.get('render_job_id')==job['job_id'] and not list(folder.glob('export_submit_once*.json')):
                try:
                    close_owned_home(self.config,folder,pre_export_recovery={'job_id':job['job_id'],
                        'launch_token':owner['launch_token'],'draft_mtime_ns':stage.get('observed_draft_mtime_ns')})
                except Exception:
                    import logging
                    logging.exception('executor cleanup not proven; keep lane blocked')
            raise ExecutionFailure('JOB_LEVEL',receipt.get('error','RENDER_FAILED') if receipt else 'RENDER_RECEIPT_MISSING')
        from .progress import progress
        from startup_render.common import read
        local_job=read(Path(self.config['local_jobs_root'])/job['job_id']/'render_job.json')
        progress(local_job,'COMPLETE','verified_receipt')
        return {'local_output_path':receipt['worker_output_path'],'media':receipt['media'],'render_receipt':receipt}

    def recover(self, job, context):
        manifest = job['payload']['render_manifest']
        output = self.transport.output_path(manifest)
        folder=Path(self.config['local_jobs_root'])/job['job_id']
        latch=folder/'export_submit_once.json'
        from startup_render.common import read,digest
        if not Path(output).exists() and latch.is_file():
            submitted=read(latch)
            if submitted.get('job_id')!=job['job_id'] or submitted.get('draft_name')!=manifest['draft_name']:
                raise PermissionError('EXPORT_RECOVERY_IDENTITY_MISMATCH')
            actual=Path(submitted['actual_output_path'])
            if not actual.is_absolute() or str(actual).startswith(('\\\\','//')) or actual.name!=manifest['draft_name']+'.mp4':
                raise PermissionError('EXPORT_RECOVERY_LOCAL_PATH_REQUIRED')
            if actual.exists():
                # 导出完成而拷贝未完成的窗口：只收回原文件，不再点击Export。
                Path(output).parent.mkdir(parents=True,exist_ok=True)
                with actual.open('rb') as src,Path(output).open('xb') as dest:shutil.copyfileobj(src,dest)
                if digest(actual)!=digest(output):raise ValueError('RECOVERY_COPY_CHANGED')
                from startup_render.media_compat import normalize_export
                normalize_export(self.config,Path(output),folder)
            else:
                raise ExecutionFailure('JOB_LEVEL','EXPORT_ALREADY_ATTEMPTED_NO_REPLAY')
        if Path(output).is_file():
            context.stage('OUTPUT_VERIFYING')
            # 复制完成但归一化尚未开始时，继续同一文件的既有编码步骤。
            from startup_render.media_compat import normalize_export
            normalize_export(self.config,Path(output),folder)
            return verify_local_output(self.config,output,float(manifest['duration_us'])/1000000)
        # 已提交过导出或已恢复过一次，均禁止再次打开草稿执行。
        if list(folder.glob('export_submit_once*.json')):
            raise ExecutionFailure('JOB_LEVEL','EXPORT_ALREADY_ATTEMPTED_NO_REPLAY')
        from .progress import reserve_recovery
        reserve_recovery(folder,job['job_id'])
        failure=folder/'render_error.json'
        if failure.exists():failure.rename(folder/('render_error.before-recovery.'+str(time.time_ns())+'.json'))
        # 调用方已持有媒体Mutex并证明无旧执行子进程；只续原Job，保留中断证据。
        state=folder/'state.json'
        if state.exists():
            from startup_render.common import read
            previous=read(state)
            if previous['manifest']['job_id']!=job['job_id'] or previous['manifest']['content_id']!=job['content_id']:
                raise PermissionError('RECOVERY_ORIGINAL_JOB_REQUIRED')
            # 原Agent只接受未开始state；备份原state后以同身份重新执行已验哈希的包。
            state.rename(folder/('state.interrupted.'+str(time.time_ns())+'.json'))
        return self(job,context)
