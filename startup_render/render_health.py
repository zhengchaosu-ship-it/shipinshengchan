"""区分任务隔离与工作站故障；心跳不能代替实际导出能力证据。"""
from datetime import datetime, timezone
from pathlib import Path
import shutil
from .common import digest, read

JOB_ERRORS=('DRAFT_LOAD_TIMEOUT','DRAFT_NAME_MISMATCH','DRAFT_NOT_VISIBLE_AFTER_BOUNDED_SCROLL',
            'DRAFT_NOT_VISIBLE','JIANYING_DRAFT_NOT_VISIBLE','DUPLICATE_DRAFT_NAME',
            'REFERENCED_MEDIA_MISSING','REQUIRED_AUDIO_STREAM_MISSING','RESOLUTION_MISMATCH',
            'FPS_MISMATCH','EXPORTED_MEDIA_VALIDATION_FAILED','FULL_DECODE_FAILED')


def failure_scope(receipt):
    if receipt.get('status')=='FAILED_MISSING_SOURCE':return 'JOB_HALTED'
    error=receipt.get('error','')
    if receipt.get('status')=='VERSION_DRIFT':return 'WORKER_BROKEN'
    if any(code in error for code in JOB_ERRORS):return 'JOB_HALTED'
    return 'WORKER_BROKEN'


def probe(config, status, *, job_attention=0):
    result={'checked_at':datetime.now(timezone.utc).isoformat(),'status':status,
            'process_health':'READY','draft_health':'NEEDS_ATTENTION' if job_attention else 'READY',
            'export_automation_health':'UNKNOWN','render_capability':'HALTED','readiness':'HALTED',
            'job_attention_count':job_attention,'real_publish_enabled':False}
    root=Path(config['state_root']);proof_path=root/'export_capability.json'
    try:
        if not proof_path.is_file():raise ValueError('EXPORT_CAPABILITY_NOT_VERIFIED')
        proof=read(proof_path)
        if (proof.get('worker_id')!=config['worker_id'] or not proof.get('full_decode_verified')
                or proof.get('jianying_sha256')!=config['jianying_sha256'].lower()
                or digest(config['jianying_exe'])!=config['jianying_sha256'].lower()):
            raise ValueError('EXPORT_CAPABILITY_VERSION_MISMATCH')
        required=('draft_root','local_jobs_root','task_files_unc','startup_assets_unc')
        if not config.get('media_execution_enabled'):
            required+=('render_output_unc',)
        if any(not Path(config[k]).is_dir() for k in required):
            raise ValueError('RENDER_STORAGE_UNAVAILABLE')
        if shutil.disk_usage(config['local_jobs_root']).free<5*1024**3:
            raise ValueError('INSUFFICIENT_DISK_SPACE')
        result['export_automation_health']='READY'
        result['capability_verified_at']=proof['verified_at']
        if status=='HALTED_NEEDS_MANUAL':
            result['export_automation_health']='ATTENTION_REQUIRED'
        else:
            result['render_capability']='READY'
            result['readiness']='DEGRADED' if job_attention else 'READY'
    except Exception as error:
        result['failure_code']=str(error)
        result['process_health']='DEGRADED'
    return result
