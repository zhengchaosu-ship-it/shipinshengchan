"""生成完成事件的幂等入队；只写PENDING，不扫描文件、不传输、不运行Worker。"""
import json
from pathlib import Path
import sqlite3

from .common import identifier, read
from .server import closing_connection


class RenderQueue:
    def __init__(self, path=None):
        if path is None:
            config = read(Path(__file__).with_name('server.example.json'))
            path = Path(config['state_root']) / 'render_jobs.db'
        self.path = Path(path).resolve()

    def enqueue(self, record):
        content = identifier(record['content_id'])
        identifier(record['batch_id'])
        if record['business_type'] != 'STARTUP':
            raise ValueError('STARTUP_REQUIRED')
        payload = {k: record[k] for k in ('content_id', 'employee_id', 'batch_id', 'video_index',
                   'composition_signature', 'draft_name', 'draft_path', 'business_type', 'created_at', 'generation_id')}
        payload.update(job_id=content, render_job_id=content, pending_at=record['created_at'],
                       return_mp4=True, origin='GENERATION_COMPLETED_EVENT')
        for key in ('target_account_id', 'target_account_name_snapshot'):
            if key in record:
                payload[key] = record[key]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing_connection(sqlite3.connect(self.path, timeout=30)) as db:
            db.row_factory = sqlite3.Row
            db.execute('CREATE TABLE IF NOT EXISTS jobs(job_id TEXT PRIMARY KEY,batch_id TEXT NOT NULL,video_index INTEGER NOT NULL,'
                       'status TEXT NOT NULL,payload TEXT NOT NULL,claim TEXT,receipt TEXT,error TEXT,UNIQUE(batch_id,video_index))')
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM jobs WHERE job_id=? OR (batch_id=? AND video_index=?)',
                             (content, record['batch_id'], record['video_index'])).fetchone()
            if old:
                prior = json.loads(old['payload'])
                if old['job_id'] != content or any(prior.get(k) != payload[k] for k in payload if k not in {'return_mp4', 'pending_at'}):
                    raise PermissionError('RENDER_JOB_IDENTITY_IMMUTABLE')
                return old['job_id']
            db.execute("INSERT INTO jobs(job_id,batch_id,video_index,status,payload) VALUES(?,?,?,'PENDING',?)",
                       (content, record['batch_id'], record['video_index'], json.dumps(payload, ensure_ascii=False)))
        return content
