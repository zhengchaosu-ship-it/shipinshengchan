"""Provider稳定身份的本地快照；同步只写账号与审计，从不启用托管。"""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from publish_planner.storage import PlannerStore


def at_now():
    return datetime.now(timezone.utc)


def exists(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='business_account_registry'").fetchone())


def provider_state(account):
    return 'ONLINE' if account.get('status') == 1 and not account.get('isFreeze') and not account.get('isLock') and account.get('isOperate', True) is not False else 'OFFLINE'


def fields(account):
    return str(account.get('platformAccountName') or account['id']), str(account.get('remark') or ''), str(account.get('status', 'UNKNOWN')), provider_state(account)


class BusinessAccountRegistry:
    def __init__(self, path=None):
        self.store = PlannerStore(path)

    def migrate(self):
        with self.store.connect() as db:
            if exists(db):
                return
            backup = self.store.path.with_name(self.store.path.name + '.account-registry-' + at_now().strftime('%Y%m%d%H%M%S%f') + '.bak')
            with closing(sqlite3.connect(backup)) as saved:
                db.backup(saved)
        with self.store.connect(write=True) as db:
            db.executescript('BEGIN IMMEDIATE;' + Path(__file__).with_name('migrations').joinpath('003_account_registry.sql').read_text('utf-8'))

    def state(self):
        with self.store.connect() as db:
            return dict(db.execute('SELECT * FROM account_sync_state WHERE id=1').fetchone()) if exists(db) else None

    def snapshot(self):
        with self.store.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM business_account_registry ORDER BY business_account_id')] if exists(db) else []

    def request_refresh(self):
        with self.store.connect(write=True) as db:
            if not exists(db):
                raise RuntimeError('ACCOUNT_SYNC_WORKER_NOT_INSTALLED')
            db.execute('UPDATE account_sync_state SET request_generation=request_generation+1 WHERE id=1')

    def begin(self, now=None):
        run_id = str(uuid4())
        with self.store.connect(write=True) as db:
            db.execute("INSERT INTO account_sync_runs(sync_run_id,started_at,state) VALUES(?,?,'RUNNING')", (run_id, (now or at_now()).isoformat()))
        return run_id

    def fail(self, run_id, code, *, generation=0, now=None):
        # 失败只更新审计与提示，不修改账号、绑定或上次成功快照。
        at = (now or at_now()).isoformat()
        with self.store.connect(write=True) as db:
            changed = db.execute("UPDATE account_sync_runs SET state='FAILED',finished_at=?,errors=1,error_code=? WHERE sync_run_id=? AND state='RUNNING'", (at, code, run_id)).rowcount
            if changed:
                db.execute('UPDATE account_sync_state SET last_error=?,last_attempt_at=?,completed_generation=MAX(completed_generation,?) WHERE id=1', (code, at, generation))

    def apply(self, accounts, *, run_id=None, generation=0, now=None, missing_limit=3, missing_ttl_seconds=900):
        now = now or at_now()
        run_id = run_id or self.begin(now)
        try:
            if not isinstance(accounts, list) or any(not isinstance(a, dict) for a in accounts):
                raise ValueError('ACCOUNT_LIST_INVALID')
            rows = [a for a in accounts if a.get('platformName') == '抖音']
            by_id = {}
            for a in rows:
                key = a.get('id')
                if not isinstance(key, str) or not key.strip() or key != key.strip() or key in by_id:
                    raise ValueError('PROVIDER_STABLE_ID_INVALID_OR_DUPLICATE')
                if 'status' not in a:
                    raise ValueError('PROVIDER_STATUS_MISSING')
                by_id[key] = a
            at = now.isoformat()
            counts = dict(provider_accounts_seen=len(rows), created=0, updated=0, unchanged=0, offline=0, missing=0, errors=0)
            with self.store.connect(write=True) as db:
                run = db.execute('SELECT * FROM account_sync_runs WHERE sync_run_id=?', (run_id,)).fetchone()
                if run and run['state'] == 'SUCCEEDED':
                    return {k: run[k] for k in ('sync_run_id', *counts.keys())}
                if not run or run['state'] != 'RUNNING':
                    raise ValueError('SYNC_RUN_ALREADY_FINISHED_OR_UNKNOWN')
                # 采用既有稳定映射，原业务ID、分组、模板、历史全部保留。
                for b in db.execute("SELECT b.*,a.display_name FROM provider_account_bindings b JOIN xiaovcat_accounts a ON a.account_id=b.business_account_id WHERE b.provider='yixiaoer' AND b.platform='douyin'").fetchall():
                    if db.execute('SELECT 1 FROM business_account_registry WHERE provider_account_id=?', (b['provider_account_id'],)).fetchone():
                        continue
                    raw = json.loads(b['raw_account_json'])
                    name, remark, status, _ = fields(dict(raw, id=b['provider_account_id']))
                    first = b['provider_last_verified_at'] or at
                    db.execute('''INSERT INTO business_account_registry(business_account_id,provider,platform,provider_account_id,business_display_name,
                        provider_display_name,provider_remark,provider_status,provider_binding_status,provider_first_seen_at,provider_last_seen_at,mapping_source,raw_account_json,initial_startup_profile_status)
                        VALUES(?,'yixiaoer','douyin',?,?,?,?,?,?,?,?,'HISTORICAL_STABLE_ID',?,'LEGACY_PROFILE_UNCHANGED')''',
                        (b['business_account_id'], b['provider_account_id'], b['display_name'], name, remark, status, b['provider_account_status'], first, first, b['raw_account_json']))
                def change(business, provider, event, previous, current):
                    db.execute('INSERT INTO account_sync_changes(sync_run_id,business_account_id,provider_account_id,event,previous_json,current_json) VALUES(?,?,?,?,?,?)',
                        (run_id, business, provider, event, json.dumps(previous, ensure_ascii=False) if previous else None, json.dumps(current, ensure_ascii=False)))
                for key, a in by_id.items():
                    old_row = db.execute('SELECT * FROM business_account_registry WHERE provider_account_id=?', (key,)).fetchone()
                    old = dict(old_row) if old_row else None
                    name, remark, status, binding = fields(a)
                    raw = json.dumps(a, ensure_ascii=False)
                    current = dict(provider_display_name=name, provider_remark=remark, provider_status=status, provider_binding_status=binding)
                    if old is None:
                        business = 'YXER-DY-' + key
                        if db.execute('SELECT 1 FROM xiaovcat_accounts WHERE account_id=?', (business,)).fetchone():
                            raise ValueError('BUSINESS_ACCOUNT_ID_COLLISION')
                        evidence = json.dumps(dict(source='PROVIDER_AUTO_SYNC', provider_account_id=key), ensure_ascii=False)
                        # group_id为空；仅本地工作室从Registry识别，不自动授予员工组权限。
                        db.execute('''INSERT INTO xiaovcat_accounts(account_id,display_name,platform,online_status,is_available,is_active,last_synced_at,identity_evidence)
                            VALUES(?,?,'抖音',?,?,1,?,?)''', (business, name, binding, int(binding == 'ONLINE'), at, evidence))
                        db.execute("INSERT INTO provider_account_bindings VALUES(?,'douyin','yixiaoer',?,?,?,?)", (business, key, binding, at, raw))
                        db.execute('''INSERT INTO business_account_registry(business_account_id,provider,platform,provider_account_id,business_display_name,
                            provider_display_name,provider_remark,provider_status,provider_binding_status,provider_first_seen_at,provider_last_seen_at,mapping_source,raw_account_json)
                            VALUES(?,'yixiaoer','douyin',?,?,?,?,?,?,?,?,'PROVIDER_AUTO_SYNC',?)''',
                            (business, key, name, name, remark, status, binding, at, at, raw))
                        counts['created'] += 1
                        change(business, key, 'NEW', None, current)
                    else:
                        business = old['business_account_id']
                        mapped = db.execute("SELECT business_account_id FROM provider_account_bindings WHERE provider='yixiaoer' AND provider_account_id=?", (key,)).fetchall()
                        if len(mapped) != 1 or mapped[0][0] != business:
                            raise ValueError('PROVIDER_MAPPING_CONFLICT')
                        events = []
                        if old['provider_display_name'] != name or old['provider_remark'] != remark:
                            events.append('DISPLAY_NAME_CHANGED')
                        if old['provider_binding_status'] in ('OFFLINE', 'MISSING_FROM_PROVIDER', 'DISCONNECTED') and binding == 'ONLINE':
                            events.append('RECONNECTED')
                        if old['provider_status'] != status or old['provider_binding_status'] != binding:
                            events.append('STATUS_CHANGED')
                        counts['updated' if events else 'unchanged'] += 1
                        for event in events:
                            change(business, key, event, {k: old[k] for k in current}, current)
                        db.execute('''UPDATE business_account_registry SET provider_display_name=?,provider_remark=?,provider_status=?,provider_binding_status=?,
                            provider_last_seen_at=?,missing_count=0,missing_since=NULL,raw_account_json=? WHERE business_account_id=?''', (name, remark, status, binding, at, raw, business))
                        db.execute("UPDATE provider_account_bindings SET provider_account_status=?,provider_last_verified_at=?,raw_account_json=? WHERE business_account_id=? AND provider='yixiaoer'", (binding, at, raw, business))
                    counts['offline'] += int(binding == 'OFFLINE')
                for old_row in db.execute('SELECT * FROM business_account_registry').fetchall():
                    old = dict(old_row)
                    if old['provider_account_id'] in by_id:
                        continue
                    missing = old['missing_count'] + 1
                    since = old['missing_since'] or at
                    elapsed = (now - datetime.fromisoformat(old['provider_last_seen_at'])).total_seconds()
                    status = 'DISCONNECTED' if missing >= missing_limit or elapsed >= missing_ttl_seconds else 'MISSING_FROM_PROVIDER'
                    db.execute('UPDATE business_account_registry SET missing_count=?,missing_since=?,provider_binding_status=? WHERE business_account_id=?', (missing, since, status, old['business_account_id']))
                    db.execute("UPDATE provider_account_bindings SET provider_account_status=? WHERE business_account_id=? AND provider='yixiaoer'", (status, old['business_account_id']))
                    change(old['business_account_id'], old['provider_account_id'], 'MISSING', {'status': old['provider_binding_status']}, {'status': status, 'missing_count': missing})
                    counts['missing'] += 1
                db.execute("UPDATE account_sync_runs SET state='SUCCEEDED',finished_at=?," + ','.join(k + '=?' for k in counts) + ' WHERE sync_run_id=?', (at, *counts.values(), run_id))
                db.execute('UPDATE account_sync_state SET last_success_at=?,revision=revision+1,last_error=NULL,last_attempt_at=?,completed_generation=MAX(completed_generation,?) WHERE id=1', (at, at, generation))
            return dict(sync_run_id=run_id, **counts)
        except Exception as error:
            self.fail(run_id, type(error).__name__ + ':' + str(error), generation=generation, now=now)
            raise


def enrich_snapshot(db, accounts):
    if not exists(db):
        return accounts
    registry = {r['business_account_id']: dict(r) for r in db.execute('SELECT * FROM business_account_registry')}
    for a in accounts:
        row = registry.get(a['account_id'])
        a['business_display_name'] = a['display_name']
        if row:
            a.update({k: row[k] for k in ('provider_display_name', 'provider_remark', 'provider_status', 'provider_binding_status', 'mapping_source', 'provider_first_seen_at', 'provider_last_seen_at', 'initial_startup_profile_status')})
            a['display_name'] = row['provider_remark'] or row['provider_display_name'] or row['business_display_name']
        else:
            a['provider_binding_status'] = a.get('provider_account_status', 'UNBOUND')
    return accounts
