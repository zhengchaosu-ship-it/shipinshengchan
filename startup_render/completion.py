"""仅接受已签发RenderJob的自动成片回传；不创建任何发布任务。"""
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from .common import below, digest, read, save


def register_completed(config, state_root, identity, receipt, *, validation_recovery=None):
    from startup_pipeline.service import probe_video
    if not identity.get('return_mp4') or receipt.get('export_status') != 'VALIDATED':
        raise ValueError('UNVALIDATED_RENDER_RECEIPT')
    from .common import output_relative
    path = below(config['result_root'], output_relative(identity))
    if not path.is_file() or digest(path) != receipt['media']['sha256']:
        raise ValueError('HOST_MP4_HASH_MISMATCH')
    media = probe_video(path)
    if media['size_bytes'] != receipt['media']['size']:
        raise ValueError('HOST_MP4_SIZE_MISMATCH')
    db_path = Path(config['operations_db']).resolve()
    with closing(sqlite3.connect(db_path.as_uri() + '?mode=rw', uri=True)) as db:
        db.row_factory = sqlite3.Row
        # 明确限定签发时的员工/内容/批次/序号/组合签名，Worker不能指定其它内容。
        row = db.execute('SELECT c.*,b.employee_id,b.manifest_path FROM startup_contents c '
                         'JOIN startup_batches b USING(batch_id) WHERE c.content_id=?', (identity['content_id'],)).fetchone()
        if not row or any(row[k] != identity[k] for k in ('employee_id', 'batch_id', 'video_index', 'composition_signature', 'business_type')):
            raise PermissionError('CONTENT_IDENTITY_CHANGED')
        if row['production_status'] == 'RENDER_FAILED':
            # 只接受Broker本机审批的本轮编码验收恢复，默认历史失败仍不可变。
            if not validation_recovery or not validation_recovery.get('approved'):
                raise PermissionError('FAILED_RENDER_CONTENT_IMMUTABLE')
            prior=db.execute('SELECT * FROM startup_render_failures WHERE content_id=?', (identity['content_id'],)).fetchone()
            if not prior or prior['receipt_sha256']!=validation_recovery['original_failure_sha256']:
                raise PermissionError('VALIDATION_RECOVERY_FAILURE_PROOF_MISMATCH')
        from startup_pipeline.account_binding import content_binding, require_account
        binding = content_binding(db, identity['content_id'])
        if binding or identity.get('target_account_id'):
            require_account(db, identity['content_id'], identity.get('target_account_id'))
            if binding['draft_name'] != identity['draft_name'] or binding['target_account_name_snapshot'] != identity.get('target_account_name_snapshot'):
                raise PermissionError('ACCOUNT_BINDING_MISMATCH')
        manifest = read(row['manifest_path'])
        video = next(v for v in manifest['videos'] if v['video_index'] == row['video_index'])
        if video['composition_signature'] != row['composition_signature'] or video['draft_name'] != identity['draft_name']:
            raise PermissionError('SOURCE_MANIFEST_CHANGED')
        if row['publish_status'] != 'NOT_SCHEDULED' or row['video_path'] and row['video_path'] != str(path):
            raise PermissionError('CONTENT_ALREADY_BOUND_OR_SCHEDULED')
        if db.execute('SELECT 1 FROM startup_job_metadata WHERE content_id=?', (row['content_id'],)).fetchone():
            raise PermissionError('CONTENT_HAS_PUBLISH_JOB')
        backup = Path(state_root) / ('operations.before-ready.' + identity['job_id'] + '.db')
        if not backup.exists():
            with closing(sqlite3.connect(backup)) as saved: db.backup(saved)
        db.execute('BEGIN IMMEDIATE')
        updated = db.execute("UPDATE startup_contents SET video_path=?,production_status='READY',duration_seconds=?,"
                            "size_bytes=?,mtime_ns=?,media_json=?,error=NULL WHERE content_id=? AND publish_status='NOT_SCHEDULED' "
                            "AND composition_signature=? AND (video_path IS NULL OR video_path='' OR video_path=?)",
                            (str(path), media['duration_seconds'], media['size_bytes'], media['mtime_ns'],
                             json.dumps(media['media'], ensure_ascii=False), row['content_id'], row['composition_signature'], str(path)))
        if updated.rowcount != 1:
            db.rollback(); raise PermissionError('CONTENT_CHANGED_DURING_VALIDATION')
        db.commit()
    return {'server_video_path': str(path), 'content_status': 'READY_TO_PUBLISH',
            'database_production_status': 'READY', 'pool': 'STARTUP_READY_TO_PUBLISH'}
