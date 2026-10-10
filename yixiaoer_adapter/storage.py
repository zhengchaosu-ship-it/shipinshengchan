"""Provider映射、正式状态与持久化闩锁；现有业务主键和历史行保持不变。"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3

from xiaovcat_adapter.models import utc_now_iso

STATES = {'READY_TO_DISPATCH', 'UPLOADING', 'PROVIDER_VALIDATED', 'SUBMIT_INTENT',
          'SUBMITTED', 'SCHEDULED_QUEUED', 'PUBLISHED', 'FAILED', 'SUBMIT_RESULT_UNCERTAIN', 'CANCELLED', 'ATTENTION_REQUIRED'}
MIN_SAFE_LEAD_SECONDS = 8100
MAX_HORIZON_SECONDS = 14 * 86400


def file_sha(path):
    with open(path, 'rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def schedule_gate(scheduled_at, now=None):
    now = now or datetime.now(timezone.utc)
    selected = datetime.fromisoformat(scheduled_at)
    if selected.tzinfo is None:
        raise ValueError('DOUYIN_SCHEDULE_TIMEZONE_REQUIRED')
    seconds = (selected-now).total_seconds()
    if seconds < MIN_SAFE_LEAD_SECONDS:
        raise ValueError('DOUYIN_SCHEDULE_TOO_SOON')
    if seconds > MAX_HORIZON_SECONDS:
        raise ValueError('DOUYIN_SCHEDULE_TOO_FAR')
    return int(selected.timestamp() * 1000)


def enabled(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='yixiaoer_settings'").fetchone():
        return False
    row = db.execute("SELECT value FROM yixiaoer_settings WHERE key='enabled'").fetchone()
    return bool(row and row[0] == 'true')


def production_enabled(db):
    if not enabled(db):
        return False
    settings=dict(db.execute('SELECT key,value FROM yixiaoer_settings'))
    try:
        proof=json.loads(settings.get('canary_pass','{}'))
    except ValueError:
        return False
    return settings.get('production_enabled')=='true' and proof.get('result')=='YIXIAOER_8502_PRODUCTION_CANARY_PASS'


def confirm_scope(db, plan, employee_id, content_ids):
    """新用户Confirm只能授权已准备且身份一致的预览；旧CONFIRMED不被采用。"""
    canary=db.execute('SELECT * FROM yixiaoer_canary_plans WHERE plan_id=? AND employee_id=?',(plan.plan_id,employee_id)).fetchone()
    if canary and len(content_ids)==3 and set(json.loads(canary['content_ids_json']))==set(content_ids):
        return
    if not production_enabled(db):
        raise PermissionError('YIXIAOER_CANARY_REQUIRED_BEFORE_PRODUCTION_OPEN')
    preview=db.execute('SELECT * FROM provider_production_previews WHERE plan_id=? AND employee_id=?',(plan.plan_id,employee_id)).fetchone()
    if (not preview or json.loads(preview['content_ids_json'])!=list(content_ids)
        or json.loads(preview['payload_json'])!=json.loads(plan.payload())):
        raise PermissionError('YIXIAOER_PRODUCTION_PREVIEW_REQUIRED')
    preparation=json.loads(preview['preparation_json'])
    for item in preparation['files']:
        from media_execution.integration import output_for
        remote=output_for(db,item.get('content_id'),path=item['video_path'])
        if remote:
            valid=(remote['local_output_path']==item['video_path'] and remote['output_sha256']==item['sha256']
                and remote['media']['cover_path']==item['cover_path'] and remote['media']['cover_sha256']==item['cover_sha256'])
        else:valid=file_sha(item['video_path'])==item['sha256'] and file_sha(item['cover_path'])==item['cover_sha256']
        if not valid:
            raise PermissionError('YIXIAOER_PREPARED_MEDIA_CHANGED')


def cached_binding(db, account_id, *, required=False, now=None):
    row = db.execute("SELECT * FROM provider_account_bindings WHERE business_account_id=? AND provider='yixiaoer'", (account_id,)).fetchone()
    row = dict(row) if row else None
    from .account_registry import exists
    if row and exists(db):
        snapshot = db.execute('SELECT * FROM business_account_registry WHERE business_account_id=?', (account_id,)).fetchone()
        if snapshot:
            if snapshot['provider_account_id'] != row['provider_account_id']:
                raise PermissionError('YIXIAOER_ACCOUNT_MAPPING_CONFLICT')
            row['provider_account_status'] = snapshot['provider_binding_status']
            row['provider_last_verified_at'] = snapshot['provider_last_seen_at']
    if required:
        if not row:
            raise PermissionError('YIXIAOER_ACCOUNT_UNBOUND')
        unique = db.execute("SELECT count(*) FROM provider_account_bindings WHERE provider='yixiaoer' AND provider_account_id=?", (row['provider_account_id'],)).fetchone()[0]
        if unique != 1:
            raise PermissionError('YIXIAOER_ACCOUNT_MAPPING_NOT_UNIQUE')
        try:
            age = ((now or datetime.now(timezone.utc)) - datetime.fromisoformat(row['provider_last_verified_at'])).total_seconds()
        except (TypeError, ValueError):
            age = float('inf')
        if row['provider_account_status'] != 'ONLINE' or not 0 <= age <= 1800:
            raise PermissionError('YIXIAOER_ACCOUNT_NOT_VALID_OR_STALE')
    return row


def enrich_accounts(db, accounts):
    if not enabled(db):
        return accounts
    rows = []
    for item in accounts:
        item = dict(item)
        binding = cached_binding(db, item['account_id'])
        item.update(business_account_id=item['account_id'],provider='yixiaoer', provider_binding='已绑定' if binding else '未绑定',
                    provider_account_status=binding['provider_account_status'] if binding else 'UNBOUND',
                    provider_account_id=binding['provider_account_id'] if binding else None,
                    provider_last_verified_at=binding['provider_last_verified_at'] if binding else None)
        item['last_synced_at'] = binding['provider_last_verified_at'] if binding else item['last_synced_at']
        item['online_status'] = binding['provider_account_status'] if binding else 'OFFLINE'
        item['is_available'] = int(bool(binding and binding['provider_account_status'] == 'ONLINE'))
        rows.append(item)
    from .account_registry import enrich_snapshot
    return enrich_snapshot(db, rows)


def check_slots(db, slots, now=None):
    if not enabled(db):
        return
    from production_autopilot.budget import check_new_slots
    check_new_slots(db, slots)
    for slot in slots:
        schedule_gate(slot.scheduled_at, now)
        cached_binding(db, slot.account_id, required=True, now=now)
        from media_execution.integration import output_for
        if not output_for(db,path=slot.video_path) and not Path(slot.video_path).is_file():
            raise ValueError('MP4_MISSING')
        if db.execute("SELECT 1 FROM publish_plan_items i JOIN publish_jobs j USING(job_id) WHERE i.account_id=? AND i.scheduled_at=? AND j.status NOT IN ('CANCELLED','FAILED') AND i.item_id<>?", (slot.account_id, slot.scheduled_at, slot.item_id)).fetchone():
            raise PermissionError('ACCOUNT_TIME_COLLISION_BLOCKED')


def audit(db, event, *, job_id=None, account_id=None, previous=None, state=None, evidence=None):
    db.execute('INSERT INTO provider_audit_events(job_id,business_account_id,event,previous_state,new_state,recorded_at,evidence_json) VALUES(?,?,?,?,?,?,?)',
               (job_id, account_id, event, previous, state, utc_now_iso(), json.dumps(evidence or {}, ensure_ascii=False)))


def enroll_confirmed(db, plan_id):
    """仅新Confirm事务接入，不扫描或采用历史已确认任务。"""
    if not enabled(db):
        return
    plan = db.execute('SELECT status FROM publish_plans WHERE plan_id=?', (plan_id,)).fetchone()
    if not plan or plan[0] != 'CONFIRMED':
        raise PermissionError('CONFIRMED_PLAN_REQUIRED')
    for item in db.execute('SELECT * FROM publish_plan_items WHERE plan_id=?', (plan_id,)).fetchall():
        binding = cached_binding(db, item['account_id'], required=True)
        job = db.execute('SELECT * FROM publish_jobs WHERE job_id=?', (item['job_id'],)).fetchone()
        if db.execute('SELECT 1 FROM provider_publish_jobs WHERE job_id=?', (job['job_id'],)).fetchone():
            continue
        now = utc_now_iso()
        from media_execution.integration import output_for
        remote=output_for(db,job['content_id'])
        preparation=db.execute("SELECT value FROM yixiaoer_settings WHERE key='canary_preparation'").fetchone()
        if preparation:
            prepared=json.loads(preparation[0])
            if prepared['plan_id']==plan_id:
                cover=next((f for f in prepared['files'] if f['video_path']==job['video_path']),None)
                if not cover or file_sha(cover['cover_path'])!=cover['cover_sha256']:
                    raise PermissionError('CANARY_COVER_CHANGED')
                db.execute('UPDATE publish_jobs SET cover_path=? WHERE job_id=?',(cover['cover_path'],job['job_id']))
        if production_enabled(db):
            prepared_row=db.execute('SELECT preparation_json FROM provider_production_previews WHERE plan_id=?',(plan_id,)).fetchone()
            if prepared_row:
                prepared=json.loads(prepared_row[0])
                cover=next((f for f in prepared['files'] if f['video_path']==job['video_path']),None)
                valid_remote=bool(remote and cover and cover['sha256']==remote['output_sha256']
                    and cover['cover_path']==remote['media'].get('cover_path') and cover['cover_sha256']==remote['media'].get('cover_sha256'))
                if not cover or (not valid_remote and (file_sha(cover['cover_path'])!=cover['cover_sha256'] or file_sha(cover['video_path'])!=cover['sha256'])):
                    raise PermissionError('YIXIAOER_PREPARED_MEDIA_CHANGED')
                db.execute('UPDATE publish_jobs SET cover_path=? WHERE job_id=?',(cover['cover_path'],job['job_id']))
        db.execute('INSERT INTO provider_publish_jobs(job_id,plan_id,provider_account_id,state,video_sha256,created_at,updated_at) VALUES(?,?,?,\'READY_TO_DISPATCH\',?,?,?)',
                   (job['job_id'], plan_id, binding['provider_account_id'], remote['output_sha256'] if remote else file_sha(job['video_path']), now, now))
        if 'cover_sha256' in {r[1] for r in db.execute('PRAGMA table_info(provider_publish_jobs)')}:
            cover_path=db.execute('SELECT cover_path FROM publish_jobs WHERE job_id=?',(job['job_id'],)).fetchone()[0]
            if not cover_path or not remote and not Path(cover_path).is_file():
                raise PermissionError('YIXIAOER_COVER_REQUIRED')
            db.execute('UPDATE provider_publish_jobs SET cover_sha256=? WHERE job_id=?',(remote['media']['cover_sha256'] if remote else file_sha(cover_path),job['job_id']))
        db.execute("UPDATE publish_jobs SET status='READY_TO_DISPATCH',current_step='YIXIAOER_READY_TO_DISPATCH',error_code=NULL,error_message=NULL WHERE job_id=?", (job['job_id'],))
        audit(db, 'PLAN_CONFIRMED_PROVIDER_ROUTED', job_id=job['job_id'], state='READY_TO_DISPATCH', evidence={'provider': 'yixiaoer', 'provider_account_id': binding['provider_account_id']})
        from media_execution.integration import enroll_publish
        enroll_publish(db,job['job_id'])
    if production_enabled(db):
        owner=db.execute('SELECT employee_id FROM publish_plans WHERE plan_id=?',(plan_id,)).fetchone()[0]
        ids=[r[0] for r in db.execute('SELECT content_id FROM publish_plan_items WHERE plan_id=? ORDER BY scheduled_at',(plan_id,))]
        db.execute('INSERT OR IGNORE INTO provider_plan_authorizations VALUES(?,?,?,?)',(plan_id,owner,json.dumps(ids),utc_now_iso()))


class ProviderStore:
    def __init__(self, planner):
        self.planner = planner

    def migrate(self):
        with self.planner.connect() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='yixiaoer_settings'").fetchone():
                return {'already_applied': True}
            backup = self.planner.path.with_name(self.planner.path.name + '.yixiaoer-' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.bak')
            with closing(sqlite3.connect(backup)) as saved:
                db.backup(saved)
        with self.planner.connect(write=True) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='yixiaoer_settings'").fetchone():
                return {'already_applied': True}
            sql = (Path(__file__).parent/'migrations/001_provider.sql').read_text('utf-8')
            statement = ''
            for line in sql.splitlines(True):
                statement += line
                if sqlite3.complete_statement(statement):
                    db.execute(statement)
                    statement = ''
            db.execute("INSERT INTO yixiaoer_settings VALUES('enabled','true')")
            if db.execute('PRAGMA foreign_key_check').fetchall():
                raise RuntimeError('PROVIDER_MIGRATION_FOREIGN_KEY_ERROR')
        return {'backup': str(backup), 'historical_jobs_enrolled': 0}

    def row(self, job_id):
        with self.planner.connect() as db:
            row = db.execute('SELECT j.*,p.*,m.account_id AS business_account_id,m.topics_json FROM publish_jobs j JOIN provider_publish_jobs p USING(job_id) JOIN startup_job_metadata m USING(job_id) WHERE job_id=?', (job_id,)).fetchone()
            return dict(row) if row else None

    def migrate_production(self):
        with self.planner.connect(write=True) as db:
            if 'cover_sha256' not in {r[1] for r in db.execute('PRAGMA table_info(provider_publish_jobs)')}:
                db.execute('ALTER TABLE provider_publish_jobs ADD COLUMN cover_sha256 TEXT')
            sql=(Path(__file__).parent/'migrations/002_production.sql').read_text('utf-8')
            statement=''
            for line in sql.splitlines(True):
                statement+=line
                if sqlite3.complete_statement(statement):
                    db.execute(statement); statement=''
            if db.execute('PRAGMA foreign_key_check').fetchall():
                raise RuntimeError('PROVIDER_PRODUCTION_MIGRATION_INTEGRITY_ERROR')

    def bind(self, business_account_id, account, *, source):
        if not account.get('id') or account.get('status') != 1:
            raise PermissionError('YIXIAOER_ACCOUNT_NOT_ONLINE')
        with self.planner.connect(write=True) as db:
            business = db.execute('SELECT platform FROM xiaovcat_accounts WHERE account_id=? AND is_active=1', (business_account_id,)).fetchone()
            if not business or business[0] not in ('douyin', '抖音'):
                raise PermissionError('BUSINESS_ACCOUNT_PLATFORM_MISMATCH')
            old = cached_binding(db, business_account_id)
            if old and old['provider_account_id'] != account['id']:
                raise PermissionError('PROVIDER_REBIND_REQUIRES_SEPARATE_MIGRATION')
            db.execute("INSERT INTO provider_account_bindings VALUES(?,'douyin','yixiaoer',?,'ONLINE',?,?) ON CONFLICT(business_account_id,provider) DO UPDATE SET provider_account_status='ONLINE',provider_last_verified_at=excluded.provider_last_verified_at,raw_account_json=excluded.raw_account_json", (business_account_id, account['id'], utc_now_iso(), json.dumps(account,ensure_ascii=False)))
            audit(db, 'ACCOUNT_PROVIDER_BOUND', account_id=business_account_id, evidence={'provider_account_id': account['id'], 'source': source})

    def refresh_bindings(self, accounts):
        by_id = {a['id']: a for a in accounts}
        with self.planner.connect(write=True) as db:
            db.execute("INSERT INTO yixiaoer_settings VALUES('last_successful_account_query',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(utc_now_iso(),))
            for binding in db.execute('SELECT * FROM provider_account_bindings').fetchall():
                account = by_id.get(binding['provider_account_id'])
                status = 'ONLINE' if account and account.get('status') == 1 else 'OFFLINE'
                db.execute('UPDATE provider_account_bindings SET provider_account_status=?,provider_last_verified_at=?,raw_account_json=? WHERE business_account_id=?', (status,utc_now_iso(),json.dumps(account or {},ensure_ascii=False),binding['business_account_id']))
                audit(db, 'ACCOUNT_PROVIDER_VERIFIED', account_id=binding['business_account_id'], evidence={'status': status})

    def transition(self, job_id, state, evidence=None, **fields):
        if state not in STATES:
            raise ValueError('INVALID_PROVIDER_STATE')
        allowed = {'provider_task_set_id','provider_task_id','provider_video_id','provider_video_url','provider_status','provider_stage_status','provider_last_checked_at','provider_raw_status','last_error','payload_sha256','request_hash'}
        if not set(fields).issubset(allowed):
            raise ValueError('INVALID_PROVIDER_FIELD')
        with self.planner.connect(write=True) as db:
            old = db.execute('SELECT state FROM provider_publish_jobs WHERE job_id=?',(job_id,)).fetchone()[0]
            if old in ('PUBLISHED','CANCELLED') and state != old:
                raise PermissionError('PROVIDER_TERMINAL_STATE_IMMUTABLE')
            values = dict(fields,state=state,updated_at=utc_now_iso())
            db.execute('UPDATE provider_publish_jobs SET '+','.join(k+'=?' for k in values)+' WHERE job_id=?', (*values.values(),job_id))
            db.execute('UPDATE publish_jobs SET status=?,current_step=?,external_work_id=COALESCE(?,external_work_id),external_work_url=COALESCE(?,external_work_url),updated_at=? WHERE job_id=?', (state,'YIXIAOER_'+state,fields.get('provider_video_id'),fields.get('provider_video_url'),utc_now_iso(),job_id))
            audit(db,'PROVIDER_STATE_OBSERVED',job_id=job_id,previous=old,state=state,evidence=evidence)
            if fields.get('provider_task_set_id'):
                db.execute("INSERT INTO yixiaoer_settings VALUES('local_executor_last_confirmed',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(utc_now_iso(),))

    def claim_principal(self, db, owner, row):
        actor = db.execute('SELECT * FROM employees WHERE employee_id=? AND enabled=1',(owner,)).fetchone()
        if not actor:raise PermissionError('PLAN_OWNER_DISABLED')
        return actor

    def claim(self, worker_id, allowed_plan_ids):
        if not allowed_plan_ids:
            return None
        with self.planner.connect(write=True) as db:
            from media_execution.integration import enabled as media_enabled
            if media_enabled(db):
                # 新拓扑只由2060领取。旧Server代码留作显式回退，不自动选中。
                return None
            from production_autopilot.restore_guard import assert_dispatch_allowed
            assert_dispatch_allowed(db)
            row = db.execute("SELECT p.*,j.scheduled_at,j.video_path,j.content_id,i.account_id FROM provider_publish_jobs p JOIN publish_jobs j USING(job_id) JOIN publish_plans plan ON plan.plan_id=p.plan_id JOIN publish_plan_items i USING(job_id) WHERE p.plan_id IN ("+','.join('?' for _ in allowed_plan_ids)+") AND plan.status='CONFIRMED' AND p.state='READY_TO_DISPATCH' AND p.worker_id IS NULL AND p.submit_attempt_count=0 AND j.status!='CANCELLED' ORDER BY j.scheduled_at LIMIT 1", tuple(allowed_plan_ids)).fetchone()
            if not row:
                return None
            try:
                identity = cached_binding(db,row['account_id'],required=True)
                if identity['provider_account_id'] != row['provider_account_id']:
                    raise PermissionError('YIXIAOER_ACCOUNT_MAPPING_CONFLICT')
            except PermissionError as error:
                db.execute("UPDATE provider_publish_jobs SET state='ATTENTION_REQUIRED',last_error=?,updated_at=? WHERE job_id=?", (str(error),utc_now_iso(),row['job_id']))
                db.execute("UPDATE publish_jobs SET status='ATTENTION_REQUIRED',current_step='YIXIAOER_ACCOUNT_ATTENTION_REQUIRED',updated_at=? WHERE job_id=?", (utc_now_iso(),row['job_id']))
                audit(db,'ACCOUNT_MAPPING_ATTENTION_REQUIRED',job_id=row['job_id'],state='ATTENTION_REQUIRED',evidence={'reason':str(error)})
                return None
            schedule_gate(row['scheduled_at'])
            from startup_pipeline.account_binding import guard_publish_job
            guard_publish_job(db,row['job_id'])
            plan = db.execute('SELECT employee_id FROM publish_plans WHERE plan_id=?',(row['plan_id'],)).fetchone()
            actor = self.claim_principal(db,plan[0],row)
            self.planner._require_publish_accounts(db,actor,[row['account_id']],'STARTUP')
            if db.execute("SELECT 1 FROM publish_jobs WHERE content_id=? AND job_id<>? AND status NOT IN ('CANCELLED','FAILED')",(row['content_id'],row['job_id'])).fetchone():
                raise PermissionError('CONTENT_ALREADY_SCHEDULED_IN_OTHER_PLAN')
            binding = cached_binding(db,row['account_id'],required=True)
            if binding['provider_account_id'] != row['provider_account_id'] or file_sha(row['video_path']) != row['video_sha256']:
                raise PermissionError('FROZEN_JOB_CHANGED')
            token = secrets.token_hex(24)
            db.execute("UPDATE provider_publish_jobs SET worker_id=?,claim_token=?,state='UPLOADING',updated_at=? WHERE job_id=?", (worker_id,token,utc_now_iso(),row['job_id']))
            db.execute("UPDATE publish_jobs SET status='UPLOADING',current_step='YIXIAOER_UPLOADING' WHERE job_id=?", (row['job_id'],))
            audit(db,'JOB_CLAIMED',job_id=row['job_id'],previous=row['state'],state='UPLOADING',evidence={'worker_id':worker_id})
            return row['job_id'],token

    def reserve_submit(self, job_id, token, intent):
        with self.planner.connect(write=True) as db:
            from production_autopilot.restore_guard import assert_dispatch_allowed
            assert_dispatch_allowed(db)
            row = db.execute('SELECT p.*,j.scheduled_at,j.video_path,j.status FROM provider_publish_jobs p JOIN publish_jobs j USING(job_id) WHERE job_id=?',(job_id,)).fetchone()
            if row['submit_attempt_count'] >= 1 or row['intent_json']:
                raise PermissionError('SUBMIT_ONCE_LATCH_CONSUMED')
            if row['claim_token'] != token or row['state'] != 'PROVIDER_VALIDATED' or row['status']=='CANCELLED':
                raise PermissionError('CLAIM_AND_VALIDATED_JOB_REQUIRED')
            business = db.execute('SELECT account_id FROM startup_job_metadata WHERE job_id=?', (job_id,)).fetchone()
            if not business:
                raise PermissionError('YIXIAOER_ACCOUNT_UNBOUND')
            binding = cached_binding(db,business[0],required=True)
            if binding['provider_account_id'] != row['provider_account_id']:
                raise PermissionError('YIXIAOER_ACCOUNT_MAPPING_CONFLICT')
            schedule_gate(row['scheduled_at'])
            if int(datetime.fromisoformat(row['scheduled_at']).timestamp()*1000)!=intent['scheduledTime']:
                raise PermissionError('FROZEN_SCHEDULE_CHANGED')
            if file_sha(row['video_path']) != row['video_sha256']:
                raise PermissionError('REGISTERED_VIDEO_CHANGED')
            # 同事务持久化intent与计数；提交进程只能在commit后执行一次POST。
            db.execute("UPDATE provider_publish_jobs SET intent_json=?,submit_attempt_count=1,state='SUBMIT_INTENT',provider_submitted_at=?,updated_at=? WHERE job_id=?", (json.dumps(intent,ensure_ascii=False),utc_now_iso(),utc_now_iso(),job_id))
            db.execute("UPDATE publish_jobs SET status='SUBMIT_INTENT',current_step='YIXIAOER_SUBMIT_INTENT' WHERE job_id=?",(job_id,))
            audit(db,'SUBMIT_INTENT',job_id=job_id,previous=row['state'],state='SUBMIT_INTENT',evidence=intent)

    def cancel(self, token, job_id):
        with self.planner.connect(write=True) as db:
            actor=self.planner._principal(db,token)
            row=db.execute('SELECT p.*,plan.employee_id,j.content_id FROM provider_publish_jobs p JOIN publish_plans plan ON plan.plan_id=p.plan_id JOIN publish_jobs j USING(job_id) WHERE job_id=?',(job_id,)).fetchone()
            if not row or actor['employee_id']!=row['employee_id']:
                raise PermissionError('PLAN_PERMISSION_DENIED')
            if row['submit_attempt_count'] or row['intent_json'] or row['worker_id']:
                raise PermissionError('ACTIVE_OR_CONSUMED_JOB_CANNOT_CANCEL_LOCALLY')
            db.execute("UPDATE provider_publish_jobs SET state='CANCELLED',updated_at=? WHERE job_id=?",(utc_now_iso(),job_id))
            db.execute("UPDATE publish_jobs SET status='CANCELLED',current_step='YIXIAOER_CANCELLED' WHERE job_id=?",(job_id,))
            if not db.execute("SELECT 1 FROM publish_jobs WHERE content_id=? AND job_id<>? AND status NOT IN ('CANCELLED','FAILED')",(row['content_id'],job_id)).fetchone():
                db.execute("UPDATE startup_contents SET publish_status='NOT_SCHEDULED' WHERE content_id=?",(row['content_id'],))
            audit(db,'JOB_CANCELLED',job_id=job_id,previous=row['state'],state='CANCELLED',evidence={'employee_id':actor['employee_id']})
