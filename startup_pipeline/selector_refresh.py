"""起号页仅刷新当前员工STARTUP组的可见账号快照，不改变任何账号权限。"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import subprocess
import uuid

from publish_planner.storage import ROOT
from xiaovcat_adapter.group_sync import persist_group_snapshot
from xiaovcat_adapter.models import utc_now_iso


def authorized_groups(store, token):
    with store.connect() as db:
        actor = store._principal(db, token)
        return [dict(r) for r in db.execute(
            "SELECT g.group_id,g.source_group_id,g.identity_status,g.last_synced_at "
            "FROM employee_group_bindings b JOIN xiaovcat_groups g USING(group_id) "
            "WHERE b.employee_id=? AND b.group_role='STARTUP' AND b.enabled=1 AND g.is_active=1 "
            "ORDER BY g.group_id", (actor['employee_id'],))]


def snapshot_state(store, token):
    groups = authorized_groups(store, token)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    dates = []
    stale = False
    with store.connect() as db:
        for group in groups:
            rows = db.execute('SELECT last_synced_at FROM xiaovcat_accounts WHERE group_id=? AND is_active=1',
                              (group['group_id'],)).fetchall()
            if not rows:
                stale = True
            for row in rows:
                try:
                    date = datetime.fromisoformat(row[0])
                    if date.tzinfo is None:
                        raise ValueError('MISSING_TIMEZONE')
                    dates.append(date)
                    stale = stale or date < cutoff
                except (TypeError, ValueError):
                    stale = True
    return {'group_ids':[g['group_id'] for g in groups], 'needs_refresh':bool(groups) and stale,
            'last_synced_at':min(dates).astimezone().strftime('%Y-%m-%d %H:%M:%S') if dates else None}


@contextmanager
def _sync_lock(path):
    # 同一桌面只允许一个快照读取，不让多浏览器请求交错操作小V猫。
    import msvcrt
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if path.stat().st_size == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise RuntimeError('ACCOUNT_SYNC_BUSY') from error
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def read_group(group_id, expected_ids, results, *, capture_screenshots=True):
    python = json.loads((ROOT/'config.json').read_text(encoding='utf-8'))['paths']['python_executable']
    args = [python,'-X','utf8','-B','-m','startup_pipeline.selector_sync_reader','--group-id',group_id,'--results',str(results)]
    if not capture_screenshots:args.append('--no-screenshots')
    for account_id in sorted(expected_ids):
        args.extend(['--expected-account-id',account_id])
    with _sync_lock(ROOT/'startup_pipeline/runtime/selector_refresh/ui_sync.lock'):
        done = subprocess.run(args,cwd=ROOT,capture_output=True,timeout=120,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    results.mkdir(parents=True,exist_ok=True)
    (results/'reader.log').write_bytes(done.stdout+done.stderr)
    if done.returncode:
        detail = done.stderr.decode('utf-8',errors='replace')[-800:]
        raise RuntimeError('ACCOUNT_SYNC_FAILED: '+detail)
    return json.loads((results/'LIVE_SYNC.json').read_text(encoding='utf-8'))


class _SnapshotWriter:
    """服务内部的限定快照写入：员工只能刷新自己已绑定组的既有稳定ID。

    原Planner管理员同步入口保持不变；此入口不创建身份或赋权，不接收浏览器快照。
    """
    def __init__(self, store, token, group_id, expected_ids):
        self.store,self.token,self.group_id,self.expected_ids = store,token,group_id,set(expected_ids)

    def connect(self):
        return self.store.connect()

    def sync_snapshot(self, snapshot, *, session_token):
        if session_token != self.token or {a['group_id'] for a in snapshot['accounts']} != {self.group_id}:
            raise PermissionError('ACCOUNT_PERMISSION_DENIED')
        now = utc_now_iso()
        with self.store.connect(write=True) as db:
            actor = self.store._principal(db,self.token)
            bound = db.execute("SELECT 1 FROM employee_group_bindings WHERE employee_id=? AND group_id=? "
                "AND group_role='STARTUP' AND enabled=1",(actor['employee_id'],self.group_id)).fetchone()
            if not bound:
                raise PermissionError('ACCOUNT_PERMISSION_DENIED')
            ids = {r[0] for r in db.execute('SELECT account_id FROM xiaovcat_accounts WHERE group_id=? AND is_active=1',
                                          (self.group_id,))}
            if ids != self.expected_ids:
                raise RuntimeError('ACCOUNT_ID_MISMATCH')
            for row in snapshot['accounts']:
                changed = db.execute('UPDATE xiaovcat_accounts SET display_name=?,platform=?,online_status=?,'
                    'is_available=?,last_synced_at=?,identity_evidence=? WHERE account_id=? AND group_id=? AND is_active=1',
                    (row['display_name'],row['platform'],row['online_status'],int(row['is_available']),now,
                     row['identity_evidence'],row['account_id'],self.group_id))
                if changed.rowcount != 1:
                    raise RuntimeError('ACCOUNT_ID_MISMATCH')
            db.execute('UPDATE xiaovcat_groups SET last_synced_at=? WHERE group_id=?',(now,self.group_id))
            db.execute('INSERT INTO group_sync_runs VALUES(?,?,?)',
                (snapshot['run_id'],now,json.dumps(snapshot,ensure_ascii=False)))
        return {'group_id':self.group_id,'saved_accounts':len(snapshot['accounts']),'last_synced_at':now}


def refresh_startup_accounts(store, token, *, reader=None, results=None):
    groups = authorized_groups(store,token)
    if not groups:
        raise PermissionError('NO_AUTHORIZED_STARTUP_GROUP')
    output = Path(results or ROOT/'startup_pipeline/runtime/selector_refresh'/uuid.uuid4().hex)
    refreshed = []
    for group in groups:
        if group['identity_status'] != 'SOURCE_ID' or group['source_group_id'] != group['group_id']:
            raise RuntimeError('GROUP_ID_NOT_VERIFIED')
        with store.connect() as db:
            ids = {r[0] for r in db.execute('SELECT account_id FROM xiaovcat_accounts WHERE group_id=? AND is_active=1',
                                          (group['group_id'],))}
        if not ids:
            raise RuntimeError('STABLE_ACCOUNT_BASELINE_REQUIRED')
        snapshot = (reader or read_group)(group['group_id'],ids,output/group['group_id'])
        writer = _SnapshotWriter(store,token,group['group_id'],ids)
        refreshed.append(persist_group_snapshot(writer,token,snapshot,group['group_id'],ids))
    return {'groups':refreshed}
