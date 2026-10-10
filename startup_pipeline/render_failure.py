"""失败回执→真实业务失败状态；不创建/重试RenderJob或PublishJob。"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3

FAILURE_STATES = {'NEEDS_MANUAL', 'FAILED_MISSING_SOURCE', 'VERSION_DRIFT'}


def migrate(path):
    path = Path(path).resolve()
    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)) as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='startup_render_failures'").fetchone():
            return {'already_applied': True}
        columns = [r[1] for r in db.execute('PRAGMA table_info(startup_contents)')]
        expected = ['content_id','batch_id','video_index','composition_signature','video_path','created_at','business_type','production_status','publish_status','duration_seconds','size_bytes','mtime_ns','media_json','materials_json','error']
        if columns != expected:
            raise RuntimeError('RENDER_FAILURE_MIGRATION_SCHEMA_MISMATCH')
        before = db.execute('SELECT * FROM startup_contents ORDER BY content_id').fetchall()
        objects = db.execute("SELECT sql FROM sqlite_master WHERE tbl_name='startup_contents' AND type IN ('index','trigger') AND sql IS NOT NULL").fetchall()
        backup = path.with_name(path.name + '.render-failure-' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.bak')
        with closing(sqlite3.connect(backup)) as saved:
            db.backup(saved)
        # 必须在事务外切换，仅本连接；不改线上其它连接的外键设置。
        db.execute('PRAGMA foreign_keys=OFF')
        db.execute('PRAGMA legacy_alter_table=ON')
        try:
            sql = (Path(__file__).parent / 'migrations/005_render_failure.sql').read_text(encoding='utf-8')
            db.executescript('BEGIN IMMEDIATE;' + sql)
            for (statement,) in objects:
                db.execute(statement)
            after = db.execute('SELECT ' + ','.join(expected) + ' FROM startup_contents ORDER BY content_id').fetchall()
            if before != after or db.execute('PRAGMA foreign_key_check').fetchall():
                raise RuntimeError('RENDER_FAILURE_MIGRATION_INTEGRITY_ERROR')
            db.execute('INSERT INTO startup_pipeline_migrations VALUES(5,?)', (datetime.now(timezone.utc).isoformat(),))
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.execute('PRAGMA legacy_alter_table=OFF')
            db.execute('PRAGMA foreign_keys=ON')
    return {'backup': str(backup), 'version': 5, 'old_content_rows_unchanged': True}


def register_failed(config, identity, receipt):
    if receipt.get('status') not in FAILURE_STATES or receipt.get('render_job_id', identity['job_id']) != identity['job_id']:
        raise ValueError('INVALID_RENDER_FAILURE_RECEIPT')
    if identity['content_id'] != identity['job_id'] or identity['business_type'] != 'STARTUP' or receipt.get('real_publish_attempts', 0) != 0:
        raise PermissionError('RENDER_FAILURE_IDENTITY_MISMATCH')
    code = receipt.get('failed_step') or receipt['status']
    if not isinstance(code, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]*', code):
        raise ValueError('INVALID_FAILURE_CODE')
    message = str(receipt.get('error') or code)
    events = receipt.get('events') or []
    failed_at = next((v['at'] for v in reversed(events) if v.get('status') in FAILURE_STATES | {'RENDER_FAILED'} and v.get('at')), None)
    if failed_at:
        datetime.fromisoformat(failed_at)
    else:
        # 指纹由原回执决定；重复回执不更新时间，即使旧回执没有阶段时间。
        failed_at = datetime.now(timezone.utc).isoformat()
    fingerprint = hashlib.sha256(json.dumps(receipt, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    path = Path(config['operations_db']).resolve()
    migrate(path)
    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT c.*,b.employee_id FROM startup_contents c JOIN startup_batches b USING(batch_id) WHERE content_id=?', (identity['content_id'],)).fetchone()
        if not row or any(row[k] != identity[k] for k in ('employee_id','batch_id','video_index','composition_signature','business_type')):
            raise PermissionError('CONTENT_IDENTITY_CHANGED')
        from .account_binding import content_binding, require_account
        binding = content_binding(db, identity['content_id'])
        if binding or identity.get('target_account_id'):
            require_account(db, identity['content_id'], identity.get('target_account_id'))
        if row['production_status'] == 'READY' or row['publish_status'] != 'NOT_SCHEDULED' or db.execute('SELECT 1 FROM startup_job_metadata WHERE content_id=?', (identity['content_id'],)).fetchone():
            raise PermissionError('CONTENT_ALREADY_READY_OR_SCHEDULED')
        old = db.execute('SELECT * FROM startup_render_failures WHERE content_id=?', (identity['content_id'],)).fetchone()
        if old:
            if old['render_job_id'] != identity['job_id'] or old['receipt_sha256'] != fingerprint:
                raise ValueError('FAILURE_RECEIPT_IMMUTABLE')
            return {'content_status': 'RENDER_FAILED', 'idempotent': True}
        db.execute('INSERT INTO startup_render_failures VALUES(?,?,?,?,?,?)', (identity['job_id'], identity['content_id'], fingerprint, code, message, failed_at))
        db.execute("UPDATE startup_contents SET production_status='RENDER_FAILED',error=?,failure_code=?,failure_message=?,failed_at=?,render_job_id=? WHERE content_id=?", (message, code, message, failed_at, identity['job_id'], identity['content_id']))
        db.commit()
    return {'content_status': 'RENDER_FAILED', 'failure_code': code, 'idempotent': False}
