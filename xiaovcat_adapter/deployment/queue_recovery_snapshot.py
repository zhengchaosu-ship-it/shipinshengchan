"""本轮只读队列诊断证据；不claim、不写业务库、不调用桌面。"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[2]
PLAN = '99b93466-4223-4417-8d36-8ab69a2378e8'
OLD_JOBS = ['ce40b544-6f9f-4e37-9b8a-02b430d24410',
            'c671a186-21e4-44a9-8529-28138eee49e5',
            'af6c16d3-2912-4390-88c7-4584b3e4feea']


def snapshot():
    with closing(sqlite3.connect('file:'+str(ROOT/'operations.db')+'?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        plan = dict(db.execute('SELECT * FROM publish_plans WHERE plan_id=?', (PLAN,)).fetchone())
        rows = [dict(r) for r in db.execute('SELECT j.job_id,j.content_id,j.video_path,j.account_name,m.account_id,'
            'j.scheduled_at,j.status AS job_status,j.current_step,j.created_at,j.title,j.description,m.topics_json,'
            'd.state AS dispatch_status,d.worker_id AS claimed_by,d.claimed_at,'
            '(SELECT count(*) FROM state_events e WHERE e.job_id=j.job_id AND e.step=?) AS submit_attempt_count '
            'FROM publish_jobs j JOIN startup_job_metadata m USING(job_id) '
            'LEFT JOIN startup_production_dispatch d USING(job_id) WHERE m.source_plan_id=? '
            'ORDER BY j.scheduled_at,j.job_id', ('V04_FINAL_SUBMIT_RESERVED', PLAN))]
        for row in rows:
            row['filename'] = Path(row['video_path']).name
        duplicates = [dict(r) for r in db.execute('SELECT content_id,count(*) AS job_count FROM startup_job_metadata '
            'WHERE source_plan_id=? GROUP BY content_id HAVING count(*)>1', (PLAN,))]
        same_slots = [dict(r) for r in db.execute('SELECT account_id,scheduled_at,count(*) AS job_count '
            'FROM publish_plan_items WHERE plan_id=? GROUP BY account_id,scheduled_at HAVING count(*)>1', (PLAN,))]
        old = []
        for job_id in OLD_JOBS:
            job = dict(db.execute('SELECT * FROM publish_jobs WHERE job_id=?', (job_id,)).fetchone())
            events = [dict(r) for r in db.execute('SELECT * FROM state_events WHERE job_id=? ORDER BY id', (job_id,))]
            content = dict(db.execute('SELECT * FROM startup_contents WHERE content_id=?', (job['content_id'],)).fetchone())
            data = json.dumps([job, events, content], ensure_ascii=False, sort_keys=True)
            old.append(dict(job_id=job_id, status=job['status'],
                submit_attempt_count=sum(e['step']=='V04_FINAL_SUBMIT_RESERVED' for e in events),
                job_content_events_sha256=hashlib.sha256(data.encode('utf-8')).hexdigest()))
        totals = {t: db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ['publish_plans', 'publish_jobs']}
    # 调用原正式校验，只读连接；重复拒绝发生在媒体/账号/UI操作之前。
    from publish_planner.storage import PlannerStore
    from startup_pipeline.production_dispatch import ProductionDispatcher
    dispatcher = ProductionDispatcher(PlannerStore(ROOT/'operations.db'))
    with dispatcher.store.connect() as conn:
        try:
            dispatcher._context(conn, rows[0]['job_id'])
            first_precheck = 'PASS'
        except Exception as error:
            first_precheck = str(error)
    return dict(checked_at=datetime.now(timezone.utc).isoformat(), plan=plan, jobs=rows,
                repeated_contents=duplicates, duplicate_account_time_slots=same_slots,
                old_jobs=old, totals=totals, first_precheck=first_precheck, database_changes=0)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=['before', 'after'], required=True)
    args = parser.parse_args()
    data = snapshot()
    out = ROOT/'xiaovcat_adapter/runtime/server_publish_worker/queue_recovery_20261005'
    out.mkdir(parents=True, exist_ok=True)
    (out/(args.phase.upper()+'.json')).write_text(json.dumps(data, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(dict(plan_id=PLAN, job_count=len(data['jobs']),
        unique_content_count=len({r['content_id'] for r in data['jobs']}),
        repeated_content_count=len(data['repeated_contents']),
        duplicate_slot_count=len(data['duplicate_account_time_slots']),
        first_precheck=data['first_precheck'], old_jobs=data['old_jobs'], totals=data['totals']), ensure_ascii=False))
