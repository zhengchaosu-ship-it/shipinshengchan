"""账号运行态与用户长期授权分离；只暂停未来任务，保留所有提交事实。"""
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
import time
import re

PAUSED = 'PAUSED_NEEDS_ATTENTION'
TERMINAL = {'FAILED','FAILED_JOB_LEVEL','JOB_STALLED','NEEDS_ATTENTION','CANCELLED',
            'CANCELLED_BY_ACCOUNT_PAUSE','PUBLISHED','SCHEDULED_QUEUED',
            'SUBMIT_INTENT','SUBMITTED','SUBMIT_RESULT_UNCERTAIN'}
UNSTARTED = {'PLANNED','RENDER_PENDING','READY','READY_TO_DISPATCH','WAITING','READY_TO_PUBLISH',
             'WAITING_FOR_RENDER','WAITING_FOR_WORKSTATION','WAITING_ACCOUNT_RECOVERY',
             'RENDER_BACKLOG_PAUSED','PUBLISH_NETWORK_ATTENTION','WAITING_PUBLISHER_INFRA'}


def exists(db, table):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def migrate(db):
    statement = ''
    for line in (Path(__file__).parent/'migrations/004_fault_isolation.sql').read_text('utf-8').splitlines(True):
        statement += line
        if sqlite3.complete_statement(statement):
            db.execute(statement); statement = ''


def migrate_slots(db):
    """保留每一行和外键身份；只将slot唯一约束改为有效预留唯一。调用前需备份。"""
    row = db.execute("SELECT sql FROM sqlite_master WHERE name='autopilot_allocations'").fetchone()
    if not row or not re.search(r'UNIQUE\s*\(account_id\s*,\s*scheduled_at\)',row[0],re.I): return
    schema = re.sub(r',\s*UNIQUE\s*\(account_id\s*,\s*scheduled_at\)', '', row[0], flags=re.I)
    schema = schema.replace('autopilot_allocations','autopilot_allocations_fault_v3',1)
    db.execute('PRAGMA foreign_keys=OFF')
    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute(schema)
        db.execute('INSERT INTO autopilot_allocations_fault_v3 SELECT * FROM autopilot_allocations')
        db.execute('DROP TABLE autopilot_allocations')
        db.execute('ALTER TABLE autopilot_allocations_fault_v3 RENAME TO autopilot_allocations')
        db.execute("CREATE UNIQUE INDEX autopilot_active_slot ON autopilot_allocations(account_id,scheduled_at) WHERE state!='CANCELLED_BY_ACCOUNT_PAUSE'")
        db.execute('CREATE INDEX allocation_account_state ON autopilot_allocations(account_id,state,scheduled_at)')
        if db.execute('PRAGMA foreign_key_check').fetchall(): raise RuntimeError('ACCOUNT_SLOT_MIGRATION_INTEGRITY')
        db.commit()
    except BaseException:
        db.rollback(); raise
    finally:
        db.execute('PRAGMA foreign_keys=ON')


def scope(domain):
    return {'JOB_LEVEL':'JOB','ACCOUNT_LEVEL':'ACCOUNT','INFRA_LEVEL':'SYSTEM',
            'EXECUTOR':'SYSTEM'}.get(domain, domain if domain in ('JOB','ACCOUNT','SYSTEM') else 'JOB')


def runtime(db, account):
    if not exists(db, 'autopilot_account_runtime'): return None
    row = db.execute('SELECT * FROM autopilot_account_runtime WHERE account_id=?', (account,)).fetchone()
    return dict(row) if row else None


def allowed(db, account):
    row = runtime(db, account)
    if row and row['status'] in (PAUSED,'OFF','BLOCKED'): return False
    return True


def account_message(reason):
    reason = str(reason or 'ACCOUNT_PROVIDER_BLOCKED')
    auth = any(x in reason.upper() for x in ('AUTH','OFFLINE','LOGIN')) or '登录' in reason
    return ('账号登录已失效或离线' if auth else '平台要求账号验证或恢复发布权限',
            '在蚁小二恢复登录并刷新账号，随后点击“重新开启托管”。' if auth else
            '完成平台要求的人工验证，刷新账号状态后点击“重新开启托管”。')


