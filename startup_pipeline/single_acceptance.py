"""正式READY池到既有单次Worker的限定桥接；不改变页面/默认模拟Planner。"""
from contextlib import closing
from datetime import datetime
from pathlib import Path
import json
import sqlite3
from xiaovcat_adapter.models import PublishJob,PublishStatus,utc_now_iso
from xiaovcat_adapter.storage import JOB_COLUMNS
from startup_render.common import read,digest as file_digest
from .account_binding import guard_publish_job

CONFIRMATION='USER_AUTHORIZED_STARTUP_FULL_CLOSED_LOOP_SINGLE_READY'


def migrate(path):
    path=Path(path).resolve()
    with closing(sqlite3.connect(path)) as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='startup_real_acceptance_jobs'").fetchone():
            return {'already_applied':True}
        tables=('publish_plan_items','startup_job_metadata')
        before={t:db.execute('SELECT * FROM '+t+' ORDER BY 1').fetchall() for t in tables}
        objects=db.execute("SELECT sql FROM sqlite_master WHERE tbl_name IN (?,?) AND type IN ('index','trigger') AND sql IS NOT NULL",tables).fetchall()
        backup=path.with_name(path.name+'.single-acceptance-'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.bak')
        with closing(sqlite3.connect(backup)) as saved:db.backup(saved)
        db.execute('PRAGMA foreign_keys=OFF');db.execute('PRAGMA legacy_alter_table=ON')
        try:
            db.executescript('BEGIN IMMEDIATE;'+(Path(__file__).parent/'migrations/006_single_acceptance.sql').read_text(encoding='utf-8'))
            for (statement,) in objects:db.execute(statement)
            if any(before[t]!=db.execute('SELECT * FROM '+t+' ORDER BY 1').fetchall() for t in tables) or db.execute('PRAGMA foreign_key_check').fetchall():
                raise RuntimeError('SINGLE_ACCEPTANCE_MIGRATION_INTEGRITY_ERROR')
            db.execute('INSERT INTO startup_pipeline_migrations VALUES(6,?)',(utc_now_iso(),));db.commit()
        except Exception:db.rollback();raise
        finally:db.execute('PRAGMA legacy_alter_table=OFF');db.execute('PRAGMA foreign_keys=ON')
    return {'version':6,'backup':str(backup),'old_rows_unchanged':True}


def create_single_ready_job(pipeline,token,plan,content_id,profile_id,run_root,*,expected_preview,confirmation):
    if confirmation!=CONFIRMATION:raise PermissionError('EXPLICIT_SINGLE_ACCEPTANCE_REQUIRED')
    run_root=Path(run_root).resolve()
    generated=read(run_root/'GENERATION_RESULT.json');run=read(run_root/'single_run.json')
    if (len(generated['registered'])!=1 or generated['registered'][0]['content_id']!=content_id
        or run['max_jobs']!=1 or plan.account_ids!=('1621131832863931',) or plan.daily_count!=1
        or len(plan.video_paths)!=1 or plan.start_date!=plan.end_date):
        raise PermissionError('SINGLE_READY_SCOPE_MISMATCH')
    receipt=read(run_root/'server/receipts'/(content_id+'.json'))
    if (receipt['status']!='COMPLETED' or receipt['content_status']!='READY_TO_PUBLISH'
        or receipt['media']['sha256']!=file_digest(plan.video_paths[0])
        or receipt['target_account_id']!='1621131832863931'):
        raise PermissionError('REAL_RENDER_RECEIPT_REQUIRED')
    if read(Path(__file__).resolve().parents[1]/'xiaovcat_adapter/config.json')['real_publish_enabled'] is not False:
        raise PermissionError('GLOBAL_PUBLISH_SWITCH_MUST_STAY_OFF')
    pipeline.migrate();migration=migrate(pipeline.store.path)
    slots,preview=pipeline.preview_receipt(token,plan,[content_id],profile_id)
    if preview!=expected_preview or len(slots)!=1:raise PermissionError('PREVIEW_CHANGED')
    with pipeline.store.connect(write=True) as db:
        actor=pipeline.store._principal(db,token)
        slots,rows,profile=pipeline._slots(db,token,plan,[content_id],profile_id)
        account=next(a for a in pipeline.accounts(token) if a['account_id']=='1621131832863931')
        if account['display_name']!='丙曜' or account['platform']!='抖音':raise PermissionError('BOUND_BINGYAO_REQUIRED')
        if db.execute('SELECT 1 FROM publish_jobs WHERE content_id=?',(content_id,)).fetchone():
            raise PermissionError('CONTENT_HAS_EXISTING_JOB_NO_DUPLICATE')
        if db.execute('SELECT 1 FROM startup_real_acceptance_jobs WHERE run_id=?',(run['run_id'],)).fetchone():
            raise PermissionError('RUN_ALREADY_HAS_SINGLE_JOB')
        slot=slots[0];source=rows[0]
        job=PublishJob.create(content_id=content_id,video_path=source['video_path'],title=profile['title_template'],
             description=profile['description_template'],platform=account['platform'],account_name=account['display_name'],
             publish_mode='SCHEDULED',scheduled_at=slot.scheduled_at,composition_id=source['composition_signature'],allow_empty_title=True)
        job.status=PublishStatus.DRY_RUN_READY;job.current_step='SINGLE_READY_AWAITING_VERIFIED_UI'
        policy=dict(job_id=job.job_id,content_id=content_id,video_path=job.video_path,account_name=job.account_name,
            account_id=slot.account_id,platform=job.platform,title=job.title,description=job.description,
            topics=json.loads(profile['topics_json']),publish_mode='SCHEDULED',scheduled_at=slot.scheduled_at,
            schedule_delay_minutes=130,max_jobs=1,max_final_submit_invocations=1,consume_other_jobs=False,
            media_policy='VERIFIED_READY_ONLY',profile_mode='STARTUP_READY_BOUND',
            video_sha256=receipt['media']['sha256'],source_run_id=run['run_id'],confirmation=CONFIRMATION)
        db.execute("INSERT INTO publish_plans VALUES(?,?,?,'SINGLE_ACCEPTANCE',?,'STARTUP')",
                   (plan.plan_id,actor['employee_id'],plan.payload(),utc_now_iso()))
        data=job.to_dict()
        db.execute('INSERT INTO publish_jobs ('+','.join(JOB_COLUMNS)+') VALUES ('+','.join('?' for _ in JOB_COLUMNS)+')',
            [json.dumps(data['segment_material_ids']) if col=='segment_material_ids_json' else data.get(col) for col in JOB_COLUMNS])
        db.execute('INSERT INTO publish_plan_items VALUES(?,?,?,?,?,?,?,?,?,0)',
            (slot.item_id,plan.plan_id,content_id,slot.account_id,account['group_id'],slot.video_path,slot.scheduled_at,slot.schedule_signature,job.job_id))
        db.execute("INSERT INTO startup_plan_items VALUES(?,?,?,?,'STARTUP')",(slot.item_id,content_id,source['batch_id'],source['composition_signature']))
        db.execute("INSERT INTO startup_job_metadata VALUES(?,?,?,?,'STARTUP',?,?,?,?,?,?,?,?,'SINGLE_ACCEPTANCE')",
            (job.job_id,content_id,actor['employee_id'],slot.account_id,plan.plan_id,slot.item_id,source['batch_id'],
             source['composition_signature'],profile_id,profile['topics_json'],profile['cover_mode'],slot.schedule_signature))
        db.execute('INSERT INTO startup_real_acceptance_jobs VALUES(?,?,?,?,?,?)',
            (job.job_id,content_id,run['run_id'],slot.account_id,json.dumps(policy,ensure_ascii=False,sort_keys=True),utc_now_iso()))
        db.execute("UPDATE startup_contents SET publish_status='SCHEDULED' WHERE content_id=?",(content_id,))
        guard_publish_job(db,job.job_id)
    return {'job_id':job.job_id,'policy':policy,'migration':migration}


class ReadyScope:
    def __init__(self,store,job_id,results):
        self.store,self.job_id,self.results=store,job_id,Path(results)
        with store.connect() as db:
            row=db.execute('SELECT * FROM startup_real_acceptance_jobs WHERE job_id=?',(job_id,)).fetchone()
            if not row:raise PermissionError('REGISTERED_SINGLE_READY_JOB_REQUIRED')
            self.policy=json.loads(row['scope_json'])
        self.confirmation=CONFIRMATION

    def check(self,policy):
        if policy!=self.policy:raise PermissionError('REGISTERED_READY_SCOPE_CHANGED')
        with self.store.connect() as db:
            guard_publish_job(db,self.job_id)
            content=db.execute('SELECT * FROM startup_contents WHERE content_id=?',(policy['content_id'],)).fetchone()
            job=db.execute('SELECT * FROM publish_jobs WHERE job_id=?',(self.job_id,)).fetchone()
            account=db.execute('SELECT * FROM xiaovcat_accounts WHERE account_id=?',(policy['account_id'],)).fetchone()
            if (not content or content['production_status']!='READY' or not job
                or job['content_id']!=content['content_id'] or job['video_path']!=policy['video_path']
                or job['scheduled_at']!=policy['scheduled_at'] or not account or account['online_status']!='ONLINE'
                or not account['is_available'] or account['display_name']!='丙曜' or account['platform']!='抖音'
                or job['title']!=policy['title'] or job['description']!=policy['description']
                or job['status']!='DRY_RUN_READY'):
                raise PermissionError('READY_JOB_LIVE_SCOPE_MISMATCH')
            authorized=db.execute("SELECT 1 FROM startup_job_metadata m JOIN employees e USING(employee_id) "
                "JOIN employee_group_bindings b USING(employee_id) JOIN xiaovcat_accounts a ON a.group_id=b.group_id "
                "WHERE m.job_id=? AND a.account_id=m.account_id AND e.enabled=1 AND b.enabled=1 AND b.group_role='STARTUP'",
                (self.job_id,)).fetchone()
            if not authorized or db.execute('SELECT 1 FROM published_content WHERE content_id=?',(policy['content_id'],)).fetchone():
                raise PermissionError('ACCOUNT_PERMISSION_DENIED_OR_CONTENT_ALREADY_SUBMITTED')
            from datetime import timedelta,timezone
            if datetime.now(timezone.utc)-datetime.fromisoformat(account['last_synced_at'])>timedelta(minutes=30):
                raise PermissionError('ACCOUNT_SNAPSHOT_EXPIRED')
        if file_digest(policy['video_path'])!=policy['video_sha256']:raise PermissionError('READY_VIDEO_CHANGED')
        remaining=datetime.fromisoformat(policy['scheduled_at'])-datetime.now().astimezone()
        from datetime import timedelta
        if not timedelta(hours=2)<remaining<=timedelta(days=14):raise PermissionError('SCHEDULE_NO_LONGER_SAFE')
        return policy
