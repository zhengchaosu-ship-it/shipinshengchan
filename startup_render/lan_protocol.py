"""现有RenderQueue的LAN租约/Worker注册；不创建第二套业务队列。"""
from datetime import datetime, timezone
from contextlib import closing
import hashlib
import hmac
import json
from pathlib import Path
import time
import uuid

from .common import below, digest, identifier, output_relative, read, save


def token_from(config):
    if config.get('worker_token_file'):
        from .windows_secret import unprotect
        return unprotect(Path(config['worker_token_file']).read_bytes()).decode()
    import os
    value = os.environ.get(config.get('worker_token_env', 'XUNZHEN_RENDER_TOKEN'))
    if not value or len(value) < 32:
        raise RuntimeError('WORKER_TOKEN_REQUIRED')
    return value


class LanRegistry:
    def __init__(self, broker, *, clock=time.time):
        self.broker = broker
        self.config = broker.config
        self.clock = clock
        with broker.connect() as db:
            schema = Path(__file__).parent / 'migrations/001_lan_resident.sql'
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='lan_schema_migrations'").fetchone():
                import sqlite3
                backup = broker.root / 'render_jobs.before-versioned-lan-migration.db'
                if not backup.exists():
                    with closing(sqlite3.connect(backup)) as out:
                        db.backup(out)
            db.executescript(schema.read_text(encoding='utf-8'))

    def register(self, value):
        worker = identifier(value['worker_id'])
        allowed = self.config.get('worker_ids', [])
        if allowed and worker not in allowed:
            raise PermissionError('WORKER_NOT_ALLOWED')
        # 白名单字段，认证数据及任意客户端载荷不进入注册日志。
        details = {k: value.get(k) for k in ('hostname', 'ip', 'gpu', 'jianying_version',
                   'jianying_login_state', 'disk_free', 'version_info', 'timestamp',
                   'process_health','draft_health','export_automation_health','render_capability',
                   'readiness','job_attention_count','capability_verified_at')}
        status = value.get('status', 'ONLINE')
        if status not in {'ONLINE', 'IDLE', 'BUSY', 'HALTED_NEEDS_MANUAL'}:
            raise ValueError('INVALID_WORKER_STATUS')
        current = value.get('current_job_id')
        if current:
            identifier(current)
        with self.broker.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO lan_workers VALUES(?,?,?,?,?) ON CONFLICT(worker_id) DO UPDATE SET '
                       'details=excluded.details,last_heartbeat=excluded.last_heartbeat,status=excluded.status,'
                       'current_job_id=excluded.current_job_id',
                       (worker, json.dumps(details, ensure_ascii=False), self.clock(), status, current))
            stamp = str(details.get('timestamp') or self.clock())
            db.execute('INSERT OR IGNORE INTO lan_heartbeat_history VALUES(?,?,?,?,?)',
                       (worker, stamp, self.clock(), status, current))
            db.execute('DELETE FROM lan_heartbeat_history WHERE worker_id=? AND received_at<?',
                       (worker, self.clock()-86400))
            if current:
                # 心跳不能接管其它worker的任务。
                db.execute('UPDATE lan_leases SET expires_at=? WHERE worker_id=? AND job_id=?',
                           (self.clock() + self.config.get('lease_seconds', 120), worker, current))
        return {'worker_id': worker, 'registered': True, 'status': status}

    def workers(self):
        with self.broker.connect() as db:
            rows = db.execute('SELECT * FROM lan_workers ORDER BY worker_id').fetchall()
        return [dict(worker_id=r['worker_id'], **json.loads(r['details']),
                     last_heartbeat=datetime.fromtimestamp(r['last_heartbeat'], timezone.utc).isoformat(),
                     status='OFFLINE' if self.clock() - r['last_heartbeat'] > self.config.get('heartbeat_timeout', 90)
                     else r['status'], current_job_id=r['current_job_id']) for r in rows]

    def leases(self):
        with self.broker.connect() as db:
            return [dict(r) for r in db.execute('SELECT job_id,worker_id,expires_at,stage FROM lan_leases')]

    def claim(self, value):
        if self.config.get('media_execution_enabled'):
            raise PermissionError('UNIFIED_MEDIA_COORDINATOR_REQUIRED')
        worker = identifier(value['worker_id'])
        control_file = self.config.get('claim_control_file')
        control = read(control_file) if control_file else {'enabled': True}
        if not control.get('enabled'):
            return None
        with self.broker.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            registered = db.execute('SELECT * FROM lan_workers WHERE worker_id=?', (worker,)).fetchone()
            from production_autopilot.restore_guard import render_allowed
            if not render_allowed(db):return None
            if not registered or registered['status'] == 'HALTED_NEEDS_MANUAL':
                raise PermissionError('WORKER_REGISTRATION_REQUIRED')
            active = db.execute("SELECT j.*,l.worker_id,l.expires_at,l.stage FROM jobs j LEFT JOIN lan_leases l "
                                "ON j.job_id=l.job_id WHERE j.status='CLAIMED' ORDER BY j.batch_id,j.video_index").fetchall()
            for row in active:
                if row['worker_id'] == worker:
                    db.execute('UPDATE lan_leases SET expires_at=? WHERE job_id=?',
                               (self.clock() + self.config.get('lease_seconds', 120), row['job_id']))
                    return self._claimed(row)
            for row in active:
                # 不因超时自动重Render。租约丢失进入明确恢复状态，原worker可恢复回执。
                if row['worker_id'] and row['expires_at'] < self.clock():
                    db.execute("UPDATE lan_leases SET stage='LEASE_EXPIRED_NEEDS_RECONCILIATION' WHERE job_id=?",
                               (row['job_id'],))
            capacity=self.config.get('max_parallel_jobs',1)
            if type(capacity) is not int or not 1<=capacity<=50:raise ValueError('INVALID_RENDER_PARALLEL_CAPACITY')
            if len(active)>=capacity:return None
            allowed = control.get('allowed_batch_ids')
            rows = db.execute("SELECT * FROM jobs WHERE status='QUEUED' ORDER BY batch_id,video_index").fetchall()
            permits=getattr(self.broker,'account_allows_render',lambda key:True)
            row = next((r for r in rows if (allowed is None or r['batch_id'] in allowed) and permits(r['job_id'])), None)
            if row is None:
                return None
            claim = uuid.uuid4().hex
            manifest = json.loads(row['payload'])
            manifest['output_layout'] = 'LAN_RESIDENT_V1'
            for entry in manifest.get('files', []):
                entry['source_unc_path'] = self.source_unc(row['job_id'], entry)
                entry['asset_id'] = hashlib.sha256(entry['source'].encode()).hexdigest()[:20]
            db.execute("UPDATE jobs SET status='CLAIMED',claim=?,payload=? WHERE job_id=? AND status='QUEUED'",
                       (claim, json.dumps(manifest, ensure_ascii=False), row['job_id']))
            db.execute('INSERT INTO lan_leases VALUES(?,?,?,?,?,?)',
                       (row['job_id'], worker, claim, self.clock()+self.config.get('lease_seconds',120),'CLAIMED','{}'))
            return {'claim': claim, 'manifest': manifest}

    @staticmethod
    def _claimed(row):
        return {'claim': row['claim'], 'manifest': json.loads(row['payload'])}

    def source_unc(self, job, entry):
        source = Path(entry['source']).resolve()
        assets = Path(self.config['startup_assets_root']).resolve()
        if entry['relative'].startswith('assets/') and source.is_relative_to(assets):
            return str(Path(self.config['startup_assets_unc']) / source.relative_to(assets))
        return str(Path(self.config['task_files_unc']) / identifier(job) / entry['relative'])

    def verify_owner(self, job, value):
        identifier(job)
        with self.broker.connect() as db:
            row = db.execute('SELECT * FROM lan_leases WHERE job_id=?', (job,)).fetchone()
        if not row or row['worker_id'] != value.get('worker_id') or not hmac.compare_digest(row['claim'], str(value.get('claim',''))):
            raise PermissionError('WORKER_CLAIM_MISMATCH')
        return row

    def status(self, job, value):
        self.verify_owner(job, value)
        stage = value.get('stage')
        if stage not in {'CLAIMED','STAGING_FILES','DRAFT_READY','JIANYING_RENDERING','VALIDATING',
                         'RETURNING_OUTPUT','WAITING_STORAGE','COMPLETED','HALTED_NEEDS_MANUAL'}:
            raise ValueError('INVALID_STAGE')
        with self.broker.connect() as db:
            db.execute('UPDATE lan_leases SET stage=?,expires_at=?,details=? WHERE job_id=?',
                       (stage,self.clock()+self.config.get('lease_seconds',120),json.dumps({'timestamp':value.get('timestamp')}),job))
        return {'saved': True, 'stage': stage}

    def finish(self, job, value, *, complete):
        self.verify_owner(job, value)
        receipt = value['receipt']
        encoded = json.dumps(receipt, ensure_ascii=False, sort_keys=True)
        fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
        with self.broker.connect() as db:
            prior = db.execute('SELECT * FROM lan_receipt_requests WHERE job_id=?',(job,)).fetchone()
        approved_recovery=False
        if prior:
            if prior['request_sha256'] == fingerprint:return json.loads(prior['response'])
            if not complete or receipt.get('recovery_kind')!='JIANYING59_EXPORT_RECOVERY':
                raise ValueError('RESULT_IMMUTABLE')
            with self.broker.connect() as db:
                row=db.execute('SELECT payload,receipt FROM jobs WHERE job_id=?',(job,)).fetchone()
            failed=json.loads(row['receipt'])
            if failed['status']=='COMPLETED':
                failed=read(self.broker.root/'receipts'/(job+'.failed-export-original.json'))
            from .export_receipt_recovery import validate
            validate(self.broker.root,json.loads(row['payload']),failed,receipt)
            archive=self.broker.root/'receipts'/(job+'.lan-before-export-recovery.json')
            if archive.exists() and read(archive)!=dict(prior):raise ValueError('LAN_RECOVERY_ARCHIVE_CHANGED')
            if not archive.exists():save(archive,dict(prior))
            approved_recovery=True
        if receipt.get('claim') != value.get('claim'):
            raise PermissionError('RECEIPT_CLAIM_MISMATCH')
        if complete:
            if receipt.get('status') != 'COMPLETED':
                raise ValueError('INVALID_COMPLETION')
            with self.broker.connect() as db:
                row = db.execute('SELECT payload FROM jobs WHERE job_id=?',(job,)).fetchone()
            identity = json.loads(row['payload'])
            path = below(self.config['result_root'],output_relative(identity))
            if not path.is_file() or digest(path) != receipt['media']['sha256']:
                raise ValueError('SERVER_OUTPUT_HASH_MISMATCH')
        elif receipt.get('status') not in {'NEEDS_MANUAL','VERSION_DRIFT','FAILED_MISSING_SOURCE'}:
            raise ValueError('INVALID_FAILURE')
        # 原服务验证身份/ffprobe/READY，不替换业务完成逻辑。
        self.broker.receipt(job, receipt)
        result = {'saved': True}
        with self.broker.connect() as db:
            if approved_recovery:
                db.execute('UPDATE lan_receipt_requests SET request_sha256=?,response=? WHERE job_id=? AND request_sha256=?',
                           (fingerprint,json.dumps(result),job,prior['request_sha256']))
            db.execute('INSERT OR IGNORE INTO lan_receipt_requests VALUES(?,?,?)',(job,fingerprint,json.dumps(result)))
            db.execute('UPDATE lan_leases SET stage=? WHERE job_id=?',(receipt['status'],job))
        return result