def cancel_future(db, account, now):
    """只取消未开始、未提交的自动任务；重任务与历史终态逐项排除。"""
    if not exists(db, 'autopilot_allocations'): return 0
    changed = 0
    for raw in db.execute('SELECT * FROM autopilot_allocations WHERE account_id=?', (account,)).fetchall():
        row = dict(raw)
        if row['state'] not in UNSTARTED: continue
        try: at = datetime.fromisoformat(row['scheduled_at']).timestamp()
        except (ValueError,TypeError): continue
        if at <= now: continue
        jobs = []
        if exists(db, 'media_execution_jobs'):
            jobs = db.execute('SELECT * FROM media_execution_jobs WHERE content_id=?', (row.get('content_id'),)).fetchall()
        if any(j['submit_attempt_count'] or j['intent_json'] or j['state'] in TERMINAL for j in jobs): continue
        if exists(db, 'media_execution_leases') and any(db.execute(
                'SELECT 1 FROM media_execution_leases WHERE job_type=? AND job_id=?',
                (j['job_type'],j['job_id'])).fetchone() for j in jobs): continue
        if any(j['state'] not in UNSTARTED | {'COMPLETED'} for j in jobs): continue
        provider = None
        if row.get('job_id') and exists(db, 'provider_publish_jobs'):
            provider = db.execute('SELECT * FROM provider_publish_jobs WHERE job_id=?', (row['job_id'],)).fetchone()
            if provider and (provider['submit_attempt_count'] or provider['intent_json'] or provider['worker_id']
                             or provider['state'] in TERMINAL): continue
        at_text = datetime.fromtimestamp(now,timezone.utc).isoformat()
        db.execute("UPDATE autopilot_allocations SET state='CANCELLED_BY_ACCOUNT_PAUSE',error='ACCOUNT_RUNTIME_PAUSED',updated_at=? WHERE allocation_id=?",
                   (at_text,row['allocation_id']))
        for job in jobs:
            if job['state'] == 'COMPLETED': continue
            db.execute("UPDATE media_execution_jobs SET state='CANCELLED_BY_ACCOUNT_PAUSE' WHERE job_type=? AND job_id=?",
                       (job['job_type'],job['job_id']))
        if provider:
            db.execute("UPDATE provider_publish_jobs SET state='CANCELLED',updated_at=? WHERE job_id=?", (at_text,row['job_id']))
            db.execute("UPDATE publish_jobs SET status='CANCELLED',current_step='CANCELLED_BY_ACCOUNT_PAUSE',updated_at=? WHERE job_id=?",
                       (at_text,row['job_id']))
        changed += 1
    return changed


def pause(db, account, reason, *, now=None):
    now = time.time() if now is None else now
    if not exists(db, 'autopilot_account_runtime'): return False
    old = runtime(db, account)
    message, action = account_message(reason)
    if old and old['status']=='OFF':
        cancel_future(db,account,now)
        return False  # 用户关闭优先；账号恢复也不能改变这个选择。
    if not old or old['status'] != PAUSED:
        db.execute('INSERT INTO autopilot_account_runtime VALUES(?,?,?,?,?,?,NULL,?) '
                   'ON CONFLICT(account_id) DO UPDATE SET status=excluded.status,reason_code=excluded.reason_code,'
                   'human_message=excluded.human_message,action_required=excluded.action_required,'
                   'paused_at=excluded.paused_at,updated_at=excluded.updated_at',
                   (account,PAUSED,str(reason),message,action,now,now))
        fault(db,'ACCOUNT',account,None,str(reason),message,now)
    cancel_future(db,account,now)
    return True


def fault(db, domain, account, job, reason, message, now=None):
    if exists(db, 'production_faults'):
        db.execute('INSERT INTO production_faults(domain,account_id,job_id,reason_code,human_message,recorded_at) VALUES(?,?,?,?,?,?)',
                   (scope(domain),account,job,str(reason),message,time.time() if now is None else now))


def reconcile_accounts(db, now=None):
    now = time.time() if now is None else now
    if not exists(db,'media_account_publish_gates'): return
    if exists(db,'autopilot_authorizations'):
        for auth in db.execute("SELECT account_id FROM autopilot_authorizations WHERE enabled=0 AND status IN ('PAUSED','FINISHED')").fetchall():
            if runtime(db,auth['account_id']) is None:
                db.execute("INSERT INTO autopilot_account_runtime(account_id,status,updated_at) VALUES(?,'OFF',?)",(auth['account_id'],now))
    for row in db.execute('SELECT * FROM media_account_publish_gates').fetchall():
        if row['gate'] not in ('OPEN','CONDITIONAL_OPEN','PAUSED_BY_USER') or row['provider_account_status'] != 'ONLINE':
            pause(db,row['business_account_id'],row['block_reason'] or 'ACCOUNT_AUTH_EXPIRED',now=now)


def resume_check(db, account, now=None):
    """仅查询当前账号证据；不创建探测任务，也不因ONLINE自行解除风险门。"""
    now = time.time() if now is None else now
    from yixiaoer_adapter.storage import cached_binding
    binding = cached_binding(db,account,required=True)
    if not binding or not binding['provider_account_id']: raise PermissionError('Provider账号不存在')
    if exists(db,'production_health_snapshots'):
        sync = db.execute("SELECT * FROM production_health_snapshots WHERE component='Account Sync'").fetchone()
        if not sync or sync['state'] != 'OK': raise PermissionError('账号同步尚未恢复')
        at = sync['checked_at']
        age = now-(float(at) if isinstance(at,(int,float)) else datetime.fromisoformat(at).timestamp())
        if age >= 900: raise PermissionError('账号同步已过期，请刷新账号')
    if exists(db,'media_account_publish_gates'):
        gate = db.execute('SELECT * FROM media_account_publish_gates WHERE business_account_id=?',(account,)).fetchone()
        if not gate or gate['gate'] not in ('OPEN','CONDITIONAL_OPEN') or gate['provider_account_status'] != 'ONLINE':
            raise PermissionError(account_message(gate['block_reason'] if gate else None)[0])
    return True


def activate(db, account, now):
    db.execute("INSERT INTO autopilot_account_runtime(account_id,status,resumed_at,updated_at) VALUES(?,'ON',?,?) "
               "ON CONFLICT(account_id) DO UPDATE SET status='ON',reason_code=NULL,human_message=NULL,action_required=NULL,resumed_at=excluded.resumed_at,updated_at=excluded.updated_at",
               (account,now,now))
