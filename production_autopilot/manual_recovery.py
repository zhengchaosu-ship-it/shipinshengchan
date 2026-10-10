"""人工恢复确认：同库原子生效＋可靠事件；不Probe、不创建任务、不发布。"""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib
import json
import sqlite3
import time
from .account_runtime import exists, runtime

ALLOWED_GATES={'OPEN','CONDITIONAL_OPEN'}


def encoded(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(value):return hashlib.sha256(value.encode()).hexdigest()


def migrate(db):
    sql=(Path(__file__).parent/'migrations/006_manual_recovery_ack.sql').read_text('utf-8')
    fingerprint=digest(sql)
    if exists(db,'account_manual_recovery_schema'):
        old=db.execute('SELECT sql_sha256 FROM account_manual_recovery_schema WHERE version=6').fetchone()
        if old:
            if old[0]!=fingerprint:raise ValueError('MANUAL_RECOVERY_MIGRATION_HASH_MISMATCH')
            return
    statement=''
    for line in sql.splitlines(True):
        statement+=line
        if sqlite3.complete_statement(statement):db.execute(statement);statement=''
    if statement.strip():raise ValueError('MANUAL_RECOVERY_SQL_INCOMPLETE')
    db.execute('INSERT INTO account_manual_recovery_schema VALUES(6,?)',(fingerprint,))


def version(db, account):
    from .account_recovery import generation
    state=list(generation(db,account))
    # Job级超时允许只读核对成功；只有新的账号风险会使恢复确认过期。
    state[-1]=db.execute("SELECT max(id) FROM production_faults WHERE account_id=? AND domain='ACCOUNT'",(account,)).fetchone()[0] if exists(db,'production_faults') else None
    return encoded(state)


def record_probe_version(db, check_id, account):
    db.execute('INSERT OR REPLACE INTO account_recovery_probe_versions VALUES(?,?,?)',(check_id,account,version(db,account)))


def current_ack(db, account):
    if not exists(db,'account_manual_recovery_acks'):return None
    row=db.execute('SELECT * FROM account_manual_recovery_acks WHERE business_account_id=? ORDER BY manual_recovery_ack_at DESC,rowid DESC LIMIT 1',(account,)).fetchone()
    return dict(row) if row else None


def next_future_slot(profile, now, *, service, db, account):
    from startup_autopilot.models import SHANGHAI,aware
    first=now.astimezone(SHANGHAI).date()
    for offset in (0,1):
        day=first+timedelta(days=offset)
        if service.occupancy(db,account,day.isoformat())>=profile.daily_publish_limit:continue
        occupied={aware(r[0]) for r in db.execute("SELECT scheduled_at FROM autopilot_allocations WHERE account_id=? AND state!='CANCELLED_BY_ACCOUNT_PAUSE'",(account,))}
        occupied.update(aware(r[0]) for r in db.execute("SELECT i.scheduled_at FROM publish_plan_items i JOIN publish_jobs j USING(job_id) WHERE i.account_id=? AND j.status!='CANCELLED'",(account,)))
        choices=[aware(day.isoformat()+'T'+t+':00+08:00') for t in profile.publish_times]
        future=[t for t in choices if t>now and t>=now+timedelta(seconds=8100) and t not in occupied]
        if future:return min(future).isoformat()
    return None


def current_result(db, ack, *, replayed, next_slot=None):
    rt=runtime(db,ack['business_account_id']) or {}
    gate=db.execute('SELECT gate FROM media_account_publish_gates WHERE business_account_id=?',(ack['business_account_id'],)).fetchone()
    return {'manual_recovery_ack_id':ack['manual_recovery_ack_id'],'manual_recovery_ack_at':ack['manual_recovery_ack_at'],
        'business_account_id':ack['business_account_id'],'gate':gate[0] if gate else None,
        'runtime_status':rt.get('status'),'resumed':rt.get('status')=='ACTIVE','replayed':replayed,
        'next_slot':next_slot if rt.get('status')=='ACTIVE' else None,'publish_calls':0,'jobs_created':0}


def acknowledge(service, token, account, check_id, *, explicit=False, now=None):
    if explicit is not True:raise PermissionError('EXPLICIT_MANUAL_RECOVERY_ACK_REQUIRED')
    actor=service.actor(token);actor.require(account)
    at=now or datetime.now(timezone.utc);stamp=at.timestamp()
    from .account_recovery import latest,evaluate
    from startup_autopilot.production import ServiceGrant
    with service.planner.connect(write=True) as db:
        service.planner._principal(db,token)
        migrate(db)
        prior=db.execute('SELECT * FROM account_manual_recovery_acks WHERE check_id=?',(check_id,)).fetchone()
        if prior:
            if prior['business_account_id']!=account:raise PermissionError('ACK_ACCOUNT_MISMATCH')
            # 重放不会再verify/恢复；用户OFF或后续风险优先。
            return current_result(db,dict(prior),replayed=True)
        check=latest(db,account)
        if not check or check['check_id']!=check_id or check['state']!='UNKNOWN':
            raise PermissionError('LATEST_UNKNOWN_PROBE_REQUIRED')
        if evaluate(check.get('probe_evidence',{}).get('signals',{}))[0]=='STILL_BLOCKED':
            raise PermissionError('CURRENT_PROVIDER_BLOCKER_NOT_OVERRIDABLE')
        captured=db.execute('SELECT generation_json FROM account_recovery_probe_versions WHERE check_id=? AND account_id=?',(check_id,account)).fetchone()
        before=version(db,account)
        if not captured or captured[0]!=before:raise PermissionError('RECOVERY_STATE_CHANGED_RECHECK_REQUIRED')
        rt=runtime(db,account)
        gate=db.execute('SELECT * FROM media_account_publish_gates WHERE business_account_id=?',(account,)).fetchone()
        auth=db.execute('SELECT * FROM autopilot_authorizations WHERE account_id=?',(account,)).fetchone()
        if not rt or rt['status']!='PAUSED_NEEDS_ATTENTION' or not gate or gate['gate'] not in ('BLOCKED_RISK','BLOCKED_AUTH','BLOCKED_MANUAL_ACTION'):
            raise PermissionError('PAUSED_ACCOUNT_RISK_REQUIRED')
        if not auth or auth['status'] in ('PAUSED','FINISHED') or gate['provider_account_status']!='ONLINE':
            raise PermissionError('USER_OFF_OR_ACCOUNT_OFFLINE')
        _,_,_,profile,_=service.verify(db,ServiceGrant(account,auth['config_hash']),require_enabled=False)
        if check['provider_account_id']!=auth['provider_account_id']:raise PermissionError('PROVIDER_BINDING_CHANGED')
        ack_id='MANUAL-RECOVERY-'+digest(encoded([account,check_id]))
        db.execute("UPDATE media_account_publish_gates SET gate='CONDITIONAL_OPEN',block_reason=NULL,provider_error=NULL,first_seen_at=NULL,checked_at=? WHERE business_account_id=?",(stamp,account))
        db.execute("UPDATE autopilot_account_runtime SET status='ACTIVE',reason_code=NULL,human_message=NULL,action_required=NULL,resumed_at=?,updated_at=? WHERE account_id=?",(stamp,stamp,account))
        db.execute("UPDATE autopilot_authorizations SET enabled=1,status=CASE WHEN status='ATTENTION_REQUIRED' THEN ? ELSE status END,attention_reason=NULL,updated_at=? WHERE account_id=?",(profile.status,at.isoformat(),account))
        after=version(db,account)
        result={'manual_recovery_ack_id':ack_id,'manual_recovery_ack_at':stamp,'business_account_id':account,
            'previous_block_reason':gate['block_reason'] or rt.get('reason_code'),'probe_result':'UNKNOWN',
            'gate':'CONDITIONAL_OPEN','runtime_status':'ACTIVE','next_slot':next_future_slot(profile,at,service=service,db=db,account=account),'resumed':True,
            'replayed':False,'publish_calls':0,'jobs_created':0}
        db.execute('INSERT INTO account_manual_recovery_acks VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (ack_id,check_id,stamp,account,auth['provider_account_id'],actor.employee_id,result['previous_block_reason'],'UNKNOWN',before,after,encoded(result)))
        payload=encoded({'account_id':account,'manual_recovery_ack_id':ack_id,'generation_after_json':after,'gate':'CONDITIONAL_OPEN','runtime_status':'ACTIVE'})
        key='manual_recovery_ack:'+ack_id
        db.execute('INSERT INTO server_outbox(event_id,event_type,aggregate_id,idempotency_key,payload_json,payload_sha256,created_at) VALUES(?,?,?,?,?,?,?)',
            (digest(key),'ACCOUNT_RUNTIME_CHANGE',account,key,payload,digest(payload),stamp))
        service.event(db,account,actor.employee_id,'ACCOUNT_MANUAL_RECOVERY_ACKNOWLEDGEMENT',result)
        return result


def drain_outbox(planner, *, now=None, limit=20):
    """仅消费人工恢复投影事件；运行态已同库提交，重放绝不能再次恢复或规划。"""
    now=time.time() if now is None else now
    with planner.connect(write=True) as db:
        if not exists(db,'account_manual_recovery_acks'):return 0
        rows=db.execute("SELECT * FROM server_outbox WHERE event_type='ACCOUNT_RUNTIME_CHANGE' AND idempotency_key LIKE 'manual_recovery_ack:%' AND processed_at IS NULL ORDER BY created_at,event_id LIMIT ?",(limit,)).fetchall()
        for row in rows:
            from .record_quarantine import object_json,record
            try:
                if digest(row['payload_json'])!=row['payload_sha256']:raise ValueError('MANUAL_RECOVERY_OUTBOX_HASH_MISMATCH')
                payload=object_json(row['payload_json']);account=row['aggregate_id']
                if payload['account_id']!=account or not payload['manual_recovery_ack_id']:raise ValueError('OUTBOX_ACCOUNT_MISMATCH')
            except (ValueError,TypeError,KeyError):
                record(db,'server_outbox',row['event_id'],row['payload_json'],now)
                db.execute("UPDATE server_outbox SET processed_at=?,last_error='QUARANTINED_INVALID_CONTRACT' WHERE event_id=?",(now,row['event_id']))
                continue
            old=db.execute("SELECT payload_sha256 FROM server_action_inbox WHERE consumer='MANUAL_RECOVERY_RUNTIME' AND event_id=?",(row['event_id'],)).fetchone()
            if old and old[0]!=row['payload_sha256']:raise ValueError('OUTBOX_INBOX_HASH_MISMATCH')
            if not old:
                ack=current_ack(db,account)
                # 旧确认事件不得覆盖后来OFF/新风险；投影读取当前事实。
                if ack and ack['manual_recovery_ack_id']==payload['manual_recovery_ack_id']:
                    current=current_result(db,ack,replayed=True)
                    db.execute('INSERT INTO account_manual_recovery_projection VALUES(?,?,?,?) ON CONFLICT(business_account_id) DO UPDATE SET manual_recovery_ack_id=excluded.manual_recovery_ack_id,state_json=excluded.state_json,updated_at=excluded.updated_at',
                        (account,ack['manual_recovery_ack_id'],encoded(current),now))
                db.execute('INSERT INTO server_action_inbox VALUES(?,?,?,?)',('MANUAL_RECOVERY_RUNTIME',row['event_id'],row['payload_sha256'],now))
            db.execute('UPDATE server_outbox SET processed_at=?,attempt_count=attempt_count+1,last_error=NULL WHERE event_id=?',(now,row['event_id']))
        return len(rows)


def bind_submit_intent(db, job, now):
    ack=current_ack(db,job['business_account_id'])
    if not ack:return
    gate=db.execute('SELECT gate FROM media_account_publish_gates WHERE business_account_id=?',(job['business_account_id'],)).fetchone()
    if gate and gate[0]=='CONDITIONAL_OPEN' and version(db,job['business_account_id'])==ack['generation_after_json']:
        db.execute('INSERT INTO account_manual_recovery_submit_links VALUES(?,?,?) ON CONFLICT(job_id) DO NOTHING',(job['job_id'],ack['manual_recovery_ack_id'],now))


def provider_risk(response):
    from media_execution.coordinator import classify_failure,ExecutionFailure
    failure=classify_failure(RuntimeError(encoded(response or {})))
    if failure.domain=='ACCOUNT_LEVEL':return failure
    text=encoded(response or {})
    if any(word in text for word in ('ACCOUNT_PUBLISH_DENIED','ACCOUNT_AUTH_REQUIRED','VERIFICATION_REQUIRED','PUBLISH_PERMISSION_DENIED','需要验证','授权失效','当前不可发布')):
        return ExecutionFailure('ACCOUNT_LEVEL','ACCOUNT_PUBLISH_DENIED',gate='BLOCKED_RISK')
    return None


def observe_success(db, job, response, now):
    if response.get('state') not in ('SUBMITTED','SCHEDULED_QUEUED') or not response.get('provider_task_id'):return False
    if not exists(db,'account_manual_recovery_submit_links'):return False
    if provider_risk(response.get('provider_response',{})):return False
    link=db.execute('SELECT * FROM account_manual_recovery_submit_links WHERE job_id=?',(job['job_id'],)).fetchone()
    ack=current_ack(db,job['business_account_id'])
    if not link or not ack or link['manual_recovery_ack_id']!=ack['manual_recovery_ack_id']:return False
    if version(db,job['business_account_id'])!=ack['generation_after_json']:return False
    gate=db.execute('SELECT gate FROM media_account_publish_gates WHERE business_account_id=?',(job['business_account_id'],)).fetchone()
    rt=runtime(db,job['business_account_id']) or {}
    if not gate or gate[0]!='CONDITIONAL_OPEN' or rt.get('status')!='ACTIVE':return False
    if json.loads(job['payload_json']).get('provider_account_id')!=ack['provider_account_id']:return False
    db.execute('INSERT INTO account_manual_recovery_outcomes VALUES(?,?,?,?,?) ON CONFLICT(manual_recovery_ack_id) DO NOTHING',
        (ack['manual_recovery_ack_id'],job['job_id'],now,'recovery_confirmed_by_successful_submission',encoded(response)))
    db.execute("UPDATE media_account_publish_gates SET gate='OPEN',checked_at=? WHERE business_account_id=?",(now,job['business_account_id']))
    db.execute("INSERT INTO media_execution_events(at,job_type,job_id,event,evidence_json) VALUES(?,'PUBLISH',?,'recovery_confirmed_by_successful_submission',?)",(now,job['job_id'],encoded({'manual_recovery_ack_id':ack['manual_recovery_ack_id']})))
    db.execute("INSERT INTO media_execution_events(at,job_type,job_id,event,evidence_json) VALUES(?,'PUBLISH',?,'RECOVERY_CONFIRMED_BY_NORMAL_PRODUCTION',?)",(now,job['job_id'],encoded({'manual_recovery_ack_id':ack['manual_recovery_ack_id']})))
    return True


def mark_reblocked(db, account, reason, now):
    ack=current_ack(db,account)
    if ack:
        db.execute('INSERT INTO account_manual_recovery_outcomes VALUES(?,NULL,?,?,?) ON CONFLICT(manual_recovery_ack_id) DO NOTHING',
            (ack['manual_recovery_ack_id'],now,'ACCOUNT_RISK_REBLOCKED',encoded({'reason':reason})))


def startup_check(db):
    required={'account_manual_recovery_schema','account_recovery_probe_versions','account_manual_recovery_acks',
        'account_manual_recovery_submit_links','account_manual_recovery_outcomes','account_manual_recovery_projection','server_outbox','server_action_inbox','server_record_quarantine'}
    missing=sorted(name for name in required if not exists(db,name))
    if missing:return {'planner':'PAUSED_SYSTEM','reason_codes':['MANUAL_RECOVERY_MIGRATION_MISSING'],'missing':missing}
    checksum=digest((Path(__file__).parent/'migrations/006_manual_recovery_ack.sql').read_text('utf-8'))
    row=db.execute('SELECT sql_sha256 FROM account_manual_recovery_schema WHERE version=6').fetchone()
    return {'planner':'READY' if row and row[0]==checksum else 'PAUSED_SYSTEM','reason_codes':[] if row and row[0]==checksum else ['MANUAL_RECOVERY_SCHEMA_MISMATCH']}
