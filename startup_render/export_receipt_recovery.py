"""服务器本地明确授权的一次导出恢复；不能重置通用失败队列。"""
from datetime import datetime, timezone
from pathlib import Path
from .common import identifier, read
from .validation_recovery import fingerprint

KIND='JIANYING59_EXPORT_RECOVERY'


def validate(root, identity, failed, completed):
    job=identifier(identity['job_id'])
    approval=Path(root)/'export_recovery_approvals'/(job+'.json')
    if not approval.is_file():raise ValueError('RESULT_IMMUTABLE')
    scope=read(approval)
    media=completed.get('media',{})
    expected={'job_id':job,'content_id':identity['content_id'],
              'account_id':identity.get('target_account_id'),'claim':failed.get('claim')}
    if (scope.get('kind')!=KIND or scope.get('authorized') is not True
            or any(scope.get(k)!=v for k,v in expected.items())
            or datetime.fromisoformat(scope['expires_at'])<=datetime.now(timezone.utc)
            or failed.get('status')!='NEEDS_MANUAL' or failed.get('failed_step')!='EXPORTING'
            or fingerprint(failed)!=scope.get('original_receipt_sha256')
            or completed.get('recovery_of_receipt_sha256')!=fingerprint(failed)
            or completed.get('recovery_kind')!=KIND or completed.get('recovery_export_attempts')!=1
            or completed.get('claim')!=failed.get('claim')
            or completed.get('status')!='COMPLETED' or completed.get('real_publish_attempts')!=0
            or completed.get('export_status')!='VALIDATED'
            or media.get('sha256')!=scope.get('output_sha256') or media.get('size')!=scope.get('output_size')
            or not media.get('full_decode_verified') or media.get('codec')!='h264' or media.get('audio_codec')!='aac'):
        raise PermissionError('EXPORT_RECOVERY_SCOPE_MISMATCH')
    return {'approved':True,'original_failure_sha256':fingerprint(failed),
            'archive_filename':job+'.failed-export-original.json'}
