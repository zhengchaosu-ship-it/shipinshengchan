"""恢复仅沿用原发布slot；过期slot记缺口，禁止同日追补或跨天搬单。"""
from datetime import datetime,timedelta,timezone
import json
from startup_autopilot.models import aware
from .control import WAITING


def replan(worker, grant, row, *, now=None):
    # 保留原入口名以兼容常驻Planner；不再修改任何scheduled_at。
    now=now or datetime.now(timezone.utc)
    with worker.production.planner.connect(write=True) as db:
        worker.production.verify(db,grant)
        cutoff=float(db.execute("SELECT value FROM media_execution_settings WHERE key='cutover_at'").fetchone()[0])
        current=db.execute('SELECT * FROM autopilot_allocations WHERE allocation_id=?',(row['allocation_id'],)).fetchone()
        if (not current or current['account_id']!=grant.account_id or aware(current['created_at']).timestamp()<cutoff
            or current['authorization_hash']!=grant.config_hash or current['state'] in
            ('FAILED','MISSED_NOT_SUBMITTED','STOPPED_UNSUBMITTED','CANCELLED','SCHEDULED_QUEUED','PUBLISHED','SUBMIT_RESULT_UNCERTAIN')):
            return False
        job=None
        if current['job_id']:
            job=db.execute("SELECT * FROM media_execution_jobs WHERE job_type='PUBLISH' AND job_id=?",(current['job_id'],)).fetchone()
            provider=db.execute('SELECT * FROM provider_publish_jobs WHERE job_id=?',(current['job_id'],)).fetchone()
            if (not job or not provider or job['state'] not in WAITING | {'WAITING_REPLAN','STALE_SCHEDULE'}
                or job['submit_attempt_count'] or job['intent_json'] or provider['submit_attempt_count'] or provider['intent_json']
                or provider['provider_task_id'] or provider['provider_task_set_id']
                or provider['state'] in ('FAILED','CANCELLED','SUBMITTED','SCHEDULED_QUEUED','PUBLISHED','SUBMIT_RESULT_UNCERTAIN')):
                return False
            if db.execute("SELECT 1 FROM media_execution_leases WHERE job_type='PUBLISH' AND job_id=?",(job['job_id'],)).fetchone():return False
        elif current['state']=='RENDER_PENDING':
            content=db.execute('SELECT production_status FROM startup_contents WHERE content_id=?',(current['content_id'],)).fetchone()
            if not content or content[0]!='READY':return False
        elif current['state']!='STALE_SCHEDULE':return False
        if aware(current['scheduled_at'])<now+timedelta(seconds=8100):
            reason='SLOT_EXPIRED_NO_CATCH_UP'
            if job:
                db.execute("UPDATE media_execution_jobs SET state='CANCELLED' WHERE job_type='PUBLISH' AND job_id=?",(job['job_id'],))
                db.execute("UPDATE provider_publish_jobs SET state='CANCELLED',updated_at=? WHERE job_id=?",(now.isoformat(),job['job_id']))
                db.execute("UPDATE publish_jobs SET status='CANCELLED',current_step=?,updated_at=? WHERE job_id=?",(reason,now.isoformat(),job['job_id']))
            db.execute("UPDATE autopilot_allocations SET state='MISSED_NOT_SUBMITTED',error=?,updated_at=? WHERE allocation_id=?",
                (reason,now.isoformat(),current['allocation_id']))
            event=reason
        else:
            from .integration import publish_open
            if not publish_open(db,grant.account_id):return False
            if job and job['state']=='WAITING_REPLAN':
                db.execute("UPDATE media_execution_jobs SET state='READY_TO_PUBLISH' WHERE job_type='PUBLISH' AND job_id=?",(job['job_id'],))
            elif job or current['state']!='STALE_SCHEDULE':return False
            db.execute('UPDATE autopilot_allocations SET state=?,error=NULL,updated_at=? WHERE allocation_id=?',
                ('READY_TO_DISPATCH' if job else 'RENDER_PENDING',now.isoformat(),current['allocation_id']))
            event='ORIGINAL_SLOT_RESTORED'
        evidence={'allocation_id':current['allocation_id'],'scheduled_at':current['scheduled_at'],
            'content_id':current['content_id'],'job_id':current['job_id'],'schedule_changed':False,'catch_up':False}
        if job:
            db.execute("INSERT INTO media_execution_events(at,job_type,job_id,event,evidence_json) VALUES(?,'PUBLISH',?,?,?)",
                (now.timestamp(),job['job_id'],event,json.dumps(evidence)))
        worker.production.event(db,grant.account_id,'DAILY_PLANNER',event,evidence)
        return True
