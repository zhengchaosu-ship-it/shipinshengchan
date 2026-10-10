"""既有业务表的轻量接线；无迁移/进程启动副作用。"""
import json
from datetime import datetime, timezone


def enabled(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='media_execution_settings'").fetchone():
        return False
    row = db.execute("SELECT value FROM media_execution_settings WHERE key='enabled'").fetchone()
    return bool(row and row[0]=='true')


def output_for(db, content_id=None, path=None):
    if not enabled(db):
        return None
    if content_id:
        row=db.execute('SELECT * FROM media_execution_outputs WHERE content_id=?',(content_id,)).fetchone()
    else:
        row=db.execute('SELECT * FROM media_execution_outputs WHERE local_output_path=?',(path,)).fetchone()
    if not row:
        return None
    result=dict(row)
    result['media']=json.loads(result['media_json'])
    return result


def observed_media(db, content, probe):
    output=output_for(db,content['content_id'])
    if not output:
        return probe(content['video_path'])
    if output['local_output_path']!=content['video_path']:
        raise PermissionError('WORKER_OUTPUT_IDENTITY_CHANGED')
    return {'size_bytes':output['media']['size'],'mtime_ns':output['media']['mtime_ns'],
            'duration_seconds':output['media']['duration'],'video_path':output['local_output_path']}


def managed_job(db, job_id):
    return enabled(db) and bool(db.execute("SELECT 1 FROM media_execution_jobs WHERE job_type='PUBLISH' AND job_id=?",(job_id,)).fetchone())


def enroll_publish(db, job_id):
    """仅原enroll_confirmed的新INSERT调用，同事务写执行关联，不采用历史Job。"""
    if not enabled(db):
        return
    row=db.execute('SELECT j.*,p.provider_account_id,p.video_sha256,p.cover_sha256,i.account_id '
                   'FROM publish_jobs j JOIN provider_publish_jobs p USING(job_id) '
                   'JOIN publish_plan_items i USING(job_id) WHERE j.job_id=?',(job_id,)).fetchone()
    output=output_for(db,row['content_id'])
    if not output:
        # 新架构只能消费2060生成的本机输出；历史READY不会自动进入新通道。
        raise PermissionError('NEW_WORKER_VERIFIED_OUTPUT_REQUIRED')
    contract={key:row[key] for key in ('platform','publish_mode','cover_path','title','description',
        'product_link_or_identifier','product_name')}
    topics=db.execute('SELECT topics_json FROM startup_job_metadata WHERE job_id=?',(job_id,)).fetchone()
    contract.update(topics_json=topics[0],cover_sha256=row['cover_sha256'])
    payload={'provider_account_id':row['provider_account_id'],'render_job_id':output['render_job_id'],'publish_contract':contract}
    at=datetime.now(timezone.utc).timestamp()
    db.execute("INSERT INTO media_execution_jobs(job_type,job_id,worker_id,business_account_id,content_id,payload_json,created_at,state,scheduled_at) VALUES('PUBLISH',?,?,?,?,?,?,'READY_TO_PUBLISH',?)",
               (job_id,output['worker_id'],row['account_id'],row['content_id'],json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')),at,datetime.fromisoformat(row['scheduled_at']).timestamp()))


def publish_open(db, account):
    if not enabled(db):
        return True
    row=db.execute('SELECT gate,provider_account_status FROM media_account_publish_gates WHERE business_account_id=?',(account,)).fetchone()
    return bool(row and row[0] in ('OPEN','CONDITIONAL_OPEN') and row[1]=='ONLINE')


def backlog_allowed(db, account, limit=15):
    if not enabled(db) or publish_open(db,account):
        return True
    setting=db.execute("SELECT value FROM media_execution_settings WHERE key='ready_backlog_limit_per_account'").fetchone()
    limit=int(setting[0]) if setting else limit
    count=db.execute("SELECT count(*) FROM startup_contents c JOIN startup_content_bindings b USING(content_id) "
        "WHERE b.target_account_id=? AND c.production_status IN ('READY','RENDER_PENDING','GENERATING') "
        "AND c.publish_status!='PUBLISHED'",(account,)).fetchone()[0]
    return count<limit
