"""生产接线收口只读证据：无UI、无claim、无迁移、无任务写入。"""
import hashlib
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[2]
OLD_JOBS=('ce40b544-6f9f-4e37-9b8a-02b430d24410','c671a186-21e4-44a9-8529-28138eee49e5','af6c16d3-2912-4390-88c7-4584b3e4feea')

def inspect():
    db=sqlite3.connect('file:'+str(ROOT/'operations.db').replace('\\','/')+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    try:
        plans=[dict(r) for r in db.execute('SELECT plan_id,status,created_at FROM publish_plans ORDER BY plan_id')]
        snapshots={}
        old=[]
        for job in OLD_JOBS:
            record=dict(db.execute('SELECT * FROM publish_jobs WHERE job_id=?',(job,)).fetchone())
            events=[dict(r) for r in db.execute('SELECT * FROM state_events WHERE job_id=? ORDER BY id',(job,))]
            content=dict(db.execute('SELECT * FROM startup_contents WHERE content_id=?',(record['content_id'],)).fetchone())
            snapshots[job]=hashlib.sha256(json.dumps([record,events,content],sort_keys=True).encode()).hexdigest()
            old.append(dict(job_id=job,status=record['status'],content_status=content['publish_status'],
                submit_attempt_count=sum(r['step']=='V04_FINAL_SUBMIT_RESERVED' for r in events)))
        preview=ROOT/'startup_pipeline/runtime/recovery_previews/99b93466-4223-4417-8d36-8ab69a2378e8.json'
        data=json.loads(preview.read_text('utf-8'))
        return dict(checked_at=datetime.now(timezone.utc).isoformat(),plans=plans,
            plan_count=len(plans),job_count=db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0],
            confirmed_count=sum(r['status']=='CONFIRMED' for r in plans),old_jobs=old,old_job_hashes=snapshots,
            erroneous_cancelled_jobs=db.execute("SELECT count(*) FROM startup_job_metadata m JOIN publish_jobs j USING(job_id) WHERE m.source_plan_id=? AND j.status='CANCELLED'",('99b93466-4223-4417-8d36-8ab69a2378e8',)).fetchone()[0],
            preview_id=data['plan_id'],preview_count=data['job_count'],unique_count=data['unique_content_count'],
            duplicate=data['duplicate_count'],collision=data['time_collision_count'],daily_distribution=data['daily_distribution'],
            preview_file_sha256=hashlib.sha256(preview.read_bytes()).hexdigest(),
            preview_has_formal_plan=bool(db.execute('SELECT 1 FROM publish_plans WHERE plan_id=?',(data['plan_id'],)).fetchone()),
            ready_selected_count=sum(db.execute("SELECT production_status='READY' AND publish_status='NOT_SCHEDULED' FROM startup_contents WHERE content_id=?",(key,)).fetchone()[0] for key in data['selected_content_ids']),
            global_real_publish_enabled=json.loads((ROOT/'xiaovcat_adapter/config.json').read_text('utf-8'))['real_publish_enabled'])
    finally:db.close()

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--output');args=parser.parse_args()
    result=inspect()
    if args.output:
        from xiaovcat_adapter.desktop_worker.resident_monitor import write_json
        Path(args.output).parent.mkdir(parents=True,exist_ok=True)
        write_json(Path(args.output),result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
