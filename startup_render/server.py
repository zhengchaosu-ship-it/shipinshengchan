"""只读发现已归属的新批次，用独立数据库派发2060S导出任务。"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import shutil
import sqlite3
import threading
import uuid

from .common import below, digest, identifier, package, read, save


class Broker:
    def __init__(self, config):
        self.config = config
        self.root = Path(config['state_root']).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        run_file = self.root.parent / 'single_run.json'
        self.run = read(run_file) if run_file.exists() else {}
        self.db_path = self.root / 'render_jobs.db'
        self.batches = Path(config['batch_root']).resolve()
        with self.connect() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);'
                             'CREATE TABLE IF NOT EXISTS jobs(job_id TEXT PRIMARY KEY,batch_id TEXT NOT NULL,video_index INTEGER NOT NULL,'
                             'status TEXT NOT NULL,payload TEXT NOT NULL,claim TEXT,receipt TEXT,error TEXT,'
                             'UNIQUE(batch_id,video_index));')
            if not db.execute("SELECT 1 FROM settings WHERE key='baseline'").fetchone():
                baseline = [p.parent.name for p in self.batches.glob('*/batch_manifest.json')]
                db.execute('INSERT INTO settings VALUES(?,?)', ('baseline', json.dumps(baseline)))
                db.execute('INSERT INTO settings VALUES(?,?)', ('activated_at', datetime.now(timezone.utc).isoformat()))

    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        return closing_connection(db)

    def account_allows_render(self, content_id):
        """托管停止后不领取尚未开始的渲染；人工生成继续走原队列。"""
        if not self.config.get('operations_db'):return True
        path=Path(self.config['operations_db']).resolve()
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='autopilot_allocations'").fetchone():return True
            row=db.execute('''SELECT a.state,u.enabled,u.status FROM autopilot_allocations a
                LEFT JOIN autopilot_authorizations u USING(account_id) WHERE a.content_id=?''',(content_id,)).fetchone()
            if row is None:return True
            return bool(row[1] and row[2] in ('COLD_START','LEARNING','AUTOPILOT') and row[0]=='RENDER_PENDING')

    def discover(self):
        if self.config.get('event_only'):
            return self.prepare_pending_events()
        with self.connect() as db:
            baseline = set(json.loads(db.execute("SELECT value FROM settings WHERE key='baseline'").fetchone()[0]))
            activation = datetime.fromisoformat(db.execute("SELECT value FROM settings WHERE key='activated_at'").fetchone()[0])
        for path in sorted(self.batches.glob('*/batch_manifest.json')):
            if self.run:
                with self.connect() as db:
                    if db.execute('SELECT count(*) FROM jobs').fetchone()[0] >= self.run['max_jobs']:
                        return
            if path.parent.name in baseline:
                continue
            try:
                manifest = read(path)
                if self.run and datetime.fromisoformat(manifest['created_at']) < datetime.fromisoformat(self.run['started_at']):
                    continue
                if not manifest.get('completed_at') or datetime.fromisoformat(manifest['created_at']) < activation:
                    continue
                if self.run.get('require_single_video') and len(manifest['videos']) != 1:
                    save(self.root / 'run_error.json', {'batch_id': manifest['batch_id'], 'error': 'EXPECTED_EXACTLY_ONE_VIDEO'})
                    return
                identifier(manifest['batch_id'])
                if manifest['batch_id'] != path.parent.name:
                    raise ValueError('BATCH_PATH_IDENTITY_MISMATCH')
                # 只读业务库取得真实content_id/员工归属，绝不复制账号密码或会话。
                business = Path(self.config['operations_db']).resolve()
                with closing(sqlite3.connect(business.as_uri() + '?mode=ro', uri=True)) as source:
                    source.row_factory = sqlite3.Row
                    rows = source.execute('SELECT c.content_id,c.video_index,c.composition_signature,c.publish_status,b.employee_id '
                                          'FROM startup_contents c JOIN startup_batches b USING(batch_id) '
                                          'WHERE c.batch_id=? AND b.manifest_path=?', (manifest['batch_id'], str(path))).fetchall()
                for row in rows:
                    video = next(v for v in manifest['videos'] if v['video_index'] == row['video_index'])
                    if video['status'] != 'success' or row['publish_status'] != 'NOT_SCHEDULED':
                        continue
                    if row['composition_signature'] != video['composition_signature']:
                        raise ValueError('COMPOSITION_IDENTITY_MISMATCH')
                    job_id = identifier(row['content_id'])
                    with self.connect() as db:
                        if db.execute('SELECT 1 FROM jobs WHERE job_id=?', (job_id,)).fetchone():
                            continue
                        identity = {'job_id': job_id, 'content_id': job_id, 'batch_id': manifest['batch_id'],
                                    'video_index': row['video_index'], 'employee_id': row['employee_id'],
                                    'business_type': 'STARTUP', 'composition_signature': row['composition_signature'],
                                    'draft_name': video['draft_name']}
                        if self.run:
                            identity.update(run_id=self.run['run_id'], return_mp4=self.run.get('return_mp4', False),
                                            pending_at=datetime.now(timezone.utc).isoformat())
                        db.execute('INSERT INTO jobs(job_id,batch_id,video_index,status,payload) VALUES(?,?,?,?,?)',
                                   (job_id, manifest['batch_id'], row['video_index'], 'PREPARING', json.dumps(identity)))
                    try:
                        draft = Path(video['draft_path']).resolve()
                        allowed = [Path(p).resolve() for p in self.config['allowed_draft_roots']]
                        if not any(draft.is_relative_to(p) and draft != p for p in allowed):
                            raise ValueError('DRAFT_OUTSIDE_APPROVED_ROOTS')
                        payload = package(draft, self.root / 'packages' / job_id, identity,
                                          max_bytes=self.config.get('max_package_bytes', 20 * 1024**3))
                        with self.connect() as db:
                            db.execute("UPDATE jobs SET status='QUEUED',payload=? WHERE job_id=?",
                                       (json.dumps(payload, ensure_ascii=False), job_id))
                    except Exception as error:
                        failed = 'FAILED_MISSING_SOURCE' if 'MISSING' in str(error) or isinstance(error, FileNotFoundError) else 'NEEDS_MANUAL'
                        with self.connect() as db:
                            db.execute('UPDATE jobs SET status=?,error=? WHERE job_id=?', (failed, type(error).__name__ + ':' + str(error), job_id))
                        save(self.root / 'receipts' / (job_id + '.json'), {**identity, 'status': failed,
                             'failed_step': 'STAGING_FILES', 'error': str(error), 'completed_at': datetime.now(timezone.utc).isoformat()})
            except Exception as error:
                logging.error('batch %s: %s', path.parent.name, type(error).__name__)

    def prepare_pending_events(self):
        """只准备完成事件已创建的PENDING任务；不扫描草稿/批次来推导归属。"""
        with self.connect() as db:
            rows = db.execute("SELECT * FROM jobs WHERE status='PENDING' ORDER BY batch_id,video_index").fetchall()
            if self.run and db.execute("SELECT count(*) FROM jobs WHERE status!='PENDING'").fetchone()[0] >= self.run['max_jobs']:
                return
        if self.run:
            rows = [r for r in rows if datetime.fromisoformat(json.loads(r['payload'])['created_at']) >= datetime.fromisoformat(self.run['started_at'])][:self.run['max_jobs']]
        for row in rows:
            identity = json.loads(row['payload'])
            job_id = row['job_id']
            if identity.get('origin') != 'GENERATION_COMPLETED_EVENT':
                continue
            with self.connect() as db:
                changed = db.execute("UPDATE jobs SET status='PREPARING' WHERE job_id=? AND status='PENDING'", (job_id,)).rowcount
                if not changed: continue
            try:
                business = Path(self.config['operations_db']).resolve()
                with closing(sqlite3.connect(business.as_uri() + '?mode=ro', uri=True)) as source:
                    source.row_factory = sqlite3.Row
                    registered = source.execute('SELECT * FROM startup_content_registrations WHERE content_id=?', (identity['content_id'],)).fetchone()
                    if not registered or any(registered[k] != identity[k] for k in ('employee_id','batch_id','video_index','composition_signature','draft_path','business_type')):
                        raise PermissionError('REGISTERED_RENDER_IDENTITY_MISMATCH')
                    from startup_pipeline.account_binding import content_binding, require_account
                    if content_binding(source, identity['content_id']) or identity.get('target_account_id'):
                        require_account(source, identity['content_id'], identity.get('target_account_id'))
                    if registered['production_status'] != 'RENDER_PENDING':
                        with self.connect() as db:
                            db.execute("UPDATE jobs SET status='PENDING' WHERE job_id=?", (job_id,))
                        continue
                draft = Path(identity['draft_path']).resolve()
                allowed = [Path(p).resolve() for p in self.config['allowed_draft_roots']]
                if not any(draft.is_relative_to(p) and draft != p for p in allowed):
                    raise ValueError('DRAFT_OUTSIDE_APPROVED_ROOTS')
                # 沿用原素材打包与Worker协议，不改变传输/导出实现。
                payload = package(draft, self.root / 'packages' / job_id, identity,
                                  max_bytes=self.config.get('max_package_bytes', 20 * 1024**3))
                with self.connect() as db:
                    db.execute("UPDATE jobs SET status='QUEUED',payload=? WHERE job_id=?", (json.dumps(payload, ensure_ascii=False), job_id))
            except Exception as error:
                failed = 'FAILED_MISSING_SOURCE' if 'MISSING' in str(error) or isinstance(error, FileNotFoundError) else 'NEEDS_MANUAL'
                with self.connect() as db:
                    db.execute('UPDATE jobs SET status=?,error=? WHERE job_id=?', (failed, type(error).__name__ + ':' + str(error), job_id))

    def claim(self):
        if self.config.get('media_execution_enabled'):
            raise PermissionError('UNIFIED_MEDIA_COORDINATOR_REQUIRED')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            from production_autopilot.restore_guard import render_allowed
            if not render_allowed(db):return None
            active = db.execute("SELECT * FROM jobs WHERE status='CLAIMED' LIMIT 1").fetchone()
            if active:
                return {'claim': active['claim'], 'manifest': json.loads(active['payload'])}
            row = next((r for r in db.execute("SELECT * FROM jobs WHERE status='QUEUED' ORDER BY batch_id,video_index").fetchall() if self.account_allows_render(r['job_id'])),None)
            if not row:
                return None
            token = uuid.uuid4().hex
            db.execute("UPDATE jobs SET status='CLAIMED',claim=? WHERE job_id=?", (token, row['job_id']))
            return {'claim': token, 'manifest': json.loads(row['payload'])}

    def receipt(self, job_id, value):
        identifier(job_id)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM jobs WHERE job_id=?', (job_id,)).fetchone()
            if not row or not isinstance(value.get('claim'), str) or value['claim'] != row['claim']:
                raise PermissionError('CLAIM_MISMATCH')
            if value.get('status') not in {'EXPORTED_AWAITING_PUBLISH_PARAMETERS', 'NEEDS_MANUAL', 'FAILED_MISSING_SOURCE', 'VERSION_DRIFT', 'COMPLETED'}:
                raise ValueError('INVALID_RESULT_STATE')
            original_encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
            recovery = None
            if row['receipt'] and json.loads(row['receipt'])['status'] != value['status']:
                from .validation_recovery import validate_recovery
                recovery = validate_recovery(self.root,json.loads(row['payload']),json.loads(row['receipt']),value)
            if row['receipt'] and row['receipt'] != original_encoded:
                # 成功回执会附加主机验收字段，沿用下面的最终不可变检查。
                if value['status'] in {'NEEDS_MANUAL', 'FAILED_MISSING_SOURCE', 'VERSION_DRIFT'}:
                    raise ValueError('RESULT_IMMUTABLE')
            identity = json.loads(row['payload'])
            if value['status'] in {'NEEDS_MANUAL', 'FAILED_MISSING_SOURCE', 'VERSION_DRIFT'} and identity.get('origin') == 'GENERATION_COMPLETED_EVENT':
                from startup_pipeline.render_failure import register_failed
                register_failed(self.config, identity, value)
            if value['status'] in {'EXPORTED_AWAITING_PUBLISH_PARAMETERS', 'COMPLETED'}:
                for key in ('content_id', 'batch_id', 'video_index', 'employee_id', 'business_type', 'composition_signature'):
                    if value.get(key) != identity[key]:
                        raise ValueError('RECEIPT_IDENTITY_MISMATCH')
                if not value.get('video_path') or not value.get('media') or value.get('real_publish_attempts') != 0:
                    raise ValueError('INVALID_EXPORT_RECEIPT')
                if identity.get('target_account_id') and any(value.get(k) != identity[k] for k in
                        ('target_account_id', 'target_account_name_snapshot')):
                    raise PermissionError('ACCOUNT_BINDING_MISMATCH')
                if value['status'] == 'COMPLETED':
                    from .completion import register_completed
                    value = dict(value, **register_completed(self.config, self.root, identity, value,
                                      validation_recovery=recovery))
            encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
            if row['receipt'] and row['receipt'] != encoded and not recovery:
                raise ValueError('RESULT_IMMUTABLE')
            if recovery:
                archived=self.root/'receipts'/recovery.get('archive_filename',job_id+'.failed-validation-attempt1.json')
                if archived.exists() and read(archived)!=json.loads(row['receipt']):
                    raise ValueError('ORIGINAL_FAILURE_ARCHIVE_CHANGED')
                if not archived.exists(): save(archived,json.loads(row['receipt']))
            db.execute('UPDATE jobs SET status=?,receipt=? WHERE job_id=?', (value['status'], encoded, job_id))
        save(self.root / 'receipts' / (job_id + '.json'), value)

    def receive_mp4(self, job_id, claim, expected_hash, stream, length):
        identifier(job_id)
        if not 0 < length <= self.config.get('max_package_bytes', 20 * 1024**3):
            raise ValueError('INVALID_MP4_SIZE')
        with self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE job_id=?', (job_id,)).fetchone()
        if not row or row['claim'] != claim or not json.loads(row['payload']).get('return_mp4'):
            raise PermissionError('CLAIM_MISMATCH')
        payload = json.loads(row['payload'])
        from .common import output_relative
        target = below(self.config['result_root'], output_relative(payload))
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + '.' + job_id + '.part')
        # 并发上传不允许覆盖；中断保留part并停止，不手工补结果。
        with partial.open('xb') as output:
            remaining = length
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk: raise ValueError('INCOMPLETE_MP4_UPLOAD')
                output.write(chunk); remaining -= len(chunk)
        if digest(partial) != expected_hash: raise ValueError('MP4_HASH_MISMATCH')
        if target.exists():
            raise FileExistsError('HOST_OUTPUT_EXISTS_NO_OVERWRITE')
        partial.rename(target)
        return {'server_video_path': str(target), 'sha256': expected_hash, 'size': length}

    def status(self):
        with self.connect() as db:
            rows = [dict(r) for r in db.execute('SELECT job_id,batch_id,video_index,status,error FROM jobs ORDER BY batch_id,video_index')]
        return {'status': 'LISTENING_FOR_NEW_OWNED_BATCHES', 'jobs': rows, 'real_publish_enabled': False, 'run': self.run}


class closing_connection:
    def __init__(self, db): self.db = db
    def __enter__(self): return self.db
    def __exit__(self, kind, error, trace):
        try:
            self.db.rollback() if kind else self.db.commit()
        finally:
            self.db.close()


class Handler(BaseHTTPRequestHandler):
    def authorized(self):
        return self.client_address[0] in self.server.broker.config['allowed_clients']

    def reply(self, value, status=200):
        data = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status); self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        if not self.authorized(): return self.reply({'error': 'FORBIDDEN'}, 403)
        broker = self.server.broker
        if self.path == '/health': return self.reply(broker.status())
        pieces = self.path.split('/')
        try:
            if len(pieces) != 4 or pieces[1] != 'file': raise ValueError('UNKNOWN_ROUTE')
            job = identifier(pieces[2]); index = int(pieces[3])
            with broker.connect() as db:
                row = db.execute('SELECT payload FROM jobs WHERE job_id=?', (job,)).fetchone()
            entries = json.loads(row['payload'])['files']
            if index < 0 or index >= len(entries): raise ValueError('INVALID_FILE_INDEX')
            entry = entries[index]
            path = below(broker.root / 'packages' / job, entry['relative'])
            self.send_response(200); self.send_header('Content-Length', str(path.stat().st_size)); self.end_headers()
            with path.open('rb') as stream: shutil.copyfileobj(stream, self.wfile)
        except (ValueError, KeyError, OSError, TypeError): self.reply({'error': 'FILE_NOT_AVAILABLE'}, 404)

    def do_POST(self):
        if not self.authorized(): return self.reply({'error': 'FORBIDDEN'}, 403)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= 1024 * 1024: raise ValueError('BODY_TOO_LARGE')
            value = json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(value, dict): raise ValueError('OBJECT_REQUIRED')
            if self.path == '/claim': return self.reply(self.server.broker.claim())
            if self.path.startswith('/receipt/'):
                self.server.broker.receipt(self.path.split('/')[-1], value)
                return self.reply({'saved': True})
            raise ValueError('UNKNOWN_ROUTE')
        except (ValueError, KeyError, TypeError, PermissionError): self.reply({'error': 'REQUEST_REJECTED'}, 400)

    def do_PUT(self):
        if not self.authorized(): return self.reply({'error': 'FORBIDDEN'}, 403)
        try:
            if not self.path.startswith('/result/'): raise ValueError('UNKNOWN_ROUTE')
            result = self.server.broker.receive_mp4(self.path.split('/')[-1], self.headers.get('X-Claim'),
                        self.headers.get('X-SHA256'), self.rfile, int(self.headers.get('Content-Length', '0')))
            self.reply(result)
        except Exception as error:
            logging.exception('result upload failed')
            self.reply({'error': type(error).__name__ + ':' + str(error)}, 400)

    def log_message(self, fmt, *args): logging.info('%s %s', self.client_address[0], fmt % args)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--config', required=True); parser.add_argument('--scan-once', action='store_true')
    args = parser.parse_args(); config = read(args.config); broker = Broker(config)
    logging.basicConfig(filename=str(broker.root / 'broker.log'), level=logging.INFO)
    if args.scan_once:
        broker.discover(); print(json.dumps(broker.status(), ensure_ascii=False)); return
    # 中断的准备/领取任务保留给人工，不重复消费旧草稿。
    def watch():
        while True:
            try: broker.discover()
            except Exception: logging.exception('scan failed')
            threading.Event().wait(config.get('poll_seconds', 10))
    threading.Thread(target=watch, daemon=True).start()
    server = ThreadingHTTPServer((config['bind'], config['port']), Handler); server.broker = broker
    server.serve_forever()


if __name__ == '__main__': main()
