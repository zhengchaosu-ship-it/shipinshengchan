"""备份专用互斥、持久失败退避及暂停账号兼容；不改变生产授权。"""
from contextlib import contextmanager, closing
from dataclasses import replace
from datetime import timedelta
import json
import logging
from pathlib import Path
import sqlite3

from startup_autopilot.models import Profile, aware
from yixiaoer_adapter.worker import write_json


@contextmanager
def backup_lock(root):
    import msvcrt
    root.mkdir(parents=True, exist_ok=True)
    with (root/'backup.lock').open('a+b') as handle:
        if handle.seek(0, 2) == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def profile_compatibility(folder):
    """只容许有持久暂停证据的安全降级，真正配置漂移仍拒绝验证。"""
    folder = Path(folder).resolve()
    notes = []
    with closing(sqlite3.connect((folder/'operations.db').as_uri()+'?mode=ro', uri=True)) as db, \
            closing(sqlite3.connect((folder/'account_assets.db').as_uri()+'?mode=ro', uri=True)) as assets:
        db.row_factory = sqlite3.Row
        has_runtime = db.execute("SELECT 1 FROM sqlite_master WHERE name='autopilot_account_runtime'").fetchone()
        for auth in db.execute('SELECT * FROM autopilot_authorizations WHERE enabled=1'):
            row = assets.execute('SELECT payload_json FROM shadow_profiles WHERE business_account_id=?', (auth['account_id'],)).fetchone()
            if not row:
                raise ValueError('BACKUP_ACTIVE_PROFILE_MISSING')
            profile = Profile(**json.loads(row[0])); profile.validate()
            if profile.enabled and profile.config_hash() == auth['config_hash']:
                continue
            runtime = db.execute('SELECT status FROM autopilot_account_runtime WHERE account_id=?', (auth['account_id'],)).fetchone() if has_runtime else None
            if runtime and runtime[0] in ('PAUSED_NEEDS_ATTENTION', 'OFF', 'BLOCKED') and not profile.enabled and 'config_json' in auth.keys():
                confirmed = Profile(**json.loads(auth['config_json'])); confirmed.validate()
                safe_profile = replace(profile, execution_mode=confirmed.execution_mode)
                if confirmed.config_hash() == auth['config_hash'] == safe_profile.config_hash():
                    notes.append({'account_id':auth['account_id'], 'runtime_status':runtime[0],
                                  'reason':'PAUSED_AUTHORIZATION_PRESERVED', 'dispatch_allowed':False})
                    continue
            raise ValueError('BACKUP_ACTIVE_PROFILE_MISMATCH')
    return notes


def guarded_backup(operations, *, force, now, verify):
    root = operations.root
    with backup_lock(root) as acquired:
        if not acquired:
            return {'state':'BACKUP_BUSY', 'verified':False}
        pause = root/'backup.pause.json'
        if pause.exists() and not force:
            control = json.loads(pause.read_text('utf-8'))
            if control.get('paused'):
                return {'state':'BACKUP_PAUSED', 'reason':control.get('reason', 'STORAGE_PROTECTION'), 'verified':False}
        journal = root/'backup.status.json'
        previous = json.loads(journal.read_text('utf-8')) if journal.exists() else {}
        latest = root/'backup.latest.json'

        def failed(reason, folder):
            count = int(previous.get('failure_count', 0)) + 1
            delay = min(21600, 900 * 2 ** min(count - 1, 5))
            record = {'state':'BACKUP_FAILED', 'reason':str(reason), 'folder':str(folder),
                      'failed_at':now.isoformat(), 'next_retry_at':(now+timedelta(seconds=delay)).isoformat(),
                      'failure_count':count, 'verified':False, 'retry_mode':'VERIFY_EXISTING_ONLY'}
            write_json(journal, record)
            write_json(root/'backup.alert.json', dict(record, severity='WARNING', scope='BACKUP', active=True))
            logging.error('BACKUP_FAILED: %s; retry existing snapshot after %ss', reason, delay)
            return record

        if previous.get('state') == 'BACKUP_IN_PROGRESS':
            return failed('BACKUP_PROCESS_INTERRUPTED', previous['folder'])
        if previous.get('state') == 'BACKUP_FAILED':
            if not force and now < aware(previous['next_retry_at']):
                return dict(previous, deferred=True)
            # 不重新复制整库；残缺副本必须由维护流程审阅，不能无限生成新批次。
            folder = Path(previous['folder']).resolve()
            if folder.parent != (root/'backups').resolve():
                raise ValueError('BACKUP_JOURNAL_PATH_INVALID')
            try:
                manifest = verify(folder)
                result = {'created_at':manifest['created_at'], 'folder':str(folder), 'verified':True}
            except Exception as error:
                return failed(error, folder)
        else:
            if not force and latest.exists():
                record = json.loads(latest.read_text('utf-8'))
                if now-aware(record['created_at']) < timedelta(seconds=operations.config.get('backup_interval_seconds',21600)):
                    return record
            folder = root/'backups'/now.strftime('%Y%m%dT%H%M%S%fZ')
            write_json(journal, {'state':'BACKUP_IN_PROGRESS','folder':str(folder),'started_at':now.isoformat()})
            try:
                result = operations._backup_snapshot(now=now)
            except Exception as error:
                return failed(error, folder)
        write_json(latest, result)
        write_json(journal, dict(result, state='COMPLETE', failure_count=0))
        write_json(root/'backup.alert.json', {'active':False,'state':'RESOLVED','scope':'BACKUP','at':now.isoformat()})
        return result
