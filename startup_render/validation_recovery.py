"""仅本轮已导出HEVC成片的有界验收恢复；不重导出、不恢复历史失败任务。"""
import hashlib
import json
from pathlib import Path
from .common import read


def fingerprint(receipt):
    return hashlib.sha256(json.dumps(receipt,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def validate_recovery(root, identity, failed, completed):
    if completed.get('recovery_kind')=='JIANYING59_EXPORT_RECOVERY':
        from .export_receipt_recovery import validate
        return validate(root,identity,failed,completed)
    root=Path(root)
    approval_path=root.parent/'VALIDATION_RECOVERY_APPROVAL.json'
    if not approval_path.is_file():
        raise ValueError('RESULT_IMMUTABLE')
    scope=read(approval_path)
    generated=read(root.parent/'GENERATION_RESULT.json')
    expected=generated['registered']
    if (len(expected)!=1 or expected[0]['content_id']!=identity['job_id']
        or scope.get('run_id')!=root.parent.name
        or scope.get('job_id')!=identity['job_id'] or identity['content_id']!=identity['job_id']
        or identity.get('target_account_id')!=scope.get('account_id')
        or failed.get('status')!='NEEDS_MANUAL' or failed.get('failed_step')!='VALIDATING'
        or failed.get('error')!='ValueError:EXPORTED_MEDIA_VALIDATION_FAILED'
        or completed.get('status')!='COMPLETED' or completed.get('real_publish_attempts')!=0
        or completed.get('recovery_of_receipt_sha256')!=fingerprint(failed)
        or completed.get('normalization',{}).get('original_sha256')!=scope.get('original_sha256')
        or completed.get('media',{}).get('codec')!='h264'
        or not any(e['status']=='EXPORTED' for e in failed.get('events',[]))
        or not any(e['status']=='PROCESS_EXITED' for e in failed.get('events',[]))):
        raise PermissionError('VALIDATION_RECOVERY_SCOPE_MISMATCH')
    return {'approved':True,'original_failure_sha256':fingerprint(failed)}
