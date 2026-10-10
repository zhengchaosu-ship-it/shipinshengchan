"""账号归属与数据库命名预留；昵称从不参与权限判断。"""
from contextlib import closing
from datetime import datetime, timezone, timedelta
from pathlib import Path
import re
import sqlite3
import uuid
from xiaovcat_adapter.models import utc_now_iso


def migrate(store):
    with store.connect() as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='startup_content_bindings'").fetchone():
            return {'already_applied': True}
        backup = store.path.with_name(store.path.name + '.account-binding-' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.bak')
        with closing(sqlite3.connect(backup)) as saved:
            db.backup(saved)
        try:
            db.executescript('BEGIN IMMEDIATE;' + (Path(__file__).parent / 'migrations/004_account_binding.sql').read_text(encoding='utf-8'))
            db.execute('INSERT INTO startup_pipeline_migrations VALUES(4,?)', (utc_now_iso(),))
            db.commit()
        except Exception:
            db.rollback()
            raise
        return {'backup': str(backup), 'version': 4}


def draft_name(name, business, local_date, sequence):
    labels = {'STARTUP': '起号', 'COMMERCE': '带货'}
    clean = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', name).strip().rstrip('. ')[:80] or '账号'
    day = datetime.fromisoformat(str(local_date))
    if sequence < 1:
        raise ValueError('INVALID_SEQUENCE')
    return f'{clean}{labels[business]}{day.month}月{day.day}日-{sequence}'


def reserve(store, token, account_id, count=1, *, now=None):
    if not account_id:
        raise PermissionError('TARGET_ACCOUNT_REQUIRED')
    if type(count) is not int or not 1 <= count <= 10:
        raise ValueError('INVALID_GENERATION_COUNT')
    local_date = (now or datetime.now(timezone(timedelta(hours=8)))).date().isoformat()
    with store.connect(write=True) as db:
        actor = store._principal(db, token)
        accounts = {r['account_id']: r for r in store._generation_accounts(db, actor, 'STARTUP')}
        if account_id not in accounts:
            raise PermissionError('ACCOUNT_PERMISSION_DENIED')
        name = accounts[account_id]['display_name']
        key = str(uuid.uuid4()); batch = 'STARTUP_' + key.replace('-', '')
        started = utc_now_iso()
        db.execute('INSERT INTO startup_generation_runs VALUES(?,?,?,NULL)', (key, actor['employee_id'], started))
        db.execute('INSERT INTO startup_generation_bindings VALUES(?,?,?,?,?,?,?)',
                   (key, actor['employee_id'], 'STARTUP', account_id, name, batch, local_date))
        last = db.execute('SELECT COALESCE(MAX(daily_sequence),0) FROM startup_name_reservations '
                          'WHERE target_account_id=? AND business_type=? AND local_date=?',
                          (account_id, 'STARTUP', local_date)).fetchone()[0]
        names = []
        for index in range(1, count + 1):
            value = draft_name(name, 'STARTUP', local_date, last + index)
            db.execute('INSERT INTO startup_name_reservations VALUES(?,?,?,?,?,?,?)',
                       (key, index, account_id, 'STARTUP', local_date, last + index, value))
            names.append(value)
    return dict(generation_id=key, employee_id=actor['employee_id'], started_at=started,
                business_type='STARTUP', target_account_id=account_id,
                target_account_name_snapshot=name, batch_id=batch, draft_names=names)


def content_binding(db, content_id):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='startup_content_bindings'").fetchone():
        return None
    return db.execute('SELECT * FROM startup_content_bindings WHERE content_id=?', (content_id,)).fetchone()


def require_account(db, content_id, account_id):
    binding = content_binding(db, content_id)
    if not binding or not account_id or binding['target_account_id'] != account_id:
        raise PermissionError('ACCOUNT_BINDING_MISMATCH')
    return binding


def guard_publish_job(db, job_id):
    """提交前读真实Job→稳定账号映射；历史非STARTUP任务保持原验证。"""
    job = db.execute('SELECT content_id FROM publish_jobs WHERE job_id=?', (job_id,)).fetchone()
    if not job:
        raise PermissionError('ACCOUNT_BINDING_MISMATCH')
    binding = content_binding(db, job['content_id'])
    if not binding and not job['content_id'].startswith('STARTUP-'):
        return
    account = db.execute('SELECT account_id FROM publish_plan_items WHERE job_id=?', (job_id,)).fetchall()
    if len(account) != 1:
        raise PermissionError('ACCOUNT_BINDING_MISMATCH')
    require_account(db, job['content_id'], account[0]['account_id'])
    metadata = db.execute('SELECT content_id,account_id FROM startup_job_metadata WHERE job_id=?', (job_id,)).fetchone()
    if not metadata or metadata['content_id'] != job['content_id'] or metadata['account_id'] != account[0]['account_id']:
        raise PermissionError('ACCOUNT_BINDING_MISMATCH')


def guard_manual_paths(db, paths):
    # 已绑定自动生产成片只能走READY入口，不能借手工入口换一个content_id规避锁定。
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='startup_content_bindings'").fetchone():
        return
    for path in paths:
        if db.execute('SELECT 1 FROM startup_contents c JOIN startup_content_bindings b USING(content_id) '
                      'WHERE c.video_path=? COLLATE NOCASE', (str(Path(path).resolve()),)).fetchone():
            raise PermissionError('ACCOUNT_BINDING_MISMATCH: USE_STARTUP_READY_POOL')


def render_states(store, content_ids, queue_path=None):
    """只读已授权内容的交接/队列状态，不启动Broker、不创建队列库。"""
    from startup_render.queue import RenderQueue
    states = {key: 'UNKNOWN' for key in content_ids}
    with store.connect() as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='startup_content_registrations'").fetchone():
            for key in content_ids:
                row = db.execute('SELECT production_status FROM startup_content_registrations WHERE content_id=?', (key,)).fetchone()
                if row:
                    states[key] = row[0]
    path = Path(queue_path or RenderQueue().path).resolve()
    if path.is_file():
        try:
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                for key in content_ids:
                    row = db.execute('SELECT status FROM jobs WHERE job_id=?', (key,)).fetchone()
                    if row:
                        states[key] = row[0]
        except sqlite3.Error:
            # 不把读取失败解释成“等待”或“成功”。
            return {key: 'RENDER_STATUS_UNAVAILABLE' for key in content_ids}
    return states
